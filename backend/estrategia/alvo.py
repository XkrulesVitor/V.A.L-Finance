"""
Stop gain: vender quando a operacao atinge um alvo de lucro.

## O alvo

Fixado na entrada e nunca recalculado:

    alvo = preco_entrada x (1 + 3 x ATR14 / fechamento)

onde ATR14 e a volatilidade diaria (media de Wilder de 14 dias do true
range) no ultimo dia fechado antes da compra. Em % do preco, o alvo
acompanha a agitacao da moeda: em 23/09/2026 dava ~+9% no BTC e ~+12% no
ETH. Tres ATRs e o multiplo classico de alvo em sistemas de swing trade;
um % fixo igual para BTC e ETH ignoraria que o ETH anda ~30% mais.

O stop de perda continua o de catastrofe, -20% (nenhum stop mais apertado:
em cripto diario, stops curtos caem no ruido -- ARCHITECTURE.md, secao 11).
A conta de equilibrio que isso implica esta registrada no ARCHITECTURE.md:
com alvo de +9% e stop de -20% a operacao precisa acertar ~69% das vezes
so para empatar, se todas terminassem no alvo ou no stop. Na pratica a
maior parte termina pela propria regra de saida, no meio do caminho.

## Rearme

Sem rearme, a carteira venderia no alvo e recompraria no dia seguinte com
o mesmo sinal -- viraria "a carteira de tendencia menos as taxas". Depois
de uma saida pelo alvo, a entrada so volta quando:

1. um dia fechado DEPOIS da saida mostrar o sinal enfraquecido (Reguas: 3
   votos ou menos; painel: soma abaixo de +2); e
2. um dia fechado depois desse mostrar o sinal de compra de novo.

Em palavras: vende no alvo, espera um recuo e so recompra quando a alta
retomar. Nao ha parametro novo: 3 e a zona neutra que as Reguas ja tem.
"""

from estrategia.indicadores import atr

ALVO_EM_ATR = 3.0
ATR_N = 14
MOTIVO_ALVO = "stop gain"
# A media de Wilder depende do ponto de partida; com 150 dias ele pesa
# (13/14)^136 < 0,001%. Menos que isso, sem alvo -- e sem entrada.
DIAS_MINIMOS = 150


def atr_pct(diarios: list[dict]) -> float | None:
    if len(diarios) < DIAS_MINIMOS:
        return None
    a = atr(diarios, ATR_N)
    if a is None:
        return None
    return a / diarios[-1]["fechamento"]


def nivel_de_alvo(preco_entrada: float, atr_pct_na_entrada: float) -> float:
    return preco_entrada * (1.0 + ALVO_EM_ATR * atr_pct_na_entrada)


def rearmada(dias_desde_saida: list[bool]) -> bool:
    """
    `dias_desde_saida`: para cada dia fechado depois da saida pelo alvo, em
    ordem, True se o sinal daquele dia era de compra. A conta esta rearmada
    se algum dia mostrou o sinal enfraquecido e o dia mais recente mostra
    compra de novo DEPOIS dele.
    """
    viu_recuo = False
    for compra in dias_desde_saida[:-1]:
        if not compra:
            viu_recuo = True
    return viu_recuo and bool(dias_desde_saida) and dias_desde_saida[-1]
