"""
Ensemble de tendencia diaria -- o nucleo de decisao do V.A.L a partir de
2026-09-22 (decidida em 2026-09-19).

Um unico lugar define a regra, e dois lugares a usam: o estudo de backtest
(`backtest/estudo_tendencia_diaria.py`) e o ciclo ao vivo
(`live/ciclo_carteira.py`, carteiras T1 e G1). E o principio que o projeto segue desde o
passo 5: a estrategia medida tem que ser a estrategia que opera. Duas
implementacoes viram dois sistemas, e o numero do backtest deixa de
prever o do ao vivo.

## A regra

Seis votos. Cada um pergunta a mesma coisa em um prazo diferente: o
fechamento diario de hoje esta acima da media dos ultimos L fechamentos
diarios? L em {10, 20, 30, 50, 70, 100} dias.

- fora da posicao: entra quando 4 ou mais dos 6 estao acima;
- dentro: sai quando 2 ou menos estao acima;
- com 3, mantem o que estiver fazendo (histerese -- e o que impede o
  rodizio que destruiu as regras de 1h).

Sem take-profit e sem stop por ATR: a saida e a propria reversao da
tendencia. Ha so um stop de catastrofe, largo, contra queda extrema entre
dois ciclos (ver STOP_CATASTROFE).

## Por que esta e nao outra

Veio da literatura (Zarattini, Pagani & Barbon 2025; Detzel et al. 2021;
Liu & Tsyvinski 2021) e nao dos nossos dados. Medido em 64 janelas: na
amostra 2024-26 bateu o comprar-e-segurar de mesma exposicao em +4,6 pts;
fora da amostra 2022-24 perdeu por -1,8 pt. O perfil que se repete nos
dois periodos e drawdown menor com ~3 operacoes por trimestre. A
expectativa honesta e essa -- menos risco, nao mais retorno.
"""

from backtest.engine import BUY, HOLD, NO_TRADE, SELL

LOOKBACKS = (10, 20, 30, 50, 70, 100)
ENTRA_COM = 4   # votos >= 4 -> entra
SAI_COM = 2     # votos <= 2 -> sai

# Stop de catastrofe: 20% abaixo da entrada. NAO faz parte do design
# testado no estudo (que nao tinha stop nenhum); existe porque o ciclo ao
# vivo so enxerga o mercado de tempos em tempos (o agendamento do GitHub
# tem buracos de ate 6h), e uma queda extrema no meio do buraco nao pode
# ficar sem piso. O efeito dele sobre o estudo foi medido a parte e e
# registrado no ARCHITECTURE.md.
STOP_CATASTROFE = 0.20


def votos(fechamentos_diarios: list[float]) -> int | None:
    """
    Quantos dos 6 prazos estao em alta no ULTIMO fechamento da lista.

    A lista tem que terminar num dia JA FECHADO -- quem chama e responsavel
    por descartar o dia em andamento. `None` quando o historico e curto
    demais para o prazo mais longo: sem dado, sem voto.
    """
    if len(fechamentos_diarios) < max(LOOKBACKS):
        return None
    ultimo = fechamentos_diarios[-1]
    return sum(ultimo > sum(fechamentos_diarios[-n:]) / n for n in LOOKBACKS)


def detalhar(fechamentos_diarios: list[float]) -> dict:
    """Votos e as medias de cada prazo, para registrar e mostrar."""
    v = votos(fechamentos_diarios)
    if v is None:
        return {"estrategia": "tendencia_diaria", "votos": None, "prazos": {}}
    ultimo = fechamentos_diarios[-1]
    prazos = {}
    for n in LOOKBACKS:
        media = sum(fechamentos_diarios[-n:]) / n
        prazos[str(n)] = {"media": media, "acima": ultimo > media}
    return {
        "estrategia": "tendencia_diaria",
        "votos": v,
        "de": len(LOOKBACKS),
        "entra_com": ENTRA_COM,
        "sai_com": SAI_COM,
        "fechamento_diario": ultimo,
        "prazos": prazos,
    }


def decidir(v: int | None, posicionado: bool, pode_entrar: bool = True) -> str:
    """
    A regra de entrada e saida, com histerese.

    `pode_entrar=False` segura a entrada mesmo com votos suficientes --
    ver `voto_vale_para_entrada`.
    """
    if v is None:
        return HOLD if posicionado else NO_TRADE
    if posicionado:
        return SELL if v <= SAI_COM else HOLD
    return BUY if v >= ENTRA_COM and pode_entrar else NO_TRADE


def nivel_de_stop(preco_entrada: float) -> float:
    return preco_entrada * (1.0 - STOP_CATASTROFE)


def voto_vale_para_entrada(fechamento_do_voto_ms: int, ultima_saida_ms: int | None) -> bool:
    """
    So se entra com um voto calculado DEPOIS da ultima saida.

    Sem isto, o stop de catastrofe seria inutil: ele vende no meio do dia,
    mas o voto que vale ate a meia-noite UTC ainda e o de ontem -- o mesmo
    que mandou comprar -- e a hora seguinte compraria de volta.

    Para a saida normal a regra nao muda nada: quem saiu com 2 votos ou
    menos so volta com 4 ou mais, o que exige um dia novo de qualquer
    jeito. Ela so morde depois de um stop, que e onde tem que morder.
    """
    return ultima_saida_ms is None or fechamento_do_voto_ms > ultima_saida_ms


def motivo(v: int | None, acao: str) -> str:
    """Frase curta, deterministica, do porque da decisao."""
    if v is None:
        return "historico diario insuficiente para os 6 prazos"
    base = f"{v} de {len(LOOKBACKS)} prazos em alta"
    if acao == BUY:
        return f"{base} (entra com {ENTRA_COM})"
    if acao == SELL:
        return f"{base} (sai com {SAI_COM} ou menos)"
    return base
