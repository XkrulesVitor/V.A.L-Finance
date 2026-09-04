"""
Um ciclo do forward test -- passo 8a.

E o equivalente ao vivo de `EstrategiaHibrida.__call__`, com uma
diferenca estrutural: la o estado vive em memoria porque a simulacao roda
de uma vez; aqui o processo morre a cada hora, entao o estado vem do
banco (`live/estado.py`) e volta pra ele.

## As tres etapas, na mesma ordem do backtest

A ordem nao e detalhe -- ela e a estrategia.

**Etapa 1 -- stop/take, TODO ciclo.** Antes da cadencia, antes de
qualquer chamada de API, sem tocar nas features. So compara preco contra
numero ja gravado. Uma posicao aberta e checada de hora em hora mesmo que
o cerebro so seja consultado a cada 6h; inverter isso significaria
descobrir o rompimento do stop com ate 6 horas de atraso.

**Etapa 2 -- e hora de consultar?** `cadencia.deve_consultar()`, a mesma
funcao pura que o backtest usa. A diferenca e de onde vem a ultima
consulta: no backtest, memoria; aqui, a tabela `decisions`.

**Etapa 3 -- o Risk Engine decide.** Ele pode contrariar a tese, e o
override fica registrado.

## Idempotencia vem antes de tudo

O candle e reivindicado ANTES de qualquer decisao. Se outra execucao ja
pegou este candle, o ciclo sai em silencio sem operar. Ver `live/estado.py`.

## Falha do cerebro nao desprotege a posicao

Se a consulta ao LLM falhar, o ciclo registra e segue. Isso e seguro
justamente porque a etapa 1 ja rodou: o stop foi conferido antes, com
dado local. Uma falha de rede na etapa 2 nunca deixa uma posicao sem
vigilancia -- ela so adia a proxima reavaliacao de tese.

E um simbolo com problema nao pode derrubar os outros: cada par roda no
seu proprio try.
"""

from datetime import datetime, timezone

from backtest.engine import BUY, HOLD, NO_TRADE, SELL
from brain.cadencia import INTERVALO_PADRAO_MS, deve_consultar
from brain.hybrid_strategy import parametros_para_horizonte
from features.candles import somente_fechados
from features.feature_engine import CANDLES_NECESSARIOS, calcular_features
from live.estado import (
    CandleJaProcessado,
    carregar_conta,
    concluir_decisao,
    reivindicar_candle,
    salvar_conta,
    ultima_consulta_ms,
)
from live.execucao import comprar, medir_deslize, vender
from risk.risk_engine import ParametrosDeRisco, avaliar_risco

CANDLES_A_PEDIR = CANDLES_NECESSARIOS + 1


class ResultadoDoCiclo:
    """O que aconteceu num ciclo, pra log e pra teste."""

    def __init__(self, par: str, acao: str, detalhe: str = "", preco: float | None = None):
        self.par = par
        self.acao = acao
        self.detalhe = detalhe
        self.preco = preco

    def __repr__(self) -> str:
        preco = f" @ {self.preco:,.2f}" if self.preco else ""
        detalhe = f" -- {self.detalhe}" if self.detalhe else ""
        return f"[{self.par}] {self.acao}{preco}{detalhe}"


def rodar_ciclo(
    supabase,
    binance,
    analista,
    par: str,
    *,
    intervalo_ms: int = INTERVALO_PADRAO_MS,
    parametros_base: ParametrosDeRisco | None = None,
    intervalo_candle: str = "1h",
) -> ResultadoDoCiclo:
    """
    Roda um ciclo para um par. Nao captura excecoes de infraestrutura de
    proposito -- quem chama decide se um par quebrado derruba os outros.
    """
    parametros_base = parametros_base or ParametrosDeRisco()

    # ---------- dado ----------
    candles = binance.buscar_candles(par, intervalo=intervalo_candle, limite=CANDLES_A_PEDIR)
    fechados = somente_fechados(candles)
    if not fechados:
        return ResultadoDoCiclo(par, "SEM_DADO", "nenhum candle fechado")

    ultimo_fechado = fechados[-1]
    # A abertura do candle EM CURSO e onde o backtest teria executado.
    # Guardada pra medir o deslize; None se a Binance so devolveu fechados.
    em_curso = candles[-1] if len(candles) > len(fechados) else None
    preco_de_referencia = em_curso["abertura"] if em_curso else None

    # ---------- idempotencia, antes de decidir qualquer coisa ----------
    try:
        id_decisao = reivindicar_candle(supabase, par, ultimo_fechado["fechamento_em"])
    except CandleJaProcessado:
        return ResultadoDoCiclo(par, "JA_PROCESSADO", "candle ja decidido")

    preco_atual = binance.buscar_preco(par)
    conta = carregar_conta(supabase, par)
    posicao = conta.como_estado_de_posicao()
    capital = conta.capital_total(preco_atual)

    registro = {
        "market_snapshot": {
            "preco_atual": preco_atual,
            "ultimo_candle": ultimo_fechado,
            "candles_em_andamento_descartados": len(candles) - len(fechados),
            "checado_em": datetime.now(timezone.utc).isoformat(),
            **medir_deslize(preco_atual, preco_de_referencia),
            # O estado da conta no momento da decisao vai DENTRO do
            # snapshot, e nao como coluna solta: `decisions` nao tem
            # colunas pra isso, e o snapshot e justamente "o mundo como
            # estava quando decidimos" -- a nossa posicao faz parte dele.
            "conta": {"caixa": conta.caixa, "quantidade": conta.quantidade},
        },
    }

    # ---------- ETAPA 1: stop/take, todo ciclo, sem features ----------
    if posicao.aberta:
        resultado = avaliar_risco(
            tese=HOLD,
            atr_14=None,
            preco_atual=preco_atual,
            posicao=posicao,
            capital_total=capital,
            parametros=parametros_base,
        )
        if resultado.acao_final == SELL:
            motivo = _motivo_da_saida(posicao, preco_atual)
            conta, preenchimento = vender(conta, preco_atual, motivo)
            salvar_conta(supabase, conta)
            concluir_decisao(supabase, id_decisao, {
                **registro,
                "risk_result": resultado.como_dicionario(),
                "order_result": preenchimento,
                "status": "executed",
                "outcome": {
                    "resultado": preenchimento["resultado"],
                    "resultado_pct": preenchimento["resultado_pct"],
                },
            })
            return ResultadoDoCiclo(par, SELL, motivo, preco_atual)

    # ---------- ETAPA 2: e hora de consultar o cerebro? ----------
    agora_ms = ultimo_fechado["fechamento_em"]
    if not deve_consultar(agora_ms, ultima_consulta_ms(supabase, par), intervalo_ms):
        acao = HOLD if posicao.aberta else NO_TRADE
        concluir_decisao(supabase, id_decisao, {
            **registro, "status": "no_trade" if acao == NO_TRADE else "hold",
        })
        return ResultadoDoCiclo(par, acao, "fora da cadencia", preco_atual)

    features = calcular_features(fechados)
    registro["features"] = features

    try:
        tese = analista.analisar(
            features=features,
            simbolo=par,
            posicao_aberta=posicao.aberta,
            preco_atual=preco_atual,
        )
    except Exception as erro:  # noqa: BLE001
        # Seguro porque a etapa 1 ja rodou: a posicao foi conferida contra
        # o stop antes desta chamada. Falhar aqui adia a proxima tese, nao
        # desprotege nada.
        concluir_decisao(supabase, id_decisao, {
            **registro, "status": "brain_error",
            "outcome": {"erro": str(erro)[:500]},
        })
        return ResultadoDoCiclo(par, "ERRO_CEREBRO", str(erro)[:120], preco_atual)

    registro["llm_output"] = tese.model_dump()

    # ---------- ETAPA 3: o Risk Engine decide ----------
    parametros = parametros_para_horizonte(tese.horizon, parametros_base)
    resultado = avaliar_risco(
        tese=tese,
        atr_14=features["atr_14"],
        preco_atual=preco_atual,
        posicao=posicao,
        capital_total=capital,
        parametros=parametros,
    )
    registro["risk_result"] = resultado.como_dicionario()

    if resultado.acao_final == BUY and resultado.aprovado and not posicao.aberta:
        conta, preenchimento = comprar(
            conta, preco_atual, resultado.stop_loss, resultado.take_profit
        )
        salvar_conta(supabase, conta)
        concluir_decisao(supabase, id_decisao, {
            **registro, "order_result": preenchimento, "status": "executed",
        })
        return ResultadoDoCiclo(par, BUY, f"stop {resultado.stop_loss:,.2f}", preco_atual)

    if resultado.acao_final == SELL and posicao.aberta:
        conta, preenchimento = vender(conta, preco_atual, "tese de saida")
        salvar_conta(supabase, conta)
        concluir_decisao(supabase, id_decisao, {
            **registro, "order_result": preenchimento, "status": "executed",
            "outcome": {
                "resultado": preenchimento["resultado"],
                "resultado_pct": preenchimento["resultado_pct"],
            },
        })
        return ResultadoDoCiclo(par, SELL, "tese de saida", preco_atual)

    concluir_decisao(supabase, id_decisao, {
        **registro,
        "status": "blocked" if not resultado.aprovado else "no_trade",
    })
    detalhe = resultado.motivo if not resultado.aprovado else resultado.acao_final
    return ResultadoDoCiclo(par, resultado.acao_final, detalhe, preco_atual)


def _motivo_da_saida(posicao, preco_atual: float) -> str:
    """Qual dos dois niveis foi rompido -- o par de saidas nao e o mesmo."""
    if posicao.stop_loss and preco_atual <= posicao.stop_loss:
        return "stop-loss rompido"
    if posicao.take_profit and preco_atual >= posicao.take_profit:
        return "alvo atingido"
    return "nivel rompido"
