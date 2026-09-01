"""
Estrategias de baseline -- passo 4 do roteiro (secao 10 do ARCHITECTURE.md).

Duas estrategias burras de proposito. Elas nao existem pra ganhar
dinheiro: existem pra dar um piso contra o qual medir o resto.

Sao dois trabalhos ao mesmo tempo, e por isso os passos 3 e 4 andam
juntos:

1. **Validam o motor.** `buy_and_hold` tem resultado fechado, calculavel
   na mao a partir de dois precos e da taxa. Se o motor devolver outro
   numero, o bug esta no motor -- e e melhor descobrir isso agora do que
   no passo 7, olhando um resultado hibrido sem saber de quem e a culpa.

2. **Dao o ponto de comparacao.** A pergunta do projeto (secao 11) nao e
   "a IA ganhou dinheiro" -- ate estrategia ruim ganha em mercado de
   alta. E "a IA bateu uma estrategia idiota, depois de custo, em dado
   que nunca viu". Sem estes numeros, nao ha como responder.

Estrategia e uma funcao pura do contexto: recebe `ContextoDeDecisao`,
devolve BUY, SELL, HOLD ou NO_TRADE. Sem estado entre chamadas -- o que
precisa ser lembrado (tem posicao? a que preco entrou?) ja vem no
contexto, que e o mesmo lugar de onde a estrategia hibrida do passo 7
vai ler.
"""

from backtest.engine import BUY, HOLD, NO_TRADE, SELL, ContextoDeDecisao


def buy_and_hold(contexto: ContextoDeDecisao) -> str:
    """
    Compra tudo assim que possivel e segura ate o fim.

    O motor so liquida no ultimo candle, entao "compra quando estiver
    sem posicao" acontece uma vez so, no comeco -- e o resto do periodo
    e HOLD. E a estrategia mais dificil de bater num ativo que subiu, e
    a mais facil num que caiu; e exatamente por isso que ela e a
    referencia honesta.
    """
    if contexto.posicao_aberta:
        return HOLD
    return BUY


def ema_crossover(contexto: ContextoDeDecisao) -> str:
    """
    Compra quando a EMA de 20 esta acima da EMA de 50, vende quando cai
    abaixo. Usa os indicadores que a Feature Engine ja calcula.

    Sobre "cruzamento": a regra e escrita comparando o nivel das duas
    medias, nao procurando o instante do cruzamento -- e o resultado e o
    mesmo. Como a estrategia esta sempre 100% comprada ou 100% fora, a
    unica barra em que "EMA20 acima" muda de decisao e justamente a
    barra em que o cruzamento aconteceu. Comparar niveis evita ter que
    guardar estado do passo anterior, e evita o bug classico de perder o
    sinal quando as medias empatam por uma barra.

    Enquanto nao houver 50 candles de historico a EMA de 50 nao existe,
    e a Feature Engine devolve `None` (nunca NaN). Sem sinal nao ha
    aposta: NO_TRADE, que e uma decisao de primeira classe no modelo do
    projeto (secao 6), e nao um erro disfarcado.
    """
    features = contexto.features
    rapida, lenta = features["ema_20"], features["ema_50"]

    if rapida is None or lenta is None:
        return HOLD if contexto.posicao_aberta else NO_TRADE

    if rapida > lenta:
        return HOLD if contexto.posicao_aberta else BUY
    return SELL if contexto.posicao_aberta else NO_TRADE


ESTRATEGIAS = {
    "buy_and_hold": buy_and_hold,
    "ema_crossover": ema_crossover,
}


# ====================================================================
# Estrategias experimentais -- passo 7, exploracao
# ====================================================================
#
# Ficam separadas de `ESTRATEGIAS` de proposito. Aquele dicionario e o
# conjunto de baselines canonicas: e contra ele que a hibrida e medida,
# e cada rodada gravada em `backtest_runs` traz aquelas duas linhas de
# referencia. Se estas entrassem la, toda comparacao ja feita mudaria de
# significado retroativamente.
#
# Estas existem pra responder uma pergunta diferente: entre regras
# simples e classicas, quais funcionam nos ativos e no periodo que
# estamos estudando? Custam zero chamada de API -- sao aritmetica sobre
# indicadores que a Feature Engine ja calcula.


def rsi_reversao(contexto: ContextoDeDecisao) -> str:
    """
    Reversao a media: compra sobrevendido (RSI < 30), vende sobrecomprado
    (RSI > 70).

    E a aposta oposta a das medias moveis: assume que exagero volta pro
    meio, em vez de assumir que tendencia continua. Rodar as duas lado a
    lado no mesmo periodo diz qual dos dois regimes o mercado estava.
    """
    rsi = contexto.features["rsi_14"]
    if rsi is None:
        return HOLD if contexto.posicao_aberta else NO_TRADE
    if rsi < 30:
        return HOLD if contexto.posicao_aberta else BUY
    if rsi > 70:
        return SELL if contexto.posicao_aberta else NO_TRADE
    return HOLD if contexto.posicao_aberta else NO_TRADE


def macd_histograma(contexto: ContextoDeDecisao) -> str:
    """
    Momento: comprado enquanto o histograma do MACD for positivo.

    O histograma e a distancia entre a linha e o sinal, entao ele vira
    antes do cruzamento das medias -- e uma versao mais rapida e mais
    ruidosa da mesma ideia do `ema_crossover`. Compara-los mede o custo
    de reagir cedo demais.
    """
    histograma = contexto.features["macd"]["histograma"]
    if histograma is None:
        return HOLD if contexto.posicao_aberta else NO_TRADE
    if histograma > 0:
        return HOLD if contexto.posicao_aberta else BUY
    return SELL if contexto.posicao_aberta else NO_TRADE


def acima_da_ema200(contexto: ContextoDeDecisao) -> str:
    """
    Filtro de regime: comprado so enquanto o preco estiver acima da EMA
    de 200.

    E a regra mais lenta do conjunto, e a mais interessante pra este
    projeto: ela testa a hipotese que o resultado da BNB levantou --
    "operar so quando o ativo esta em tendencia de alta resolve?". Se
    ela sozinha ja capturar a maior parte do ganho, o cerebro precisa
    justificar o proprio custo contra ela, nao contra comprar e segurar.
    """
    ema = contexto.features["ema_200"]
    if ema is None:
        return HOLD if contexto.posicao_aberta else NO_TRADE
    if contexto.preco_atual > ema:
        return HOLD if contexto.posicao_aberta else BUY
    return SELL if contexto.posicao_aberta else NO_TRADE


ESTRATEGIAS_EXPERIMENTAIS = {
    "rsi_reversao": rsi_reversao,
    "macd_histograma": macd_histograma,
    "acima_da_ema200": acima_da_ema200,
}

TODAS_AS_ESTRATEGIAS = {**ESTRATEGIAS, **ESTRATEGIAS_EXPERIMENTAIS}
