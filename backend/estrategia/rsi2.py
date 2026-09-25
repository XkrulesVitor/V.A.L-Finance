"""
RSI(2) de Connors -- a estrategia de curto prazo mais famosa de "comprar a
queda dentro da alta" (Connors & Alvarez, "Short Term Trading Strategies
That Work", 2008).

- COMPRA quando o fechamento esta acima da media de 200 dias (a alta de
  longo prazo existe) e o RSI de 2 dias esta abaixo de 10 (dois dias de
  queda forte: o "exagero" que costuma devolver).
- VENDE quando o fechamento passa da media de 5 dias -- o repique.

Nao segue tendencia: aposta que a queda curta volta. O lucro de cada
operacao e pequeno e a saida e rapida (no BTC, mediana de 4 dias). A
saida pela media de 5 dias faz o papel do stop gain -- e dinamica, em vez
de um % fixo, que e como o metodo foi publicado.

Parametros do livro, sem ajuste: 200, 2, 10 e 5. O livro tambem mostra
"< 5", mas ele foi o melhor dentro da amostra dos autores; "< 10" e a zona
de compra que eles apresentam primeiro e da ~2x mais operacoes, o que
importa para ter o que medir.

Unico acrescimo do projeto: o stop de catastrofe de 20%, conferido nos
fechamentos de 1h, igual ao das outras carteiras. O original nao tem stop
de preco.
"""

from backtest.engine import BUY, HOLD, NO_TRADE, SELL
from estrategia.indicadores import rsi_de_wilder, sma

SMA_FILTRO = 200
RSI_N = 2
RSI_ENTRA = 10.0
SMA_SAIDA = 5
DIAS_MINIMOS = SMA_FILTRO + 20


def leitura(diarios: list[dict]) -> dict:
    if len(diarios) < DIAS_MINIMOS:
        return {"estrategia": "rsi2", "pronta": False}
    fech = [c["fechamento"] for c in diarios]
    ultimo = fech[-1]
    s200, s5 = sma(fech, SMA_FILTRO), sma(fech, SMA_SAIDA)
    rsi = rsi_de_wilder(fech, RSI_N)
    return {
        "estrategia": "rsi2",
        "pronta": True,
        "fechamento_diario": ultimo,
        "sma200": s200,
        "sma5": s5,
        "rsi2": rsi,
        "em_alta_longa": ultimo > s200,
        "queda_curta": rsi < RSI_ENTRA,
        "repicou": ultimo > s5,
    }


def decidir(l: dict, posicionado: bool, pode_entrar: bool = True) -> str:
    if not l.get("pronta"):
        return HOLD if posicionado else NO_TRADE
    if posicionado:
        return SELL if l["repicou"] else HOLD
    return BUY if l["em_alta_longa"] and l["queda_curta"] and pode_entrar else NO_TRADE


def motivo(l: dict, acao: str) -> str:
    if not l.get("pronta"):
        return "historico diario insuficiente"
    base = f"RSI(2) {l['rsi2']:.1f}"
    if acao == BUY:
        return f"{base}: queda forte dentro da alta de 200 dias"
    if acao == SELL:
        return f"repique: fechou acima da media de {SMA_SAIDA} dias"
    if not l["em_alta_longa"]:
        return f"{base}; abaixo da media de 200 dias (sem alta de longo prazo)"
    return base
