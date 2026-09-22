"""
Estudo 2: ensemble de tendencia DIARIA -- o design que a literatura sustenta,
testado nas mesmas 64 janelas do estudo de votacao.

    python backend/backtest/estudo_tendencia_diaria.py

Zero chamada de LLM.

## Por que este estudo existe

O estudo de votacao (estudo_votacao.py) mostrou que votar entre 7 regras
tecnicas de familias diferentes nao gera vantagem: com limiar baixo vira
rodizio (60+ trades por janela), com limiar alto so reduz exposicao. A
pesquisa (base-de-conhecimento-investimentos.md, frente "estrategias")
aponta o unico ensemble com precedente empirico em cripto: VARIAS versoes
da MESMA ideia robusta -- tendencia em horizonte diario, varios prazos --
com posicao proporcional aos votos (Zarattini, Pagani & Barbon 2025;
Detzel et al. 2021; Liu & Tsyvinski 2021).

O design abaixo veio da literatura, NAO dos nossos resultados. E isso que o
torna um teste honesto: nada aqui foi ajustado olhando estas 64 janelas.

## Pre-registro (fixado antes da primeira execucao)

Votantes: fechamento diario > media simples dos ultimos L fechamentos
diarios, para L em {10, 20, 30, 50, 70, 100} dias. Seis votos.

O sinal e calculado no fechamento de cada dia UTC com dados ate aquele dia,
e so vale a partir do dia seguinte -- sem olhar o dia que ainda nao fechou.

Duas configuracoes, e so duas:
  - fracionaria: exposicao = votos/6 (0%, 17%, ..., 100%), rebalanceada no
    primeiro candle de cada dia quando o alvo muda. Taxa de 0,1% sobre o
    valor negociado.
  - binaria: 100% dentro quando >= 4 de 6 votos, 100% fora quando <= 2 de 6,
    mantem entre os dois (histerese). Roda no motor de backtest padrao.

Sem take-profit. Sem stop por ATR. A saida e a reversao do sinal.

## Benchmark justo

Alem do comprar-e-segurar, cada configuracao e comparada com o
comprar-e-segurar de EXPOSICAO EQUIVALENTE: a fracao f do capital no ativo
(resto em caixa) cujo drawdown maximo iguala o da estrategia. Estrategia que
fica pouco tempo comprada reduz drawdown por definicao; a pergunta e se ela
faz isso MELHOR do que simplesmente manter menos dinheiro no ativo.
"""

import json
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backtest.engine import BUY, HOLD, rodar_backtest  # noqa: E402
from backtest.estudo_votacao import ATIVOS, FIM, HORAS_JANELA, N_JANELAS  # noqa: E402
from backtest.run_baseline import buscar_historico_com_cache  # noqa: E402
from estrategia import tendencia_diaria as regra  # noqa: E402

# A regra mora em estrategia/tendencia_diaria.py -- o mesmo modulo que o
# ciclo ao vivo importa. Este estudo so a alimenta com historico.
LOOKBACKS = regra.LOOKBACKS
AQUECIMENTO_DIAS = 110
TAXA = 0.001
DIA_MS = 86_400_000
SAIDA = Path(__file__).resolve().parent / "resultados" / "estudo_tendencia_diaria.json"


def baixar_com_aquecimento(ativo):
    ini = int((FIM.timestamp() - N_JANELAS * HORAS_JANELA * 3600 - AQUECIMENTO_DIAS * 86400) * 1000)
    fim = int(FIM.timestamp() * 1000)
    return buscar_historico_com_cache(ativo, "1h", str(ini), str(fim))


def votos_por_dia(serie):
    """
    dia (inteiro UTC) -> votos (0..6) calculados no FECHAMENTO daquele dia.
    Quem usa deve consultar o dia ANTERIOR ao candle corrente.
    """
    fechamentos = {}
    for c in serie:
        fechamentos[c["abertura_em"] // DIA_MS] = c["fechamento"]  # ultimo candle do dia vence
    dias = sorted(fechamentos)
    closes = [fechamentos[d] for d in dias]
    votos = {}
    for i, d in enumerate(dias):
        v = regra.votos(closes[max(0, i + 1 - max(LOOKBACKS)) : i + 1])
        if v is not None:
            votos[d] = v
    return votos


class Binaria:
    """>= 4 de 6 entra, <= 2 de 6 sai, mantem entre os dois."""

    def __init__(self, votos):
        self.votos = votos
        self.__name__ = "tendencia_binaria"

    def __call__(self, ctx):
        dia_anterior = ctx.candle_atual["abertura_em"] // DIA_MS - 1
        return regra.decidir(self.votos.get(dia_anterior), ctx.posicao_aberta)


def simular_fracionaria(candles, votos, alvo_fixo=None):
    """
    Exposicao = votos/6, rebalanceada no primeiro candle de cada dia, ao
    preco de abertura, com taxa sobre o valor negociado. `alvo_fixo` ignora
    os votos (usado para conferir contra o comprar-e-segurar do motor).
    """
    caixa, qtd = 1.0, 0.0
    curva = []
    trocas = 0
    dia_atual = None
    for c in candles:
        dia = c["abertura_em"] // DIA_MS
        if dia != dia_atual:
            dia_atual = dia
            if alvo_fixo is not None:
                alvo = alvo_fixo
            else:
                v = votos.get(dia - 1)
                alvo = None if v is None else v / len(LOOKBACKS)
            if alvo is not None:
                preco = c["abertura"]
                total = caixa + qtd * preco
                atual = qtd * preco / total if total else 0.0
                if abs(alvo - atual) > 1e-9:
                    delta_valor = alvo * total - qtd * preco
                    taxa = abs(delta_valor) * TAXA
                    qtd += delta_valor / preco
                    caixa -= delta_valor + taxa
                    trocas += 1
        curva.append(caixa + qtd * c["fechamento"])
    final = caixa + qtd * candles[-1]["fechamento"] * (1 - TAXA)  # liquida no fim, como o motor
    pico, dd = curva[0], 0.0
    for v in curva:
        pico = max(pico, v)
        dd = min(dd, v / pico - 1)
    return {"retorno": (final - 1) * 100, "drawdown": dd * 100, "trocas": trocas}


def bh_fracao(candles, f):
    p0 = candles[0]["abertura"]
    q = f * (1 - TAXA) / p0
    caixa = 1 - f
    pico, dd = None, 0.0
    for c in candles:
        v = caixa + q * c["fechamento"]
        pico = v if pico is None else max(pico, v)
        dd = min(dd, v / pico - 1)
    final = caixa + q * candles[-1]["fechamento"] * (1 - TAXA)
    return (final - 1) * 100, dd * 100


def bh_mesma_exposicao(candles, drawdown_alvo):
    lo, hi = 0.0, 1.0
    for _ in range(30):
        mid = (lo + hi) / 2
        if bh_fracao(candles, mid)[1] > drawdown_alvo:
            lo = mid
        else:
            hi = mid
    return bh_fracao(candles, lo)[0], lo


def main():
    global FIM, SAIDA
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--fim", help="fim do periodo (AAAA-MM-DD); padrao 2026-09-01")
    args = ap.parse_args()
    if args.fim:
        # Teste FORA DA AMOSTRA: mesma configuracao pre-registrada, outro
        # periodo. Nada muda alem da data -- esse e o ponto.
        FIM = datetime.fromisoformat(args.fim).replace(tzinfo=timezone.utc)
        SAIDA = SAIDA.with_name(f"estudo_tendencia_diaria_ate_{args.fim}.json")
        print(f"periodo: 8 janelas de 91 dias terminando em {FIM.date()}")
    linhas = []
    conferencia = []
    for ativo in ATIVOS:
        serie = baixar_com_aquecimento(ativo)
        votos = votos_por_dia(serie)
        inicio_janelas = int((FIM.timestamp() - N_JANELAS * HORAS_JANELA * 3600) * 1000)
        base = next(i for i, c in enumerate(serie) if c["abertura_em"] >= inicio_janelas)
        for j in range(N_JANELAS):
            candles = serie[base + j * HORAS_JANELA : base + (j + 1) * HORAS_JANELA]
            if len(candles) < HORAS_JANELA * 0.95:
                continue
            # Janela so conta se a regra ja tem voto no primeiro dia dela.
            # Sem isto, um ativo listado ha pouco (SOL em ago/2020) teria
            # janelas em que a regra passa semanas sem poder votar e o b&h
            # compra no primeiro candle -- a comparacao mediria o aquecimento,
            # nao a regra. Nos periodos ja rodados todas as janelas tinham voto.
            if votos.get(candles[0]["abertura_em"] // DIA_MS - 1) is None:
                print(f"  {ativo} j{j} fora: sem voto no inicio da janela (historico curto)")
                continue
            var = (candles[-1]["fechamento"] / candles[0]["abertura"] - 1) * 100
            reg = "alta" if var > 10 else "baixa" if var < -10 else "lateral"

            bh = rodar_backtest(candles, lambda ctx: HOLD if ctx.posicao_aberta else BUY,
                                nome_estrategia="comprar_e_segurar").metricas
            # conferencia do simulador: exposicao fixa 100% tem que dar o b&h do motor
            chk = simular_fracionaria(candles, votos, alvo_fixo=1.0)
            conferencia.append(abs(chk["retorno"] - bh["retorno_total_pct"]))

            b = rodar_backtest(candles, Binaria(votos), nome_estrategia="tendencia_binaria").metricas
            f = simular_fracionaria(candles, votos)

            for nome, ret, dd, trades in (
                ("comprar_e_segurar", bh["retorno_total_pct"], bh["max_drawdown_pct"], 1),
                ("tendencia_binaria", b["retorno_total_pct"], b["max_drawdown_pct"], b["numero_trades"]),
                ("tendencia_fracionaria", f["retorno"], f["drawdown"], f["trocas"]),
            ):
                eq, fr = bh_mesma_exposicao(candles, dd) if nome != "comprar_e_segurar" else (ret, 1.0)
                linhas.append({"ativo": ativo, "janela": j, "regime": reg, "config": nome,
                               "retorno": round(ret, 2), "drawdown": round(dd, 2), "trades": trades,
                               "bh_mesma_exposicao": round(eq, 2), "fracao_equivalente": round(fr, 3),
                               "bh": bh["retorno_total_pct"]})
            print(f"  {ativo} j{j} {reg:<7} {var:+7.1f}%  bin {b['retorno_total_pct']:+7.2f}  frac {f['retorno']:+7.2f}", flush=True)

    print(f"\nconferencia do simulador (|frac 100% - b&h do motor|): max {max(conferencia):.4f} pts")
    print()
    print(f"{'config':<24}{'ret':>7}{'med':>7}{'dd':>8}{'trades':>8}{'>bh ret':>9}{'>bh dd':>8}{'vs b&h mesma exp':>18}{'vence':>8}")
    print("-" * 98)
    resumo = {}
    for cfg in ("comprar_e_segurar", "tendencia_binaria", "tendencia_fracionaria"):
        L = [l for l in linhas if l["config"] == cfg]
        vs_eq = [l["retorno"] - l["bh_mesma_exposicao"] for l in L]
        r = {
            "retorno_medio": round(statistics.mean(l["retorno"] for l in L), 2),
            "retorno_mediano": round(statistics.median(l["retorno"] for l in L), 2),
            "drawdown_medio": round(statistics.mean(l["drawdown"] for l in L), 2),
            "trades_medio": round(statistics.mean(l["trades"] for l in L), 1),
            "vence_bh_retorno": sum(1 for l in L if l["retorno"] > l["bh"]),
            "vence_bh_drawdown": sum(1 for l in L if l["drawdown"] > [x for x in linhas if x["config"] == "comprar_e_segurar" and x["ativo"] == l["ativo"] and x["janela"] == l["janela"]][0]["drawdown"]),
            "vs_bh_mesma_exposicao": round(statistics.mean(vs_eq), 2),
            "vence_bh_mesma_exposicao": sum(1 for d in vs_eq if d > 0),
            "n": len(L),
            "por_regime": {},
        }
        for reg in ("alta", "lateral", "baixa"):
            R = [l for l in L if l["regime"] == reg]
            if R:
                r["por_regime"][reg] = {
                    "n": len(R),
                    "vs_bh": round(statistics.mean(l["retorno"] - l["bh"] for l in R), 2),
                    "vs_bh_mesma_exposicao": round(statistics.mean(l["retorno"] - l["bh_mesma_exposicao"] for l in R), 2),
                }
        resumo[cfg] = r
        print(f"{cfg:<24}{r['retorno_medio']:>7.2f}{r['retorno_mediano']:>7.2f}{r['drawdown_medio']:>8.2f}"
              f"{r['trades_medio']:>8.1f}{r['vence_bh_retorno']:>6}/{r['n']}{r['vence_bh_drawdown']:>5}/{r['n']}"
              f"{r['vs_bh_mesma_exposicao']:>+18.2f}{r['vence_bh_mesma_exposicao']:>5}/{r['n']}")
    print("\npor regime (vs b&h | vs b&h mesma exposicao):")
    for cfg in ("tendencia_binaria", "tendencia_fracionaria"):
        pr = resumo[cfg]["por_regime"]
        print(f"  {cfg:<24}" + "  ".join(f"{k} {v['vs_bh']:+7.2f} | {v['vs_bh_mesma_exposicao']:+6.2f} (n={v['n']})" for k, v in pr.items()))

    SAIDA.parent.mkdir(parents=True, exist_ok=True)
    SAIDA.write_text(json.dumps({"gerado_em": datetime.now(timezone.utc).isoformat(),
                                 "lookbacks": LOOKBACKS, "resumo": resumo, "linhas": linhas},
                                ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nresultado completo em {SAIDA}")


if __name__ == "__main__":
    main()
