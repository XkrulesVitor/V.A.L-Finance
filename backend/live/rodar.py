"""
Ponto de entrada do forward test -- seis carteiras a partir de setembro/2026.

    python backend/live/rodar.py                          # as 6 carteiras, BTC e ETH
    python backend/live/rodar.py --carteiras T1 G1        # so algumas
    python backend/live/rodar.py --ensaio                 # mostra o estado e sai

## As fases de um ciclo, nesta ordem

0. Catalogo: grava as carteiras em `carteiras` (o site le de la).
1. Dados: candles de 1h e 1d e o preco de cada par, UMA vez por par --
   as seis carteiras veem o mesmo instantaneo.
2. Sem IA: cada carteira x par reivindica o candle e confere stop e alvo.
   T1, T2, G1 e G2 ja decidem aqui. Nenhuma IA e chamada antes disto:
   um provedor lento nunca atrasa um stop.
3. Painel: uma consulta por ativo por dia, as 3 vagas em paralelo, com
   prazo proprio (6 min, e nunca depois dos 11 min do job).
4. T3 e G3 decidem com o veredito do ultimo dia fechado.
5. Explicacoes: as frases das operacoes, no fim, enquanto houver prazo.
6. Conferencia: toda carteira x par tem de terminar com uma linha
   concluida ou um JA_PROCESSADO legitimo.

## Codigo de saida

Vermelho (1): falha de estado, banco ou Binance em qualquer carteira x
par; falha na conferencia; erro de CONFIGURACAO de IA (chave invalida,
pagamento, politica de dados, requisicao malformada). Verde (0): falhas
transitorias de IA (429, 5xx, timeout, JSON invalido), sem quorum, falha
do explicador. Um erro numa carteira x par nao derruba as outras.

Nada e enviado a corretora: o preenchimento e simulado ao preco real.
"""

from dotenv import load_dotenv
load_dotenv()

import argparse  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
from datetime import datetime, timezone  # noqa: E402
from pathlib import Path  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from adapters.binance_adapter import BinanceAdapter  # noqa: E402
from db.supabase_client import get_supabase_client  # noqa: E402
from live.carteiras import CARTEIRAS, POR_ID, sincronizar_catalogo  # noqa: E402
from live.ciclo_carteira import concluir_sem_painel, fase_painel, fase_sem_ia  # noqa: E402
from live.estado import carregar_conta  # noqa: E402
from live.explicador import Explicador, explicar_pendentes  # noqa: E402
from live.mercado import buscar_mercado  # noqa: E402
from live.painel import Painel, compras_do_painel_desde  # noqa: E402

# Tres grandes e tres menores (escolhidas em 25/09/2026: top-20 em valor de
# mercado, liquidez alta na Binance, anos de historico e cobertas pelos
# backtests do projeto -- ARCHITECTURE.md, secao 11, "Seis moedas").
PARES_PADRAO = ["BTCUSDT", "ETHUSDT", "XRPUSDT", "LINKUSDT", "ADAUSDT", "DOGEUSDT"]
PRAZO_JOB_S = 13 * 60          # o workflow mata o job aos 15 min
PRAZO_PAINEL_S = 6 * 60
PAINEL_ATE_S = 11 * 60


def main() -> int:
    ap = argparse.ArgumentParser(description="Ciclo ao vivo das seis carteiras")
    ap.add_argument("--pares", nargs="+", default=PARES_PADRAO)
    ap.add_argument("--carteiras", nargs="+", default=[c.id for c in CARTEIRAS], choices=list(POR_ID))
    ap.add_argument("--ensaio", action="store_true", help="mostra o estado atual e sai, sem gravar nada")
    args = ap.parse_args()

    t0 = time.monotonic()
    supabase = get_supabase_client()
    carteiras = [POR_ID[i] for i in args.carteiras]

    if args.ensaio:
        for c in carteiras:
            for par in args.pares:
                print(f"  {c.id} {carregar_conta(supabase, c.id, par)}")
        return 0

    falhas: list[str] = []

    # ---------- 1. dados ----------
    binance = BinanceAdapter(somente_dados_publicos=True)
    mercados = {}
    for par in args.pares:
        try:
            mercados[par] = buscar_mercado(binance, par)
        except Exception as erro:  # noqa: BLE001
            falhas.append(f"{par}: Binance -- {type(erro).__name__}: {erro}")
            print(f"  [{par}] FALHA nos dados -- {erro}", flush=True)

    # ---------- 2. sem IA ----------
    resultados, pendentes = {}, []
    for par, m in mercados.items():
        for c in carteiras:
            try:
                r = fase_sem_ia(supabase, c, m)
                resultados[(c.id, par)] = r
                if r.pendente:
                    pendentes.append((c, par, r))
                else:
                    print(f"  {r}", flush=True)
            except Exception as erro:  # noqa: BLE001
                falhas.append(f"{c.id} {par}: {type(erro).__name__}: {erro}")
                print(f"  [{c.id} {par}] FALHA -- {type(erro).__name__}: {erro}", flush=True)

    # ---------- 3. painel ----------
    vereditos = {}
    if pendentes:
        agora_s = time.monotonic()
        prazo = min(agora_s + PRAZO_PAINEL_S, t0 + PAINEL_ATE_S)
        try:
            import httpx
            with httpx.Client(follow_redirects=True) as http:
                res = Painel(supabase, http=http).rodar(
                    {p: mercados[p] for p in {par for _, par, _ in pendentes}}, prazo, binance=binance)
            vereditos = res.vereditos
            print(f"  painel: {res.chamadas} chamadas; vereditos "
                  + ", ".join(f"{p} {(v or {}).get('veredito', 'pendente')}" for p, v in vereditos.items()),
                  flush=True)
            for msg in res.erro_de_configuracao:
                falhas.append(f"painel: {msg}")
                print(f"  painel: ERRO DE CONFIGURACAO -- {msg}", flush=True)
        except Exception as erro:  # noqa: BLE001 -- T3/G3 concluem sem decidir; o resto ja rodou
            falhas.append(f"painel: {type(erro).__name__}: {erro}")
            print(f"  painel: FALHA -- {type(erro).__name__}: {erro}", flush=True)

    # ---------- 4. T3 e G3 ----------
    for c, par, r in pendentes:
        m = mercados[par]
        try:
            # Sem veredito do ultimo dia fechado (pendente, ou o painel
            # falhou): `fase_painel` conclui como "painel pendente".
            conta = r.pendente["conta"]
            historico = None
            if c.com_alvo and not conta.armado and conta.ultima_saida_em:
                historico = compras_do_painel_desde(supabase, par, conta.ultima_saida_em)
            final = fase_painel(supabase, c, m, r.pendente, vereditos.get(par), historico)
        except Exception as erro:  # noqa: BLE001
            falhas.append(f"{c.id} {par}: {type(erro).__name__}: {erro}")
            print(f"  [{c.id} {par}] FALHA -- {type(erro).__name__}: {erro}", flush=True)
            # Se a conta JA mudou (a compra/venda foi gravada e so a linha da
            # decisao falhou), concluir como "nao operou" mentiria no
            # historico: a linha fica 'processando' e o proximo ciclo varre.
            try:
                agora = carregar_conta(supabase, c.id, par)
                antes = r.pendente["conta"]
                if (agora.quantidade, agora.caixa) != (antes.quantidade, antes.caixa):
                    print(f"  [{c.id} {par}] operacao gravada, decisao sem conclusao -- linha fica orfa", flush=True)
                    continue
                final = concluir_sem_painel(supabase, c, m, r.pendente, "falha ao aplicar o veredito")
            except Exception:  # noqa: BLE001 -- linha fica orfa; o proximo ciclo varre de novo
                continue
        resultados[(c.id, par)] = final
        print(f"  {final}", flush=True)

    # ---------- 5. explicacoes ----------
    try:
        n = explicar_pendentes(supabase, Explicador(), POR_ID, datetime.now(timezone.utc),
                               lambda: time.monotonic() < t0 + PRAZO_JOB_S - 45)
        if n:
            print(f"  explicacoes: {n} pedidas", flush=True)
    except Exception as erro:  # noqa: BLE001 -- frase e opcional
        print(f"  explicacoes: falha -- {erro}", flush=True)

    # ---------- catalogo ----------
    # Depois das fases, e so com as carteiras que concluiram o ciclo nos dois
    # pares: `ativa_desde` (o D0 de cada uma) nao pode ser gravado numa
    # execucao em que ela falhou -- por exemplo, antes da etapa B da migracao.
    concluidas = [c.id for c in carteiras if mercados and all(
        (r := resultados.get((c.id, par))) is not None and r.acao != "PENDENTE" for par in mercados)]
    try:
        sincronizar_catalogo(supabase, ativas=concluidas)
    except Exception as erro:  # noqa: BLE001 -- o catalogo e so para o site
        print(f"  aviso: catalogo nao sincronizado -- {erro}", flush=True)

    # ---------- 6. conferencia ----------
    for c in carteiras:
        for par in mercados:
            r = resultados.get((c.id, par))
            if r is None or r.acao == "PENDENTE":
                falhas.append(f"{c.id} {par}: ciclo sem conclusao")

    if falhas:
        print(f"\n{len(falhas)} falha(s):")
        for f in falhas:
            print(f"  - {f}")
        return 1
    print("\nok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
