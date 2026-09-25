"""
Indicadores diarios usados pelas estrategias de `estrategia/`.

Funcoes puras sobre listas de candles diarios JA FECHADOS, no formato do
adapter da Binance (`abertura_em`, `abertura`, `maxima`, `minima`,
`fechamento`, `fechamento_em`). O backtest monta esses candles agregando
os de 1h de cada dia UTC (`diarios_de_horarios`); ao vivo eles vem prontos
do kline "1d". Os dois caminhos dao os mesmos numeros: o kline diario da
Binance e exatamente a agregacao dos de 1h do mesmo dia.

Todas devolvem None quando o historico e curto demais -- sem dado, sem
sinal. Nenhuma completa lacuna com valor inventado.
"""

DIA_MS = 86_400_000


def diarios_de_horarios(horarios: list[dict]) -> list[dict]:
    """Agrega candles de 1h em diarios UTC (dia em andamento incluso)."""
    dias: dict[int, dict] = {}
    for c in horarios:
        d = c["abertura_em"] // DIA_MS
        atual = dias.get(d)
        if atual is None:
            dias[d] = {
                "abertura_em": d * DIA_MS,
                "abertura": c["abertura"],
                "maxima": c["maxima"],
                "minima": c["minima"],
                "fechamento": c["fechamento"],
                "fechamento_em": (d + 1) * DIA_MS - 1,
            }
        else:
            atual["maxima"] = max(atual["maxima"], c["maxima"])
            atual["minima"] = min(atual["minima"], c["minima"])
            atual["fechamento"] = c["fechamento"]
    return [dias[d] for d in sorted(dias)]


def sma(valores: list[float], n: int) -> float | None:
    if len(valores) < n:
        return None
    return sum(valores[-n:]) / n


def true_ranges(diarios: list[dict]) -> list[float]:
    """TR_t = max(H-L, |H-C_ant|, |L-C_ant|); o primeiro dia usa so H-L."""
    saida = []
    for i, c in enumerate(diarios):
        if i == 0:
            saida.append(c["maxima"] - c["minima"])
            continue
        ant = diarios[i - 1]["fechamento"]
        saida.append(max(c["maxima"] - c["minima"], abs(c["maxima"] - ant), abs(c["minima"] - ant)))
    return saida


def media_de_wilder(valores: list[float], n: int) -> float | None:
    """
    Media de Wilder: a primeira e a media simples dos n primeiros valores,
    depois m_t = ((n-1) m_{t-1} + v_t) / n. E o ATR de Wilder (n = 14) e o
    N das Tartarugas (n = 20). Depende de todo o historico dado; quanto
    mais longo, menos o ponto de partida pesa -- (1-1/n)^k.
    """
    if len(valores) < n:
        return None
    m = sum(valores[:n]) / n
    for v in valores[n:]:
        m = ((n - 1) * m + v) / n
    return m


def atr(diarios: list[dict], n: int = 14) -> float | None:
    # O TR do primeiro dia nao tem fechamento anterior; fica fora.
    return media_de_wilder(true_ranges(diarios)[1:], n)


def rsi_de_wilder(fechamentos: list[float], n: int) -> float | None:
    """RSI de Wilder. 100 quando nao houve queda no periodo."""
    if len(fechamentos) < n + 1:
        return None
    difs = [fechamentos[i] - fechamentos[i - 1] for i in range(1, len(fechamentos))]
    ganhos = [max(d, 0.0) for d in difs]
    perdas = [max(-d, 0.0) for d in difs]
    g = media_de_wilder(ganhos, n)
    p = media_de_wilder(perdas, n)
    if p == 0:
        return 100.0
    return 100.0 - 100.0 / (1.0 + g / p)
