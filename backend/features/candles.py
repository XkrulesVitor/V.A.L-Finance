"""
Filtro de candles fechados -- a metade "consciente do relogio" do passo 2.

Existe pra resolver a ressalva que a Feature Engine registra e nao trata:
a Binance devolve tambem o candle em andamento, que ainda nao fechou. O
volume dele e parcial -- um candle de 1h com cinco minutos de vida traz
uma fracao do volume que vai terminar tendo -- e isso puxa o
`volume_relativo` pra baixo de forma sistematica, nao aleatoria. Um vies
que sempre aponta pro mesmo lado e pior que ruido: o cerebro passaria a
ler "volume abaixo do normal" em todo ciclo ao vivo.

Por que o filtro mora aqui e nao dentro da Feature Engine: a Feature
Engine e pura de proposito (mesma entrada, mesma saida, sem olhar
relogio nem rede), e o motor de backtest depende disso pra nao vazar
futuro. Uma funcao que pergunta as horas nao pode viver la dentro. Entao
quem filtra e quem chama -- exatamente como a ressalva original aponta.

Quem usa: o caminho AO VIVO (cron job, cerebro). O backtest nao usa e
nao deve usar: la todo candle ja fechou faz tempo, e chamar isto so
introduziria dependencia de relogio num caminho que precisa ser
deterministico.
"""

import statistics
import time

CAMPO_FECHAMENTO = "fechamento_em"


def somente_fechados(candles: list[dict], agora_ms: int | None = None) -> list[dict]:
    """
    Devolve so os candles que ja fecharam, descartando o em andamento.

    `agora_ms` existe pra testar sem depender do relogio da maquina; em
    producao fica em None e o relogio e consultado aqui.

    Quando o candle traz `fechamento_em` (todo candle vindo do adapter
    traz), a resposta e direta. Quando nao traz -- candle de arquivo
    antigo, ou de outra fonte no futuro -- a duracao e inferida da
    mediana das distancias entre aberturas, e o fim do candle vira
    `abertura + duracao`. Mediana e nao media porque buraco no historico
    distorce a media e nao a mediana.
    """
    if not candles:
        return []

    agora_ms = int(time.time() * 1000) if agora_ms is None else agora_ms
    ordenados = sorted(candles, key=lambda candle: candle["abertura_em"])
    duracao_ms = _duracao_do_candle_ms(ordenados)

    return [
        candle for candle in ordenados if _ja_fechou(candle, agora_ms, duracao_ms)
    ]


def _ja_fechou(candle: dict, agora_ms: int, duracao_ms: float | None) -> bool:
    fim = candle.get(CAMPO_FECHAMENTO)
    if fim is None:
        if duracao_ms is None:
            # Um candle so, sem campo de fechamento e sem como inferir
            # duracao: nao da pra afirmar que fechou. Na duvida, descarta
            # -- decidir com dado parcial e o problema que este modulo existe
            # pra evitar.
            return False
        fim = candle["abertura_em"] + duracao_ms
    return agora_ms >= fim


def _duracao_do_candle_ms(ordenados: list[dict]) -> float | None:
    if len(ordenados) < 2:
        return None
    distancias = [
        ordenados[i]["abertura_em"] - ordenados[i - 1]["abertura_em"]
        for i in range(1, len(ordenados))
    ]
    duracao = statistics.median(distancias)
    return float(duracao) if duracao > 0 else None
