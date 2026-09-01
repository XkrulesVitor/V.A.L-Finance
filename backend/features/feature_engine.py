"""
Feature Engine -- passo 2 do roteiro (secao 10 do ARCHITECTURE.md).

Transforma os candles crus que `binance_adapter.buscar_candles()`
devolve num dicionario de indicadores tecnicos. E esse dicionario, e
nunca o candle cru, que o cerebro vai receber no passo 5 -- principio 3
da secao 4: candle cru e caro em token e faz o modelo responder coisas
diferentes pra mercados parecidos; um punhado de indicadores e barato,
estavel e comparavel entre um ciclo e outro.

Por que os indicadores sao calculados aqui, em pandas, em vez de virem
de uma lib de analise tecnica pronta: o `atr_14` que sai daqui e a
entrada do Risk Engine (passo 6) -- e dele que saem o stop-loss e o
take-profit de verdade, justamente os numeros que o LLM tem proibicao
explicita de inventar (principio 2). Amarrar esse valor a uma
dependencia externa e aceitar que uma atualizacao dela mude, em
silencio, o tamanho do risco de cada operacao. Escrito aqui, a formula
fica visivel e auditavel, e a unica dependencia nova do passo 2 e o
proprio pandas -- que o motor de backtest (passo 3) ia exigir de
qualquer jeito.

A funcao publica e `calcular_features(candles)`, e ela e pura: mesma
lista de candles, mesmo resultado, sem consultar relogio nem rede. Isso
e de proposito. O motor de backtest vai chamar exatamente esta funcao
sobre janelas de candles historicos, e ela precisa enxergar so o
passado que recebeu -- qualquer olhada no "agora" viraria vazamento de
informacao futura e inflaria o resultado do backtest.
"""

import math

import pandas as pd

NAO_NUMERO = float("nan")

PERIODO_RSI = 14
PERIODO_ATR = 14
PERIODOS_EMA = (20, 50, 200)
MACD_RAPIDA, MACD_LENTA, MACD_SINAL = 12, 26, 9
JANELA_VOLUME = 20

# Quantos candles pedir ao adapter pra que todos os indicadores tenham
# valor. O piso e ditado por dois lados: a EMA de 200 precisa de 200
# candles so pra existir (e do dobro disso pra ja ter esquecido o
# chute inicial), e o retorno de 7 dias em candles de 1h precisa de 169.
# 400 cobre os dois com folga e ainda cabe numa unica chamada da Binance
# (o limite dela e 1000).
CANDLES_NECESSARIOS = 400

# Janelas de retorno, em milissegundos. Sao convertidas em "quantos
# candles atras" a partir da duracao real inferida dos timestamps, e nao
# fixadas em numero de candles, pra que o mesmo codigo sirva se um dia o
# ciclo rodar em 15m ou 4h em vez de 1h.
HORIZONTES_DE_RETORNO_MS = {
    "retorno_1h": 60 * 60 * 1000,
    "retorno_24h": 24 * 60 * 60 * 1000,
    "retorno_7d": 7 * 24 * 60 * 60 * 1000,
}

COLUNAS_ESPERADAS = ("abertura_em", "abertura", "maxima", "minima", "fechamento", "volume")
COLUNAS_NUMERICAS = ("abertura", "maxima", "minima", "fechamento", "volume")


def calcular_features(candles: list[dict]) -> dict:
    """
    Recebe a lista de candles do adapter e devolve os indicadores prontos
    pro campo `features` (jsonb) da tabela `decisions`.

    Todo valor sai como float ou `None` -- nunca NaN. A distincao importa:
    NaN nao e JSON valido e explodiria na hora de gravar no Supabase, e
    `None` comunica com honestidade o unico caso em que isso acontece --
    historico curto demais pro indicador (uma EMA de 200 com 50 candles
    na mao nao e um numero ruim, e a ausencia de numero).

    Uma ressalva sobre o ultimo candle: a Binance devolve tambem o candle
    em andamento, que ainda nao fechou. Fechamento, maxima e minima dele
    sao parciais, e o volume mais ainda -- um candle de 1h com 5 minutos
    de vida traz uma fracao do volume que ele terminara tendo, o que puxa
    `volume_relativo` pra baixo de forma sistematica. Nao e filtrado aqui
    de proposito: descartar o candle aberto exigiria olhar o relogio, e
    isso quebraria a pureza da funcao de que o backtest depende. Quem
    quiser so candles fechados corta a lista antes de chamar.
    """
    if not candles:
        return _resultado_vazio()

    df = _para_dataframe(candles)
    if df.empty:
        return _resultado_vazio()

    fechamentos = df["fechamento"]
    linha_macd, sinal_macd, histograma_macd = _macd(fechamentos)
    emas = {periodo: _ultimo(_ema(fechamentos, periodo)) for periodo in PERIODOS_EMA}
    retornos = _retornos(df)

    return {
        "rsi_14": _numero(_rsi(fechamentos, PERIODO_RSI)),
        "macd": {
            "linha": _preco(linha_macd),
            "sinal": _preco(sinal_macd),
            "histograma": _preco(histograma_macd),
        },
        "ema_20": _preco(emas[20]),
        "ema_50": _preco(emas[50]),
        "ema_200": _preco(emas[200]),
        "atr_14": _preco(_atr(df, PERIODO_ATR)),
        "volume_relativo": _numero(_volume_relativo(df["volume"], JANELA_VOLUME)),
        "retorno_1h": _numero(retornos["retorno_1h"]),
        "retorno_24h": _numero(retornos["retorno_24h"]),
        "retorno_7d": _numero(retornos["retorno_7d"]),
    }


# --------------------------------------------------------------------
# Preparo dos dados
# --------------------------------------------------------------------


def _para_dataframe(candles: list[dict]) -> pd.DataFrame:
    """Candles do adapter -> DataFrame ordenado do mais antigo pro mais novo."""
    df = pd.DataFrame(candles)

    faltando = [coluna for coluna in COLUNAS_ESPERADAS if coluna not in df.columns]
    if faltando:
        raise ValueError(
            f"candles sem as colunas {faltando} -- esperado o formato de "
            f"binance_adapter.buscar_candles()"
        )

    # A conversao vem antes da ordenacao de proposito: se `abertura_em`
    # chegar como texto (a Binance manda int, mas o motor de backtest do
    # passo 3 vai alimentar esta funcao de outras fontes), ordenar sem
    # converter seria ordem alfabetica -- e a serie sairia embaralhada
    # sem nenhum erro visivel.
    df["abertura_em"] = pd.to_numeric(df["abertura_em"], errors="coerce")
    df = df.sort_values("abertura_em").reset_index(drop=True)

    for coluna in COLUNAS_NUMERICAS:
        df[coluna] = pd.to_numeric(df[coluna], errors="coerce").astype(float)
    return df


def _resultado_vazio() -> dict:
    """
    Mesmo formato, tudo em `None`. Um ciclo sem candles (adapter fora do
    ar, par recem-listado) grava uma linha honesta em vez de derrubar o
    cron job -- o pipeline inteiro seguir rodando vale mais do que essa
    linha ter numeros.
    """
    return {
        "rsi_14": None,
        "macd": {"linha": None, "sinal": None, "histograma": None},
        "ema_20": None,
        "ema_50": None,
        "ema_200": None,
        "atr_14": None,
        "volume_relativo": None,
        "retorno_1h": None,
        "retorno_24h": None,
        "retorno_7d": None,
    }


# --------------------------------------------------------------------
# Medias moveis
# --------------------------------------------------------------------


def _media_recursiva(valores, periodo: int, alpha: float) -> list[float]:
    """
    Media movel exponencial generica, escrita como a recursao que ela e:
    `media = media_anterior + alpha * (valor - media_anterior)`.

    Duas escolhas aqui merecem explicacao.

    A primeira e o seed. A recursao precisa comecar de algum lugar, e o
    ponto de partida e a media simples dos `periodo` primeiros valores --
    a convencao de Wilder, a mesma que TradingView e a maioria das
    plataformas usam. Comecar do primeiro valor da serie (o atalho comum
    em codigo) devolve um numero visivelmente diferente e que so
    converge dezenas de barras depois, o que faria o ATR daqui nao bater
    com o grafico que uma pessoa abre pra conferir.

    A segunda e o loop explicito no lugar de `Series.ewm()`. O `ewm` faz
    a mesma conta, mas a forma como ele trata NaN no inicio da serie e
    detalhe de implementacao do pandas, nao contrato. Como esse numero
    vira stop-loss no passo 6, a recursao fica escrita onde da pra ler.
    Sao poucas centenas de iteracoes por ciclo -- o custo e irrelevante.
    """
    valores = [float(valor) for valor in valores]
    saida = [NAO_NUMERO] * len(valores)
    if periodo < 1 or len(valores) < periodo:
        return saida

    media = sum(valores[:periodo]) / periodo
    saida[periodo - 1] = media
    for i in range(periodo, len(valores)):
        media = media + alpha * (valores[i] - media)
        saida[i] = media
    return saida


def _ema(valores, periodo: int) -> list[float]:
    """EMA classica -- peso 2/(periodo+1), a usada nas medias de tendencia e no MACD."""
    return _media_recursiva(valores, periodo, alpha=2 / (periodo + 1))


def _media_wilder(valores, periodo: int) -> list[float]:
    """
    Media de Wilder (RMA) -- peso 1/periodo, bem mais lenta que a EMA de
    mesmo periodo. E a suavizacao do RSI e do ATR originais; trocar por
    uma EMA comum aqui daria um ATR menor e, por consequencia, stop-loss
    mais apertado do que o pretendido.
    """
    return _media_recursiva(valores, periodo, alpha=1 / periodo)


# --------------------------------------------------------------------
# Indicadores
# --------------------------------------------------------------------


def _rsi(fechamentos: pd.Series, periodo: int) -> float:
    """RSI de Wilder: forca media das altas contra a das quedas, de 0 a 100."""
    variacao = fechamentos.diff().iloc[1:]  # o primeiro candle nao tem variacao
    if len(variacao) < periodo:
        return NAO_NUMERO

    media_alta = _ultimo(_media_wilder(variacao.clip(lower=0), periodo))
    media_queda = _ultimo(_media_wilder((-variacao).clip(lower=0), periodo))
    if _invalido(media_alta) or _invalido(media_queda):
        return NAO_NUMERO

    if media_queda == 0:
        # Sem nenhuma queda na janela o RSI satura em 100. Se tambem nao
        # houve alta (preco travado, tipico de par ilíquido), nao ha forca
        # pra lado nenhum: 50, o ponto neutro, diz isso melhor do que um
        # None que o cerebro leria como "indicador quebrado".
        return 100.0 if media_alta > 0 else 50.0

    forca_relativa = media_alta / media_queda
    return 100 - (100 / (1 + forca_relativa))


def _macd(fechamentos: pd.Series) -> tuple[float, float, float]:
    """
    MACD: distancia entre a EMA rapida e a lenta (linha), a EMA de 9 dessa
    distancia (sinal), e a diferenca entre as duas (histograma).

    Devolve (linha, sinal, histograma) no candle mais recente.
    """
    ema_rapida = _ema(fechamentos, MACD_RAPIDA)
    ema_lenta = _ema(fechamentos, MACD_LENTA)

    linha = [
        rapida - lenta if not (_invalido(rapida) or _invalido(lenta)) else NAO_NUMERO
        for rapida, lenta in zip(ema_rapida, ema_lenta)
    ]

    # O sinal e uma EMA sobre a propria linha, entao a serie precisa
    # chegar la sem os NaN do aquecimento -- eles envenenariam o seed.
    linha_valida = [valor for valor in linha if not _invalido(valor)]
    sinal = _ultimo(_ema(linha_valida, MACD_SINAL))

    valor_linha = _ultimo(linha)
    histograma = (
        valor_linha - sinal if not (_invalido(valor_linha) or _invalido(sinal)) else NAO_NUMERO
    )
    return valor_linha, sinal, histograma


def _amplitude_verdadeira(df: pd.DataFrame) -> pd.Series:
    """
    True Range: o maior entre a amplitude do candle e os dois saltos em
    relacao ao fechamento anterior.

    Os saltos existem por causa de gap: se o preco abre longe de onde
    fechou, `maxima - minima` sozinho subestima o quanto o ativo andou
    naquele periodo, e o ATR sairia menor do que a volatilidade real.
    """
    maxima, minima = df["maxima"], df["minima"]
    fechamento_anterior = df["fechamento"].shift(1)

    amplitude = maxima - minima
    salto_de_alta = (maxima - fechamento_anterior).abs()
    salto_de_baixa = (minima - fechamento_anterior).abs()

    true_range = pd.DataFrame(
        {
            "amplitude": amplitude,
            "salto_de_alta": salto_de_alta,
            "salto_de_baixa": salto_de_baixa,
        }
    ).max(axis=1)
    # O primeiro candle nao tem fechamento anterior: so a amplitude vale.
    true_range.iloc[0] = amplitude.iloc[0]
    return true_range


def _atr(df: pd.DataFrame, periodo: int) -> float:
    """
    ATR -- media de Wilder do True Range. E a medida de "quanto esse ativo
    costuma andar por candle", em unidade de preco.

    E o numero mais importante deste modulo: o Risk Engine (passo 6)
    calcula stop-loss e take-profit como multiplos dele, que e como o
    risco fica amarrado a volatilidade real do ativo em vez de um palpite
    do LLM (principio 2, secao 4).
    """
    if len(df) < periodo + 1:
        return NAO_NUMERO
    return _ultimo(_media_wilder(_amplitude_verdadeira(df), periodo))


def _volume_relativo(volumes: pd.Series, janela: int) -> float:
    """
    Volume do candle atual dividido pela media dos `janela` candles
    anteriores. 1.0 e um candle comum, 2.0 e o dobro do normal.

    A media exclui o candle atual de proposito: incluido, um pico de
    volume entraria no proprio denominador e se subestimaria -- e detectar
    exatamente esses picos e a razao de o indicador existir.
    """
    if len(volumes) < janela + 1:
        return NAO_NUMERO

    atual = float(volumes.iloc[-1])
    media_anterior = float(volumes.iloc[-(janela + 1) : -1].mean())
    if _invalido(media_anterior) or media_anterior <= 0:
        return NAO_NUMERO
    return atual / media_anterior


def _retornos(df: pd.DataFrame) -> dict:
    """
    Variacao percentual do fechamento em cada janela de tempo.

    Quantos candles andar pra tras nao e fixo: vem da duracao real
    inferida dos timestamps. Assim `retorno_24h` continua sendo 24 horas
    de verdade se o ciclo um dia passar a rodar em candles de 15m ou 4h.
    """
    duracao_ms = _duracao_do_candle_ms(df["abertura_em"])
    fechamentos = df["fechamento"]

    retornos = {}
    for nome, horizonte_ms in HORIZONTES_DE_RETORNO_MS.items():
        if duracao_ms is None:
            retornos[nome] = NAO_NUMERO
            continue
        candles_atras = round(horizonte_ms / duracao_ms)
        retornos[nome] = _retorno(fechamentos, candles_atras)
    return retornos


def _duracao_do_candle_ms(aberturas: pd.Series) -> float | None:
    """
    Duracao de um candle, pela mediana da distancia entre as aberturas.
    Mediana e nao media porque buraco no historico (a Binance as vezes
    pula candles em par pouco negociado) distorce a media e nao a mediana.
    """
    if len(aberturas) < 2:
        return None
    duracao = float(aberturas.diff().iloc[1:].median())
    return duracao if duracao > 0 else None


def _retorno(fechamentos: pd.Series, candles_atras: int) -> float:
    """Retorno percentual entre o fechamento atual e o de N candles atras."""
    if candles_atras < 1 or len(fechamentos) <= candles_atras:
        # candles_atras < 1: a janela pedida e menor que um candle (ex.:
        # retorno de 1h com candles de 4h) -- nao da pra responder.
        return NAO_NUMERO

    referencia = float(fechamentos.iloc[-1 - candles_atras])
    if referencia == 0:
        return NAO_NUMERO
    return (float(fechamentos.iloc[-1]) / referencia - 1) * 100


# --------------------------------------------------------------------
# Utilitarios
# --------------------------------------------------------------------


def _ultimo(valores: list[float]) -> float:
    return valores[-1] if len(valores) else NAO_NUMERO


def _invalido(valor) -> bool:
    """NaN ou infinito -- os dois estados que nao podem sair deste modulo."""
    return valor is None or not math.isfinite(float(valor))


def _numero(valor, casas: int = 2):
    """Arredonda em casas fixas. Pra RSI, retornos e volume relativo."""
    if _invalido(valor):
        return None
    return round(float(valor), casas)


def _preco(valor):
    """
    Arredonda preservando 8 digitos significativos, nao casas decimais.

    Preco de cripto varia em ordens de grandeza: 2 casas fixas serve pro
    BTC e transforma o ATR de um par barato (0.00004) em 0.0 -- ou seja,
    em stop-loss zerado quando o Risk Engine entrar. Digito significativo
    funciona nas duas pontas.
    """
    if _invalido(valor):
        return None
    return float(f"{float(valor):.8g}")
