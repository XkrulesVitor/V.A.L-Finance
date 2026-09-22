"""
Um ciclo do forward test com a regra de tendencia diaria -- a partir de
2026-09-22 (decidida em 2026-09-19).

Substitui `live/ciclo.py` (a estrategia hibrida LLM + Risk Engine) como
motor do forward test. O antigo continua no repositorio e acessivel por
`rodar.py --estrategia hibrida`, porque o historico gravado ate aqui foi
produzido por ele e precisa continuar reproduzivel.

## O que muda

- **Quem decide:** `estrategia/tendencia_diaria.py`, o mesmo modulo que o
  backtest usa. Sem LLM na decisao. Ele entra so depois, pra explicar.
- **Com que dado:** o voto e calculado sobre fechamentos DIARIOS ja
  fechados. O dia em andamento e descartado (`somente_fechados`), como o
  estudo fazia ao usar sempre o voto do dia anterior.
- **Saidas:** a reversao da tendencia (2 votos ou menos) e um stop de
  catastrofe 20% abaixo da entrada. Sem alvo: cortar o ganho no alvo e o
  oposto do que uma regra de tendencia precisa.

## O que continua igual

- Ciclo de hora em hora, reivindicando o ultimo candle de 1h fechado -- a
  mesma chave de idempotencia de antes. A regra so muda de ideia uma vez
  por dia, mas o stop precisa ser conferido toda hora.
- Varredura de todos os fechamentos de 1h nao vistos antes de decidir,
  pelo mesmo motivo de `live/ciclo.py`: o agendamento do GitHub pula horas.
- Preenchimento simulado com a aritmetica do motor (`live/execucao.py`).
- As contas continuam de onde estavam. Nada foi apagado; a data da troca
  fica no ARCHITECTURE.md.
"""

from dataclasses import replace
from datetime import datetime, timezone

from backtest.engine import BUY, HOLD, NO_TRADE, SELL
from estrategia import tendencia_diaria as regra
from features.candles import somente_fechados
from live.ciclo import ResultadoDoCiclo
from live.estado import (
    CandleJaProcessado,
    carregar_conta,
    concluir_decisao,
    reivindicar_candle,
    salvar_conta,
    ultima_saida_ms,
    ultimo_candle_processado,
)
from live.execucao import comprar, medir_deslize, vender

# 72h de candles de 1h: cobre com folga os maiores buracos medidos no
# agendamento (5,7h). Um buraco maior que isso e falha de infraestrutura
# e aparece no workflow em vermelho muito antes.
HORAS_A_PEDIR = 72
# O maior prazo e 100 dias; a folga cobre o dia em andamento (descartado)
# e qualquer dia que a Binance devolva a menos.
DIAS_A_PEDIR = max(regra.LOOKBACKS) + 10

MOTIVO_STOP = "stop de catastrofe"
MOTIVO_TENDENCIA = "tendencia virou"

HORA_MS = 3_600_000


def rodar_ciclo_tendencia(supabase, binance, explicador, par: str) -> ResultadoDoCiclo:
    """
    Roda um ciclo para um par. Como `rodar_ciclo`, nao captura excecoes de
    infraestrutura -- quem chama decide se um par quebrado derruba os outros.
    """
    # ---------- dado ----------
    horarios = binance.buscar_candles(par, intervalo="1h", limite=HORAS_A_PEDIR)
    fechados_h = somente_fechados(horarios)
    diarios = somente_fechados(binance.buscar_candles(par, intervalo="1d", limite=DIAS_A_PEDIR))
    if not fechados_h or not diarios:
        return ResultadoDoCiclo(par, "SEM_DADO", "nenhum candle fechado")

    ultimo_h = fechados_h[-1]
    em_curso = horarios[-1] if len(horarios) > len(fechados_h) else None
    # Lidos ANTES de reivindicar. O ultimo processado, pelo mesmo motivo de
    # `live/ciclo.py`. O preco, porque e so leitura de mercado: se falhar,
    # o par falha sem deixar reivindicacao orfa.
    processado_ate = ultimo_candle_processado(supabase, par)
    preco_atual = binance.buscar_preco(par)

    # ---------- idempotencia, antes de decidir qualquer coisa ----------
    try:
        id_decisao = reivindicar_candle(supabase, par, ultimo_h["fechamento_em"])
    except CandleJaProcessado:
        return ResultadoDoCiclo(par, "JA_PROCESSADO", "candle ja decidido")

    conta = carregar_conta(supabase, par)
    dia_do_voto = diarios[-1]
    leitura = regra.detalhar([c["fechamento"] for c in diarios])
    leitura["dia"] = datetime.fromtimestamp(dia_do_voto["abertura_em"] / 1000, timezone.utc).date().isoformat()
    votos = leitura["votos"]

    registro = {
        "market_snapshot": {
            "preco_atual": preco_atual,
            "ultimo_candle": ultimo_h,
            "checado_em": datetime.now(timezone.utc).isoformat(),
            **medir_deslize(preco_atual, em_curso["abertura"] if em_curso else None),
            "conta": {"caixa": conta.caixa, "quantidade": conta.quantidade},
        },
        # O que a regra viu: os 6 prazos, as medias e o total de votos. E o
        # equivalente do vetor de indicadores do cerebro antigo -- o
        # suficiente pra refazer a decisao a mao.
        "features": leitura,
    }

    # ---------- niveis herdados de outra estrategia ----------
    # Uma posicao aberta pela hibrida chega com stop por ATR (apertado) e
    # alvo. Conferida como esta, uma queda de 2% sairia registrada como
    # "stop de catastrofe", travaria a reentrada e seria explicada ao
    # leitor como a regra dos 20%. Os niveis passam a ser os da regra.
    if conta.posicionada and conta.preco_entrada:
        nivel = regra.nivel_de_stop(conta.preco_entrada)
        fora_da_regra = conta.take_profit is not None or conta.stop_loss is None             or abs(conta.stop_loss - nivel) > 1e-9 * nivel
        if fora_da_regra:
            registro["market_snapshot"]["niveis_herdados"] = {
                "stop_loss": conta.stop_loss, "take_profit": conta.take_profit,
            }
            conta = replace(conta, stop_loss=nivel, take_profit=None)
            salvar_conta(supabase, conta)

    # ---------- ETAPA 1: stop de catastrofe em todo fechamento nao visto ----------
    # So fechamentos de 1h, e nao o preco do instante: e a mecanica medida em
    # `backtest/efeito_stop_catastrofe.py`. Conferir tambem o ticker criaria
    # vendas que o replay offline sobre os mesmos candles nunca faria -- e o
    # criterio 1 de leitura (fidelidade) as marcaria como divergencia.
    if conta.posicionada and conta.stop_loss:
        gatilho = _primeiro_no_stop(fechados_h, processado_ate, conta.stop_loss)
        if gatilho is not None:
            preco, quando = gatilho
            # O estudo vende na abertura do candle seguinte ao fechamento
            # que furou o stop: o fechamento_em do gatilho + 1 ms.
            return _executar_venda(supabase, explicador, par, conta, preco, quando,
                                   MOTIVO_STOP, id_decisao, registro, votos,
                                   referencia=_referencia(horarios, quando + 1, preco))

    # ---------- ETAPA 2: a regra ----------
    ultimo_stop = ultima_saida_ms(supabase, par, motivo=MOTIVO_STOP)
    pode_entrar = regra.voto_vale_para_entrada(dia_do_voto["fechamento_em"], ultimo_stop)
    # Vai junto da leitura (que e o `features` gravado) para a pagina saber
    # que a regra esta travada, e nao mostrar "entra com 4" com 5 votos.
    leitura["pode_entrar"] = pode_entrar
    acao = regra.decidir(votos, conta.posicionada, pode_entrar=pode_entrar)
    motivo = regra.motivo(votos, acao)
    if acao == NO_TRADE and not pode_entrar and votos is not None and votos >= regra.ENTRA_COM:
        motivo += " -- aguardando um dia fechar depois do stop"
    registro["risk_result"] = {
        "estrategia": "tendencia_diaria", "acao_final": acao, "motivo": motivo, "pode_entrar": pode_entrar,
    }

    if acao == BUY:
        stop = regra.nivel_de_stop(preco_atual)
        conta, preenchimento = comprar(conta, preco_atual, stop, None)
        preenchimento["motivo"] = motivo
        preenchimento["referencia_backtest"] = _referencia_da_regra(horarios, dia_do_voto, preco_atual)
        salvar_conta(supabase, conta)
        concluir_decisao(supabase, id_decisao, {**registro, "order_result": preenchimento, "status": "executed"})
        _anexar_explicacao(supabase, explicador, id_decisao, par, preenchimento, votos, leitura)
        return ResultadoDoCiclo(par, BUY, f"{motivo}; stop {stop:,.2f}", preco_atual)

    if acao == SELL:
        return _executar_venda(supabase, explicador, par, conta, preco_atual, ultimo_h["fechamento_em"],
                               MOTIVO_TENDENCIA, id_decisao, registro, votos, detalhe=motivo,
                               referencia=_referencia_da_regra(horarios, dia_do_voto, preco_atual))

    concluir_decisao(supabase, id_decisao, {**registro, "status": "hold" if acao == HOLD else "no_trade"})
    return ResultadoDoCiclo(par, acao, motivo, preco_atual)


def _referencia_da_regra(horarios, dia_do_voto, preco):
    """
    Onde o motor de backtest executaria esta decisao da regra.

    O estudo (classe `Binaria`) so ve o voto do dia D no candle de 1h que
    abre as 00:00 de D+1, e o motor executa na abertura do candle seguinte:
    01:00 UTC. O ciclo ao vivo age no primeiro ciclo depois das 00:00 --
    e, com o agendamento pulando horas, as vezes bem depois.
    """
    return _referencia(horarios, dia_do_voto["fechamento_em"] + 1 + HORA_MS, preco)


def _referencia(horarios, abertura_em, preco):
    """
    A distancia entre o preenchimento ao vivo e o do backtest.

    `deslize_pct` do `market_snapshot` compara com a abertura da hora em
    curso, o que so fazia sentido para a hibrida. Esta e a medida certa para
    a regra diaria. Quando o candle de referencia ainda nao abriu (o ciclo
    agiu antes das 01:00), o preco fica None e o instante fica gravado para
    a conferencia offline completar.
    """
    candle = next((c for c in horarios if c["abertura_em"] == abertura_em), None)
    ref = candle["abertura"] if candle else None
    return {
        "em": abertura_em,
        "preco": ref,
        "deslize_pct": (preco / ref - 1.0) * 100.0 if ref else None,
    }


def _primeiro_no_stop(fechados, processado_ate, stop):
    """
    (preco, fechamento_em) do primeiro fechamento de 1h nao visto que
    furou o stop. Sai no preco daquele fechamento, e nao no de agora --
    e o que uma ordem stop descansando na corretora teria feito.
    """
    for c in fechados:
        if processado_ate is not None and c["fechamento_em"] <= processado_ate:
            continue
        if c["fechamento"] <= stop:
            return c["fechamento"], c["fechamento_em"]
    return None


def _executar_venda(supabase, explicador, par, conta, preco, gatilho_em, motivo, id_decisao,
                    registro, votos, detalhe=None, referencia=None):
    conta, preenchimento = vender(conta, preco, motivo)
    preenchimento["referencia_backtest"] = referencia
    # `gatilho_em` decide quando a regra pode voltar a entrar
    # (`voto_vale_para_entrada`). Pode ser anterior ao candle reivindicado,
    # quando a varredura acha o stop num fechamento antigo.
    preenchimento["gatilho_em"] = gatilho_em
    salvar_conta(supabase, conta)
    concluir_decisao(supabase, id_decisao, {
        **registro,
        "risk_result": {
            **registro.get("risk_result", {}),
            "estrategia": "tendencia_diaria", "acao_final": SELL, "motivo": detalhe or motivo,
        },
        "order_result": preenchimento,
        "status": "executed",
        "outcome": {"resultado": preenchimento["resultado"], "resultado_pct": preenchimento["resultado_pct"]},
    })
    _anexar_explicacao(supabase, explicador, id_decisao, par, preenchimento, votos, registro["features"])
    return ResultadoDoCiclo(par, SELL, detalhe or motivo, preco)


def _anexar_explicacao(supabase, explicador, id_decisao, par, preenchimento, votos, leitura):
    """Depois de tudo gravado: pede a frase e anexa. Falhar aqui nao desfaz nada."""
    if explicador is None:
        return
    fatos = {
        "ativo": par.replace("USDT", ""),
        "operacao": "compra" if preenchimento["lado"] == "BUY" else "venda",
        "preco": round(preenchimento["preco"], 4),
        "motivo": preenchimento.get("motivo"),
        "regra": (
            f"compra quando o preco fecha o dia acima da media em pelo menos {regra.ENTRA_COM} de "
            f"{len(regra.LOOKBACKS)} prazos ({', '.join(str(n) for n in regra.LOOKBACKS)} dias); "
            f"vende quando isso cai para {regra.SAI_COM} ou menos; vende tambem se o preco cair "
            f"{regra.STOP_CATASTROFE:.0%} abaixo da entrada"
        ),
        "prazos_em_alta": votos,
        "prazos": {f"{n} dias": ("acima" if p["acima"] else "abaixo")
                   for n, p in (leitura.get("prazos") or {}).items()},
    }
    if preenchimento.get("resultado_pct") is not None:
        fatos["resultado_da_operacao_pct"] = round(preenchimento["resultado_pct"], 2)
    texto, erro = explicador.explicar(fatos)
    extra = {"explicacao": texto}
    if erro:
        extra["explicacao_erro"] = erro
    try:
        concluir_decisao(supabase, id_decisao, {"order_result": {**preenchimento, **extra}})
    except Exception:  # noqa: BLE001 -- a operacao ja esta gravada; perder a frase e aceitavel
        pass
