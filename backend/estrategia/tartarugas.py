"""
Tartarugas (Turtle Trading), Sistema 2 -- a estrategia de tendencia mais
famosa do mercado, na versao que cabe neste projeto.

Richard Dennis e William Eckhardt ensinaram as regras a um grupo de
iniciantes em 1983 para provar que se aprende a operar (Faith, "Way of
the Turtle", 2007; regras originais publicadas em 2003). O Sistema 2 e o
de prazo longo:

- COMPRA quando o fechamento rompe a maior alta dos 55 dias anteriores;
- VENDE quando o fechamento rompe a menor baixa dos 20 dias anteriores;
- STOP a 2N abaixo da entrada, sendo N a volatilidade diaria (media de
  Wilder de 20 dias do true range).

## Desvios do original (registrados antes de testar)

1. So comprado: a conta e a vista, sem venda a descoberto.
2. Sem piramidacao (o original somava ate 4 unidades a cada +N/2). All-in
   ja equivale a carga cheia de 4 unidades, so que atingida no rompimento.
3. Canais de FECHAMENTO diario, com o sinal no fechamento UTC, em vez do
   toque intradiario na maxima. E a convencao dos testes em cripto
   (Gerritsen 2020; Zarattini, Pagani & Barbon 2025) e sai no mesmo
   horario das Reguas.
4. Stop conferido nos fechamentos de 1h, com a infraestrutura do stop de
   catastrofe.
5. Piso de 20%: o stop nunca fica mais longe que 20% da entrada. So morde
   quando N passa de 10% do preco -- quase nunca em BTC e ETH desde 2022.

Nenhum parametro foi ajustado: 55, 20, 20 e 2 sao os do livro.
"""

from backtest.engine import BUY, HOLD, NO_TRADE, SELL
from estrategia.indicadores import media_de_wilder, true_ranges

ENTRADA_DIAS = 55
SAIDA_DIAS = 20
N_DIAS = 20
STOP_EM_N = 2.0
PISO_DO_STOP = 0.20
# Com 150 dias o ponto de partida do N pesa (19/20)^130 < 0,2%.
DIAS_MINIMOS = 150


def leitura(diarios: list[dict]) -> dict:
    """O que a regra ve no ultimo dia fechado da lista."""
    if len(diarios) < DIAS_MINIMOS:
        return {"estrategia": "tartarugas", "pronta": False}
    fech = [c["fechamento"] for c in diarios]
    ultimo = fech[-1]
    maxima = max(fech[-ENTRADA_DIAS - 1 : -1])
    minima = min(fech[-SAIDA_DIAS - 1 : -1])
    n = media_de_wilder(true_ranges(diarios)[1:], N_DIAS)
    return {
        "estrategia": "tartarugas",
        "pronta": True,
        "fechamento_diario": ultimo,
        "maxima_55d": maxima,
        "minima_20d": minima,
        "n": n,
        "n_pct": n / ultimo * 100.0,
        "rompeu_alta": ultimo > maxima,
        "rompeu_baixa": ultimo < minima,
    }


def decidir(l: dict, posicionado: bool, pode_entrar: bool = True) -> str:
    if not l.get("pronta"):
        return HOLD if posicionado else NO_TRADE
    if posicionado:
        return SELL if l["rompeu_baixa"] else HOLD
    return BUY if l["rompeu_alta"] and pode_entrar else NO_TRADE


def nivel_de_stop(preco_entrada: float, n: float) -> float:
    """2N abaixo da entrada, nunca mais longe que o piso de 20%."""
    return max(preco_entrada - STOP_EM_N * n, preco_entrada * (1.0 - PISO_DO_STOP))


def motivo(l: dict, acao: str) -> str:
    if not l.get("pronta"):
        return "historico diario insuficiente"
    if acao == BUY:
        return f"fechou acima da maior alta de {ENTRADA_DIAS} dias"
    if acao == SELL:
        return f"fechou abaixo da menor baixa de {SAIDA_DIAS} dias"
    if l["rompeu_alta"]:
        return "rompimento de alta, mas aguardando um dia fechar depois do stop"
    return f"sem rompimento (alta de {ENTRADA_DIAS}d a {l['maxima_55d']:,.2f}, baixa de {SAIDA_DIAS}d a {l['minima_20d']:,.2f})"
