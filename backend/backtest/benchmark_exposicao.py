"""
Benchmark de exposicao equivalente para os estudos de votacao e de
tendencia diaria.

    python backend/backtest/benchmark_exposicao.py

## A pergunta

Uma estrategia que fica pouco tempo comprada tem drawdown menor por
definicao. Isso nao e merito: manter so 30% do capital no ativo tambem
tem. A pergunta certa e se a estrategia reduz o risco MELHOR do que
simplesmente segurar menos.

## Duas versoes, uma otimista e uma justa

- "por janela" (otimista para o b&h): em cada janela, a fracao f cujo
  drawdown iguala o da estrategia NAQUELA janela. Usa o drawdown que
  aconteceu -- informacao que ninguem teria no inicio -- e por isso
  favorece o b&h.
- "fixa" (justa): UMA fracao f por configuracao, a mesma em todas as
  janelas, escolhida para que o drawdown MEDIO do b&h-f iguale o drawdown
  medio da estrategia. Nao olha janela nenhuma individualmente.

Se a estrategia perde nas duas, o resultado nao depende da escolha do
benchmark.
"""

import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import backtest.estudo_votacao as ev  # noqa: E402
from backtest.estudo_votacao import ATIVOS, HORAS_JANELA, N_JANELAS, baixar  # noqa: E402

TAXA = 0.001
GRADE = [i / 200 for i in range(201)]  # f de 0 a 1 em passos de 0,5%
PASTA = Path(__file__).resolve().parent / "resultados"


def curva_bh(candles):
    """Para cada f da grade: (retorno %, drawdown %) do b&h com fracao f."""
    p0 = candles[0]["abertura"]
    fech = [c["fechamento"] for c in candles]
    ult = fech[-1]
    saida = []
    for f in GRADE:
        q = f * (1 - TAXA) / p0
        caixa = 1 - f
        pico, dd = None, 0.0
        for p in fech:
            v = caixa + q * p
            pico = v if pico is None else max(pico, v)
            dd = min(dd, v / pico - 1)
        final = caixa + q * ult * (1 - TAXA)
        saida.append(((final - 1) * 100, dd * 100))
    return saida


def main():
    import argparse
    from datetime import datetime, timezone
    ap = argparse.ArgumentParser()
    ap.add_argument("--fim", help="avalia o estudo de tendencia fora da amostra terminado nesta data")
    args = ap.parse_args()
    arquivos = ("estudo_votacao.json", "estudo_tendencia_diaria.json")
    if args.fim:
        ev.FIM = datetime.fromisoformat(args.fim).replace(tzinfo=timezone.utc)
        arquivos = (f"estudo_tendencia_diaria_ate_{args.fim}.json",)
    tabelas = {}
    for a in ATIVOS:
        serie = baixar(a)
        for j in range(N_JANELAS):
            c = serie[j * HORAS_JANELA : (j + 1) * HORAS_JANELA]
            if len(c) >= HORAS_JANELA * 0.95:
                tabelas[(a, j)] = curva_bh(c)
    print(f"{len(tabelas)} janelas, grade de {len(GRADE)} fracoes\n")

    fontes = []
    for nome in arquivos:
        arq = PASTA / nome
        if arq.exists():
            fontes.append((nome, json.loads(arq.read_text(encoding="utf-8"))["linhas"]))

    print(f"{'config':<24}{'ret':>7}{'dd':>8} | {'f fixa':>7}{'b&h-f':>8}{'vantagem':>10} | {'por janela':>11}")
    print("-" * 82)
    resumo = {}
    for nome, linhas in fontes:
        for cfg in sorted({l["config"] for l in linhas} - {"comprar_e_segurar"}):
            L = [l for l in linhas if l["config"] == cfg and (l["ativo"], l["janela"]) in tabelas]
            dd_medio = statistics.mean(l["drawdown"] for l in L)
            ret_medio = statistics.mean(l["retorno"] for l in L)

            # fixa: f unico cujo drawdown medio sobre as janelas iguala o da estrategia
            melhor_f, melhor_gap = 0.0, float("inf")
            for k, f in enumerate(GRADE):
                ddf = statistics.mean(tabelas[(l["ativo"], l["janela"])][k][1] for l in L)
                if abs(ddf - dd_medio) < melhor_gap:
                    melhor_f, melhor_gap, kf = f, abs(ddf - dd_medio), k
            ret_f = statistics.mean(tabelas[(l["ativo"], l["janela"])][kf][0] for l in L)

            # por janela (otimista para o b&h)
            difs = []
            for l in L:
                t = tabelas[(l["ativo"], l["janela"])]
                k = min(range(len(GRADE)), key=lambda i: abs(t[i][1] - l["drawdown"]) if t[i][1] >= l["drawdown"] - 1e-9 else 1e9)
                difs.append(l["retorno"] - t[k][0])

            resumo[cfg] = {"retorno": round(ret_medio, 2), "drawdown": round(dd_medio, 2),
                           "f_fixa": melhor_f, "bh_f_fixa": round(ret_f, 2),
                           "vantagem_f_fixa": round(ret_medio - ret_f, 2),
                           "vantagem_por_janela": round(statistics.mean(difs), 2),
                           "vence_por_janela": sum(1 for d in difs if d > 0), "n": len(L)}
            r = resumo[cfg]
            print(f"{cfg:<24}{r['retorno']:>7.2f}{r['drawdown']:>8.2f} | {r['f_fixa']:>6.0%}{r['bh_f_fixa']:>8.2f}"
                  f"{r['vantagem_f_fixa']:>+10.2f} | {r['vantagem_por_janela']:>+7.2f} {r['vence_por_janela']:>2}/{r['n']}")

    (PASTA / (f"benchmark_exposicao_ate_{args.fim}.json" if args.fim else "benchmark_exposicao.json")).write_text(json.dumps(resumo, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
