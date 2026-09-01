"""
Risk Engine -- passo 6 do roteiro (secao 10 do ARCHITECTURE.md).

Transforma uma tese do cerebro em decisao operavel: calcula stop-loss,
take-profit e tamanho de posicao a partir do ATR, e aprova ou bloqueia.
E, antes de tudo isso, faz a coisa mais importante que esta camada faz.

## O Risk Engine nao e um validador passivo

Ele tem autoridade pra AGIR CONTRA o cerebro. Se um stop-loss ou
take-profit ja registrado foi rompido, ele forca SELL -- mesmo que a
tese daquele ciclo diga HOLD, mesmo que diga BUY. Essa checagem roda
primeiro, todo ciclo, antes de qualquer outra logica, e nao consulta a
opiniao do LLM pra decidir se vale a pena.

Isso nao e zelo abstrato: e correcao de um comportamento medido. Na
validacao do passo 5 (secao 11), num cenario de queda de 19,95% com
posicao aberta, o modelo escolheu HOLD justificando "para evitar
realizar prejuizo em um momento de possivel repique tecnico". Em 12
amostras, incluindo duas quedas fortes, SELL nao apareceu nenhuma vez.
Isso e aversao a perda -- um vies humano bem documentado, reproduzido
pelo modelo. Uma camada de risco que so pudesse bloquear ordens novas,
sem poder fechar posicao existente, deixaria esse vies passar inteiro
pra carteira: a posicao ficaria aberta caindo enquanto o cerebro
repetisse "e prudente manter".

Por isso a regra 1 existe, por isso ela e a primeira, e por isso o
resultado carrega `override_do_llm`: o momento em que a maquina
discordou do modelo tem que ficar visivel no `decision_id`, nao
dissolvido numa acao final sem historia.

## ATENCAO -- os parametros padrao bloqueiam quase toda entrada em 1h

Medido sobre um ano de BTCUSDT (50 amostras semanais, capital 10.000):
com stop a 2x ATR, risco de 1% e teto de exposicao de 50%, o Risk
Engine aprova **2 de 50** entradas.

Nao e bug: e aritmetica. O ATR-14 em candle de 1h e mediana de 0,61% do
preco, entao um stop a 2x ATR fica a ~1,2% de distancia. Arriscar 1% do
capital com stop de 1,2% exige nocional de ~84% do capital -- que estoura
qualquer teto de exposicao sensato. Em spot, sem alavancagem, o teto
passa a ser a restricao que manda, e a regra de risco vira decoracao.

Duas correcoes de uma linha, medidas, que resolvem (as duas levam a
50/50 aprovados e exposicao mediana de 21% do capital):

    ParametrosDeRisco(risco_por_operacao=0.0025)   # 0,25% por operacao
    ParametrosDeRisco(multiplicador_stop=8.0)      # stop mais largo

Os padroes ficam como estao de proposito -- 2x/3x/1% sao os valores
especificados no passo 6, e mudar em silencio esconderia a tensao em vez
de resolve-la. A calibracao e decisao do passo 7, tomada comparando
backtest, e nao um numero a chutar aqui. Mas quem rodar a hibrida com os
padroes vai ver quase nenhuma operacao, e precisa saber que isso e a
configuracao falando, nao o cerebro.

## Esta funcao e pura

`avaliar_risco()` nao busca nada do Supabase e nao olha o relogio.
Recebe o estado da posicao como parametro. Quem le do banco e a casca
fina em `risk/portfolio_repo.py`, que pode falhar sem derrubar o
resto -- e cuja falha, importante, NAO pode ser interpretada como
"nao ha posicao" (o motivo esta la).

## O que ainda nao esta aqui

A estrategia hibrida (passo 7). Esta peca nao e uma estrategia: nao
recebe `ContextoDeDecisao` nem devolve uma das quatro decisoes soltas.
Ela e chamada POR DENTRO da hibrida, depois que o cerebro opinou.
"""

import math
import os
from dataclasses import dataclass

BUY, SELL, HOLD, NO_TRADE = "BUY", "SELL", "HOLD", "NO_TRADE"


@dataclass(frozen=True)
class EstadoDaPosicao:
    """
    A posicao atual num ativo. Tudo zero/None quando nao ha posicao.

    `stop_loss` e `take_profit` sao os niveis JA REGISTRADOS quando a
    posicao foi aberta -- nao sao recalculados a cada ciclo. E isso que
    da sentido a regra 1: o nivel foi fixado num momento de calma, e a
    checagem contra ele acontece depois, quando o preco ja se mexeu e a
    tentacao de "esperar mais um pouco" apareceu.
    """

    quantidade: float = 0.0
    preco_entrada: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None

    @property
    def aberta(self) -> bool:
        return self.quantidade > 0


@dataclass(frozen=True)
class ParametrosDeRisco:
    """
    Os numeros que governam o risco. Todos configuraveis, nenhum fixo no
    codigo -- sao hipoteses a calibrar no passo 7, nao verdades.
    """

    multiplicador_stop: float = 2.0
    multiplicador_take: float = 3.0
    risco_por_operacao: float = 0.01  # 1% do capital total por operacao
    # Teto de quanto do capital pode ficar exposto num unico ativo.
    # 50% permite dois ativos simultaneos (hoje BTCUSDT e ETHUSDT) sem
    # que um sozinho leve a carteira inteira.
    exposicao_maxima_pct: float = 0.50

    @classmethod
    def do_ambiente(cls) -> "ParametrosDeRisco":
        """Para o caminho ao vivo, onde ajustar sem editar codigo importa."""
        return cls(
            multiplicador_stop=float(os.environ.get("RISCO_MULT_STOP", 2.0)),
            multiplicador_take=float(os.environ.get("RISCO_MULT_TAKE", 3.0)),
            risco_por_operacao=float(os.environ.get("RISCO_POR_OPERACAO", 0.01)),
            exposicao_maxima_pct=float(os.environ.get("RISCO_EXPOSICAO_MAXIMA", 0.50)),
        )


@dataclass
class ResultadoDeRisco:
    aprovado: bool
    acao_final: str
    motivo: str
    stop_loss: float
    take_profit: float
    tamanho_posicao: float
    override_do_llm: bool
    direcao_do_llm: str

    def como_dicionario(self) -> dict:
        """
        O que vai pro campo `risk_result` (jsonb) de `decisions`.

        `direcao_do_llm` viaja junto de proposito, mesmo a tese completa
        ja estando em `llm_output` na mesma linha. Sem ele, ler
        `risk_result` isolado -- numa query, num grafico, num export --
        mostraria so a acao final, e o override ficaria invisivel
        exatamente onde ele mais precisa ser visto.
        """
        return {
            "aprovado": self.aprovado,
            "acao_final": self.acao_final,
            "motivo": self.motivo,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "tamanho_posicao": self.tamanho_posicao,
            "override_do_llm": self.override_do_llm,
            "direcao_do_llm": self.direcao_do_llm,
        }


def avaliar_risco(
    tese,
    atr_14: float | None,
    preco_atual: float,
    posicao: EstadoDaPosicao,
    capital_total: float,
    parametros: ParametrosDeRisco | None = None,
) -> ResultadoDeRisco:
    """
    Avalia uma tese e devolve a decisao final da camada de risco.

    `tese` aceita tanto um `TeseDeOperacao` quanto um dicionario -- o
    Risk Engine nao importa nada de `brain/` de proposito, pra nao
    arrastar o SDK do Gemini pra dentro de uma peca que e pura
    aritmetica e precisa ser testavel sem rede.
    """
    parametros = parametros or ParametrosDeRisco()
    direcao = _direcao_da_tese(tese)

    # ---------- REGRA 1: stop/take rompido manda em tudo ----------
    # Primeira coisa avaliada, todo ciclo, sem consultar o que o LLM
    # disse. Se esta checagem vier depois de qualquer outra logica, ela
    # deixa de ser uma protecao e vira uma sugestao.
    if posicao.aberta:
        rompimento = _nivel_rompido(posicao, preco_atual)
        if rompimento:
            nivel, valor = rompimento
            return ResultadoDeRisco(
                aprovado=True,
                acao_final=SELL,
                motivo=(
                    f"{nivel} rompido: preco {preco_atual:g} contra nivel {valor:g}. "
                    f"Saida forcada pela camada de risco"
                    + (f", sobrepondo a tese do LLM ({direcao})." if direcao != SELL else ".")
                ),
                stop_loss=posicao.stop_loss or 0.0,
                take_profit=posicao.take_profit or 0.0,
                tamanho_posicao=posicao.quantidade,
                override_do_llm=direcao != SELL,
                direcao_do_llm=direcao,
            )

    # ---------- REGRA 2: abrir posicao ----------
    if not posicao.aberta and direcao == BUY:
        return _avaliar_abertura(direcao, atr_14, preco_atual, capital_total, parametros)

    # ---------- REGRA 3: fechar posicao ----------
    if posicao.aberta and direcao == SELL:
        # Fechar e sempre menos arriscado que abrir: reduz exposicao, nao
        # aumenta. Nao ha o que calcular nem o que bloquear.
        return _resultado_simples(
            aprovado=True, acao=SELL, direcao=direcao, posicao=posicao,
            motivo="Fechamento de posicao aprovado -- reduzir exposicao nao exige checagem de risco.",
            tamanho=posicao.quantidade,
        )

    # ---------- REGRA 4: manter posicao ----------
    if posicao.aberta and direcao == HOLD:
        return _resultado_simples(
            aprovado=True, acao=HOLD, direcao=direcao, posicao=posicao,
            motivo="Posicao mantida; nenhum nivel de risco rompido.",
        )

    # ---------- REGRA 5: seguir de fora ----------
    if not posicao.aberta and direcao == NO_TRADE:
        return _resultado_simples(
            aprovado=True, acao=NO_TRADE, direcao=direcao, posicao=posicao,
            motivo="Sem posicao e sem tese de entrada; nenhuma ordem.",
        )

    # ---------- Combinacoes que o vocabulario permite mas a carteira nao ----------
    return _reconciliar_com_a_carteira(direcao, posicao)


def _avaliar_abertura(direcao, atr_14, preco_atual, capital_total, parametros) -> ResultadoDeRisco:
    """Calcula stop, take e tamanho; aprova se couber no limite de exposicao."""
    if atr_14 is None or not math.isfinite(atr_14) or atr_14 <= 0:
        # Sem ATR nao ha stop calculavel, e sem stop calculavel nao ha
        # operacao -- o principio 2 diz que o numero de risco vem da
        # volatilidade real, nao de um palpite. Na falta dela, nao se opera.
        return _bloqueio(direcao, "ATR indisponivel ou invalido; sem ele nao ha stop-loss calculavel.")
    if preco_atual <= 0 or not math.isfinite(preco_atual):
        return _bloqueio(direcao, f"Preco atual invalido ({preco_atual}).")
    if capital_total <= 0:
        return _bloqueio(direcao, f"Capital total invalido ({capital_total}).")

    distancia_do_stop = parametros.multiplicador_stop * atr_14
    stop_loss = preco_atual - distancia_do_stop
    take_profit = preco_atual + parametros.multiplicador_take * atr_14

    if stop_loss <= 0:
        return _bloqueio(
            direcao,
            f"Stop calculado em {stop_loss:g} (<= 0): a volatilidade e grande demais "
            f"em relacao ao preco para esta configuracao.",
        )

    # Tamanho por risco: quanto se pode perder dividido pela distancia ate
    # o stop. E o que faz "1% de risco" significar 1% de verdade, e nao
    # 1% do que se imagina.
    risco_em_dinheiro = capital_total * parametros.risco_por_operacao
    tamanho = risco_em_dinheiro / distancia_do_stop

    exposicao = tamanho * preco_atual
    exposicao_maxima = capital_total * parametros.exposicao_maxima_pct
    if exposicao > exposicao_maxima:
        return _bloqueio(
            direcao,
            f"Exposicao exigida ({exposicao:,.2f}) passa do teto por ativo "
            f"({exposicao_maxima:,.2f} = {parametros.exposicao_maxima_pct:.0%} de "
            f"{capital_total:,.2f}). Stop a {distancia_do_stop:g} de distancia e "
            f"apertado demais para arriscar {parametros.risco_por_operacao:.1%} sem "
            f"concentrar a carteira.",
            stop_loss=stop_loss,
            take_profit=take_profit,
            tamanho=tamanho,
        )

    return ResultadoDeRisco(
        aprovado=True,
        acao_final=BUY,
        motivo=(
            f"Entrada aprovada. Stop {parametros.multiplicador_stop:g}x ATR abaixo "
            f"({stop_loss:,.2f}), alvo {parametros.multiplicador_take:g}x ATR acima "
            f"({take_profit:,.2f}); risco de {parametros.risco_por_operacao:.1%} do capital."
        ),
        stop_loss=stop_loss,
        take_profit=take_profit,
        tamanho_posicao=tamanho,
        override_do_llm=False,
        direcao_do_llm=direcao,
    )


def _reconciliar_com_a_carteira(direcao: str, posicao: EstadoDaPosicao) -> ResultadoDeRisco:
    """
    As combinacoes que sobram: direcao valida no vocabulario, mas
    impossivel ou sem sentido dado o estado da carteira.

    Nenhuma delas e erro do cerebro -- ele responde com a informacao que
    tem. Sao reconciliadas aqui, e o `override_do_llm` fica ligado porque
    a acao final difere do que ele pediu. Um `SELL` sem posicao viraria
    venda a descoberto, que o V1 nao faz (principio 5).
    """
    if posicao.aberta and direcao == BUY:
        return _resultado_simples(
            aprovado=False, acao=HOLD, direcao=direcao, posicao=posicao,
            motivo="LLM pediu BUY, mas ja ha posicao aberta; o V1 nao aumenta posicao. Mantida.",
        )
    if posicao.aberta and direcao == NO_TRADE:
        return _resultado_simples(
            aprovado=True, acao=HOLD, direcao=direcao, posicao=posicao,
            motivo="LLM devolveu NO_TRADE com posicao aberta; sem nivel rompido, a posicao e mantida.",
        )
    if not posicao.aberta and direcao == SELL:
        return _resultado_simples(
            aprovado=False, acao=NO_TRADE, direcao=direcao, posicao=posicao,
            motivo="LLM pediu SELL sem posicao aberta; V1 e spot only, sem venda a descoberto.",
        )
    # not aberta and direcao == HOLD
    return _resultado_simples(
        aprovado=True, acao=NO_TRADE, direcao=direcao, posicao=posicao,
        motivo="LLM devolveu HOLD sem posicao aberta; nao ha o que manter.",
    )


def _resultado_simples(*, aprovado, acao, direcao, posicao, motivo, tamanho=0.0) -> ResultadoDeRisco:
    return ResultadoDeRisco(
        aprovado=aprovado,
        acao_final=acao,
        motivo=motivo,
        stop_loss=posicao.stop_loss or 0.0,
        take_profit=posicao.take_profit or 0.0,
        tamanho_posicao=tamanho,
        override_do_llm=acao != direcao,
        direcao_do_llm=direcao,
    )


def _bloqueio(direcao, motivo, stop_loss=0.0, take_profit=0.0, tamanho=0.0) -> ResultadoDeRisco:
    return ResultadoDeRisco(
        aprovado=False,
        acao_final=NO_TRADE,
        motivo=motivo,
        stop_loss=stop_loss,
        take_profit=take_profit,
        tamanho_posicao=tamanho,
        override_do_llm=direcao != NO_TRADE,
        direcao_do_llm=direcao,
    )


def _nivel_rompido(posicao: EstadoDaPosicao, preco_atual: float):
    """
    Algum nivel registrado foi rompido? Devolve (nome, valor) ou None.

    A posicao e comprada (V1 e spot only, principio 5): o stop fica
    ABAIXO e e rompido quando o preco cai ate ele; o alvo fica ACIMA e e
    atingido quando o preco sobe ate ele. A comparacao e `<=` e `>=`,
    nao `<` e `>`: preco exatamente no nivel e o nivel atingido, e
    tratar isso como "ainda nao" seria perder o gatilho por um centavo.

    Nivel `None` -- posicao aberta antes de existirem os campos, ou dado
    faltando -- simplesmente nao dispara. Nao ha nivel para romper.
    """
    if posicao.stop_loss is not None and preco_atual <= posicao.stop_loss:
        return ("Stop-loss", posicao.stop_loss)
    if posicao.take_profit is not None and preco_atual >= posicao.take_profit:
        return ("Take-profit", posicao.take_profit)
    return None


def _direcao_da_tese(tese) -> str:
    """Aceita `TeseDeOperacao`, dicionario, ou a string da direcao."""
    if isinstance(tese, str):
        direcao = tese
    elif isinstance(tese, dict):
        direcao = tese.get("direction")
    else:
        direcao = getattr(tese, "direction", None)

    if direcao not in (BUY, SELL, HOLD, NO_TRADE):
        raise ValueError(
            f"direcao {direcao!r} fora do vocabulario oficial "
            f"({BUY}, {SELL}, {HOLD}, {NO_TRADE})"
        )
    return direcao
