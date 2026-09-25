"""
Um ciclo de uma carteira x par -- o mesmo codigo para as seis carteiras.

Substitui `live/ciclo_tendencia.py` (que era so a T1) e generaliza o que
ele fazia, sem mudar o comportamento da T1:

1. **Reivindica** o ultimo candle de 1h fechado para (carteira, par): a
   idempotencia de sempre, agora por carteira.
2. **Varre** os fechamentos de 1h ainda nao vistos contra o stop e, nas
   carteiras de stop gain, contra o alvo. O primeiro que cruzar decide, e a
   venda sai no preco daquele fechamento (`preco`), com o ticker do instante
   gravado ao lado (`preco_executavel`). Nenhuma IA e chamada antes disto.
3. **Regra diaria** sobre o ultimo dia fechado:
   - T1, T2, G1 e G2 decidem logo em seguida (`fase_sem_ia`);
   - T3 e G3 esperam o veredito do painel e decidem em `fase_painel`,
     sobre a MESMA linha reivindicada.

Protecoes comuns (a mesma funcao para todas):
- **trava de reentrada:** so entra com o sinal de um dia que fechou depois
  da ultima saida (`ultima_saida_em` da propria conta, gravado no mesmo
  upsert da venda);
- **guarda de saida:** a saida pela regra so olha dias que fecharam depois
  do preenchimento da entrada (`entrada_em`) -- sem ela, uma carteira que
  comprou hoje com o sinal de ontem poderia vender hoje com o mesmo sinal;
- **rearme (G1 e G3):** depois de uma saida pelo alvo, a conta fica
  desarmada ate o sinal enfraquecer e voltar (`estrategia.alvo.rearmada`).

A frase do LLM nao roda aqui: a operacao e gravada com
`explicacao_pendente` e a fase de explicacoes, no fim do job, completa.
"""

from dataclasses import dataclass, replace
from datetime import datetime, timezone

from backtest.engine import BUY, HOLD, NO_TRADE, SELL
from estrategia import alvo
from estrategia import tendencia_diaria as reguas
from live import regras
from live.carteiras import Carteira
from live.estado import (
    CandleJaProcessado,
    ContaSimulada,
    carregar_conta,
    concluir_decisao,
    reivindicar_candle,
    salvar_conta,
    ultimo_candle_processado,
)
from live.execucao import comprar, medir_deslize, vender
from live.mercado import Mercado

HORA_MS = 3_600_000
DIA_MS = 86_400_000

MOTIVO_TENDENCIA = "tendencia virou"
MOTIVO_REPIQUE = "repique"
MOTIVO_ALVO = alvo.MOTIVO_ALVO   # "stop gain"


@dataclass
class Resultado:
    carteira: str
    par: str
    acao: str
    detalhe: str = ""
    preco: float | None = None
    # T3/G3: a linha fica reivindicada ate a fase do painel decidir.
    pendente: dict | None = None

    def __repr__(self) -> str:
        preco = f" @ {self.preco:,.2f}" if self.preco else ""
        detalhe = f" -- {self.detalhe}" if self.detalhe else ""
        return f"[{self.carteira} {self.par}] {self.acao}{preco}{detalhe}"


def _agora_ms() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def fase_sem_ia(supabase, carteira: Carteira, m: Mercado, agora_ms: int | None = None) -> Resultado:
    """Reivindica, varre stop/alvo e, nas carteiras de regra, decide."""
    agora_ms = agora_ms or _agora_ms()
    if not m.completo:
        return Resultado(carteira.id, m.par, "SEM_DADO", "nenhum candle fechado")

    # Lido ANTES de reivindicar: a reivindicacao insere o candle atual.
    processado_ate = ultimo_candle_processado(supabase, carteira.id, m.par)
    try:
        id_decisao = reivindicar_candle(supabase, carteira.id, m.par, m.ultimo_h["fechamento_em"])
    except CandleJaProcessado:
        return Resultado(carteira.id, m.par, "JA_PROCESSADO", "candle ja decidido")

    conta = carregar_conta(supabase, carteira.id, m.par)

    sinal = None if carteira.usa_painel else regras.ler(carteira.regra, m.diarios)
    registro = {
        "regra_versao": carteira.regra_versao,
        "market_snapshot": {
            "preco_atual": m.preco,
            "ultimo_candle": m.ultimo_h,
            "checado_em": datetime.now(timezone.utc).isoformat(),
            **medir_deslize(m.preco, m.em_curso["abertura"] if m.em_curso else None),
            "conta": {"caixa": conta.caixa, "quantidade": conta.quantidade},
        },
        # A leitura vem primeiro: ela traz o proprio `estrategia` (as Reguas
        # dizem "tendencia_diaria"), e o da carteira tem de prevalecer -- sem
        # isso a G1 era gravada como se fosse a T1.
        "features": {**(sinal.leitura if sinal else {}), "estrategia": _estrategia(carteira),
                     "dia": _data(m.dia["abertura_em"])},
    }

    # ---------- niveis herdados (so T1: posicao aberta pela hibrida) ----------
    if carteira.id == "T1" and conta.posicionada and conta.preco_entrada:
        nivel = reguas.nivel_de_stop(conta.preco_entrada)
        if conta.take_profit is not None or conta.stop_loss is None \
                or abs(conta.stop_loss - nivel) > 1e-9 * nivel:
            registro["market_snapshot"]["niveis_herdados"] = {
                "stop_loss": conta.stop_loss, "take_profit": conta.take_profit}
            conta = replace(conta, stop_loss=nivel, take_profit=None)
            salvar_conta(supabase, conta)

    # ---------- varredura de stop e alvo ----------
    if conta.posicionada and conta.stop_loss:
        alvo_nivel = conta.take_profit if carteira.com_alvo else None
        gatilho = primeiro_gatilho(m.fechados_h, processado_ate, conta.stop_loss, alvo_nivel,
                                   entrada_em=conta.entrada_em)
        if gatilho is not None:
            preco, quando, tipo = gatilho
            motivo = MOTIVO_ALVO if tipo == "alvo" else (conta.meta_entrada or {}).get("motivo_stop", "stop de catastrofe")
            # O patrimonio do dia D e o do FIM de D: se o gatilho caiu dentro
            # de D, a conta ja estava vendida quando D fechou.
            fim_de_d = vender(conta, preco, motivo)[0] if quando <= m.dia["fechamento_em"] else conta
            _registrar_patrimonio_com_seguranca(supabase, carteira.id, m, fim_de_d)
            return _vender(supabase, carteira, m, conta, id_decisao, registro, preco, quando, motivo,
                           referencia=_referencia(m.horarios, quando + 1, preco), executavel=m.preco)

    # Sem gatilho: a conta carregada e a do fim de D (as decisoes deste
    # ciclo acontecem depois de D fechar).
    _registrar_patrimonio_com_seguranca(supabase, carteira.id, m, conta)

    if carteira.usa_painel:
        return Resultado(carteira.id, m.par, "PENDENTE", "aguardando o painel",
                         pendente={"id_decisao": id_decisao, "registro": registro, "conta": conta})

    return _decidir(supabase, carteira, m, conta, id_decisao, registro, sinal, agora_ms)


def fase_painel(supabase, carteira: Carteira, m: Mercado, pendente: dict, veredito: dict | None,
                vereditos_desde_saida: list[bool] | None = None, agora_ms: int | None = None) -> Resultado:
    """
    T3 e G3, sobre a linha reivindicada em `fase_sem_ia`. `veredito` e a
    linha de `painel_veredito` do ultimo dia fechado (ou None se ainda
    pendente). So vale o veredito DAQUELE dia -- nunca um mais antigo.
    """
    agora_ms = agora_ms or _agora_ms()
    registro, conta = pendente["registro"], pendente["conta"]
    if veredito is None:
        sinal = regras.Sinal(False, False, False, None, "painel pendente")
    elif veredito["veredito"] == "sem_quorum":
        sinal = regras.Sinal(False, False, False, None, "sem quorum")
    else:
        dia_ms = _ms_do_dia(veredito["dia_utc"]) + DIA_MS - 1
        sinal = regras.Sinal(True, veredito["veredito"] == "compra", veredito["veredito"] == "venda", dia_ms,
                             f"conselho: soma {veredito['soma']:+d} com {veredito['validos']} votos ({veredito['veredito']})")
    atr = alvo.atr_pct(m.diarios)
    registro["features"] = {
        **registro["features"], "atr_pct": atr,
        "painel_veredito_id": (veredito or {}).get("id"),
        "veredito": (veredito or {}).get("veredito"), "soma": (veredito or {}).get("soma"),
        "validos": (veredito or {}).get("validos"), "votos": (veredito or {}).get("votos"),
        "veredito_congelado_em": (veredito or {}).get("congelado_em"),
    }
    sinal.leitura = registro["features"]
    return _decidir(supabase, carteira, m, conta, pendente["id_decisao"], registro, sinal, agora_ms,
                    compras_desde_saida=vereditos_desde_saida)


def concluir_sem_painel(supabase, carteira: Carteira, m: Mercado, pendente: dict, motivo: str) -> Resultado:
    """O prazo do job acabou antes do painel: conclui a linha sem decidir."""
    conta = pendente["conta"]
    acao = HOLD if conta.posicionada else NO_TRADE
    concluir_decisao(supabase, pendente["id_decisao"], {
        **pendente["registro"], "status": "hold" if conta.posicionada else "no_trade",
        "risk_result": {"estrategia": _estrategia(carteira), "acao_final": acao, "motivo": motivo},
    })
    return Resultado(carteira.id, m.par, acao, motivo, m.preco)


# ------------------------------------------------------------------ decisao


def _decidir(supabase, carteira, m, conta, id_decisao, registro, sinal, agora_ms, compras_desde_saida=None):
    acao, motivo = NO_TRADE, sinal.motivo
    rearme = None
    if conta.posicionada:
        acao = HOLD
        # Guarda de saida: so dias fechados depois do preenchimento da entrada.
        if sinal.pronto and sinal.venda and (conta.entrada_em is None or sinal.dia_fechamento_em > conta.entrada_em):
            acao = SELL
    elif not sinal.pronto:
        motivo = sinal.motivo if sinal.motivo in ("painel pendente", "sem quorum") else "historico insuficiente"
    elif sinal.compra:
        if not reguas.voto_vale_para_entrada(sinal.dia_fechamento_em, conta.ultima_saida_em):
            motivo = f"{sinal.motivo} -- travada: aguardando um dia fechar depois da ultima saida"
        elif carteira.com_alvo and not conta.armado:
            historico = compras_desde_saida if compras_desde_saida is not None else \
                regras.compras_desde(carteira.regra, m.diarios, conta.ultima_saida_em or 0)
            rearme = alvo.rearmada(historico)
            if rearme:
                acao = BUY
            else:
                motivo = f"{sinal.motivo} -- desarmada: esperando o sinal recuar e voltar depois da meta"
        else:
            acao = BUY
        if acao == BUY and carteira.com_alvo and sinal.leitura.get("atr_pct") is None:
            acao, motivo = NO_TRADE, "historico insuficiente para a meta (ATR)"

    # Nas regras diarias, o texto base descreve a acao tomada (manter nao e
    # "entra com 4"); os sufixos de trava e rearme ficam.
    if not carteira.usa_painel and sinal.pronto and "historico insuficiente" not in motivo:
        base = regras.motivo(carteira.regra, sinal.leitura, acao)
        motivo = base + motivo[len(sinal.motivo):] if motivo.startswith(sinal.motivo) else base

    registro["risk_result"] = {"estrategia": _estrategia(carteira), "acao_final": acao, "motivo": motivo,
                               "pode_entrar": acao == BUY or not sinal.compra}
    registro["features"]["pode_entrar"] = registro["risk_result"]["pode_entrar"]
    if not carteira.usa_painel and m.dia:
        referencia = _referencia(m.horarios, m.dia["fechamento_em"] + 1 + HORA_MS, m.preco)
    else:
        referencia = None

    if acao == BUY:
        leitura = sinal.leitura
        stop, motivo_stop = regras.nivel_de_stop(carteira.regra, m.preco, leitura)
        alvo_nivel = alvo.nivel_de_alvo(m.preco, leitura["atr_pct"]) if carteira.com_alvo else None
        conta, preenchimento = comprar(conta, m.preco, stop, alvo_nivel)
        conta = replace(
            conta, entrada_em=agora_ms, armado=True, recuo_dia=None,
            alvo_pct=(alvo_nivel / m.preco - 1) * 100 if alvo_nivel else None,
            meta_entrada={"dia_sinal": _data(sinal.dia_fechamento_em - DIA_MS + 1),
                          "atr_pct": leitura.get("atr_pct"), "n": leitura.get("n"),
                          "motivo_stop": motivo_stop, "stop_pct": (1 - stop / m.preco) * 100},
        )
        preenchimento.update({"motivo": motivo, "alvo_pct": conta.alvo_pct, "stop_tipo": motivo_stop,
                              "referencia_backtest": referencia, "explicacao_pendente": True})
        salvar_conta(supabase, conta)
        concluir_decisao(supabase, id_decisao, {**registro, "order_result": preenchimento, "status": "executed"})
        extra = f"; meta {conta.alvo_pct:+.1f}%" if conta.alvo_pct else ""
        return Resultado(carteira.id, m.par, BUY, f"{motivo}; stop {stop:,.2f}{extra}", m.preco)

    if acao == SELL:
        motivo_saida = MOTIVO_REPIQUE if carteira.regra == "rsi2" else MOTIVO_TENDENCIA
        return _vender(supabase, carteira, m, conta, id_decisao, registro, m.preco, m.ultimo_h["fechamento_em"],
                       motivo_saida, referencia=referencia, executavel=m.preco, detalhe=motivo)

    concluir_decisao(supabase, id_decisao, {**registro, "status": "hold" if acao == HOLD else "no_trade"})
    return Resultado(carteira.id, m.par, acao, motivo, m.preco)


def _vender(supabase, carteira, m, conta, id_decisao, registro, preco, gatilho_em, motivo,
            referencia=None, executavel=None, detalhe=None):
    conta, preenchimento = vender(conta, preco, motivo)
    conta = replace(conta, ultima_saida_em=gatilho_em, ultima_saida_motivo=motivo,
                    armado=motivo != MOTIVO_ALVO, recuo_dia=None, alvo_pct=None,
                    meta_entrada=None, entrada_em=None)
    preenchimento.update({"gatilho_em": gatilho_em, "referencia_backtest": referencia,
                          "preco_executavel": executavel, "explicacao_pendente": True})
    salvar_conta(supabase, conta)
    concluir_decisao(supabase, id_decisao, {
        **registro,
        "risk_result": {**registro.get("risk_result", {}), "estrategia": _estrategia(carteira),
                        "acao_final": SELL, "motivo": detalhe or motivo},
        "order_result": preenchimento,
        "status": "executed",
        "outcome": {"resultado": preenchimento["resultado"], "resultado_pct": preenchimento["resultado_pct"]},
    })
    return Resultado(carteira.id, m.par, SELL, detalhe or motivo, preco)


# ------------------------------------------------------------------ utilidades


def primeiro_gatilho(fechados, processado_ate, stop, alvo_nivel=None, entrada_em=None):
    """
    (preco, fechamento_em, 'stop'|'alvo') do primeiro fechamento de 1h nao
    visto que cruzou o stop ou o alvo. Cronologico: o primeiro decide. Um
    mesmo fechamento nao cruza os dois (o alvo fica acima da entrada e o
    stop abaixo).

    Fechamentos ANTERIORES a entrada nunca contam: depois de uma compra cuja
    linha ficou orfa, `processado_ate` fica para tras e a varredura veria
    precos que a posicao nunca viveu.
    """
    for c in fechados:
        if processado_ate is not None and c["fechamento_em"] <= processado_ate:
            continue
        if entrada_em is not None and c["fechamento_em"] <= entrada_em:
            continue
        if c["fechamento"] <= stop:
            return c["fechamento"], c["fechamento_em"], "stop"
        if alvo_nivel is not None and c["fechamento"] >= alvo_nivel:
            return c["fechamento"], c["fechamento_em"], "alvo"
    return None


def _referencia(horarios, abertura_em, preco):
    """
    Onde o motor de backtest executaria: a abertura do candle de 1h que
    comeca em `abertura_em` (decisao diaria: 01:00 UTC do dia seguinte ao
    sinal; stop/alvo: o candle seguinte ao gatilho). Se ele ainda nao
    abriu, o preco fica None e o instante gravado para a conferencia
    offline completar.
    """
    candle = next((c for c in horarios if c["abertura_em"] == abertura_em), None)
    ref = candle["abertura"] if candle else None
    return {"em": abertura_em, "preco": ref, "deslize_pct": (preco / ref - 1.0) * 100.0 if ref else None}


def _registrar_patrimonio_com_seguranca(supabase, carteira_id, m, conta) -> None:
    """O diario so alimenta o site: falhar nele nunca impede stop nem decisao."""
    try:
        registrar_patrimonio_diario(supabase, carteira_id, m, conta)
    except Exception as erro:  # noqa: BLE001
        print(f"  aviso: patrimonio_diario de {carteira_id} {m.par} nao gravado -- {erro}", flush=True)


def registrar_patrimonio_diario(supabase, carteira_id: str, m: Mercado, conta: ContaSimulada) -> None:
    """
    Patrimonio da conta no fechamento do ultimo dia fechado, gravado uma vez
    (o primeiro ciclo do dia; os seguintes nao sobrescrevem). E o que as
    curvas do site leem, sem precisar varrer todas as decisoes.
    """
    dia = m.dia
    if dia is None:
        return
    supabase.table("patrimonio_diario").upsert({
        "carteira": carteira_id, "asset": m.par, "dia_utc": _data(dia["abertura_em"]),
        "patrimonio": conta.caixa + conta.quantidade * dia["fechamento"],
        "posicionada": conta.posicionada, "preco_fechamento": dia["fechamento"],
    }, on_conflict="carteira,asset,dia_utc", ignore_duplicates=True).execute()


def _estrategia(carteira: Carteira) -> str:
    # O valor antigo da T1 ("tendencia_diaria") e o que o site ja filtra.
    return "tendencia_diaria" if carteira.id == "T1" else carteira.regra_versao


def _data(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).date().isoformat()


def _ms_do_dia(iso: str) -> int:
    d = datetime.fromisoformat(str(iso)[:10]).replace(tzinfo=timezone.utc)
    return int(d.timestamp() * 1000)
