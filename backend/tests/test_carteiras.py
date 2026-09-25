"""
Conferencia do ciclo das seis carteiras (`live/ciclo_carteira.py`).

    python backend/tests/test_carteiras.py

Sem rede: banco, Binance e explicador sao dubles (`tests/dubles.py`). O
banco em memoria aplica filtros e unicidades de verdade -- inclusive o
indice antigo de idempotencia, para testar a guarda da migracao.

Os testes da T1 sao os mesmos que protegiam `live/ciclo_tendencia.py`,
portados para o ciclo generico: a T1 nao pode mudar de comportamento.
"""

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backtest.engine import BUY, HOLD, NO_TRADE, SELL  # noqa: E402
from dubles import (  # noqa: E402
    CAINDO, SUBINDO, UMA_HORA, BancoFiltrado, BinanceDuble, ExplicadorDuble, diarios, horarios,
)
from estrategia import alvo, tartarugas  # noqa: E402
from estrategia import tendencia_diaria as reguas  # noqa: E402
from live import regras  # noqa: E402
from live.carteiras import POR_ID  # noqa: E402
from live.ciclo_carteira import (  # noqa: E402
    MOTIVO_ALVO, MOTIVO_REPIQUE, MOTIVO_TENDENCIA, concluir_sem_painel, fase_painel, fase_sem_ia,
)
from live.estado import ErroDeEstado  # noqa: E402
from live.explicador import explicar_pendentes  # noqa: E402
from live.mercado import buscar_mercado  # noqa: E402


def _ciclo(banco, binance, carteira="T1", par="BTCUSDT", agora_ms=None):
    return fase_sem_ia(banco, POR_ID[carteira], buscar_mercado(binance, par), agora_ms=agora_ms)


def _caixa(carteira="T1", caixa=10_000.0, **extra):
    return {"carteira": carteira, "asset": "BTCUSDT", "quantity": 0, "caixa": caixa, **extra}


def _comprada(carteira="T1", entrada=80_000.0, stop=64_000.0, alvo_=None, entrada_em=1, **extra):
    return {"carteira": carteira, "asset": "BTCUSDT", "quantity": 0.125, "caixa": 0.0,
            "preco_entrada": entrada, "stop_loss": stop, "take_profit": alvo_, "entrada_em": entrada_em, **extra}


def _ultima(banco, carteira="T1"):
    return banco.decisoes(carteira)[-1]


def _decisao_previa(carteira, fechamento_em, status="hold"):
    return {"id": f"p{carteira}{fechamento_em}", "carteira": carteira, "symbol": "BTCUSDT",
            "status": status, "candle_fechamento_em": fechamento_em}


# ================================================================== T1 (portados)


def test_t1_compra_com_stop_de_catastrofe_e_sem_alvo():
    banco = BancoFiltrado(portfolio=[_caixa()])
    r = _ciclo(banco, BinanceDuble(diarios(SUBINDO)))
    assert r.acao == BUY, r
    conta = banco.conta("T1")
    assert abs(conta["stop_loss"] - 80_000.0 * (1 - reguas.STOP_CATASTROFE)) < 1e-6
    assert conta["take_profit"] is None, "regra de tendencia nao corta o ganho no alvo"
    assert conta["caixa"] == 0.0 and conta["entrada_em"] is not None
    assert _ultima(banco)["order_result"]["explicacao_pendente"] is True


def test_explicacao_vem_depois_e_nao_apaga_o_preenchimento():
    banco = BancoFiltrado(portfolio=[_caixa()])
    _ciclo(banco, BinanceDuble(diarios(SUBINDO)))
    exp = ExplicadorDuble()
    from datetime import datetime, timezone
    n = explicar_pendentes(banco, exp, POR_ID, datetime.now(timezone.utc), lambda: True)
    assert n == 1
    ordem = _ultima(banco)["order_result"]
    assert ordem["explicacao"] == "frase de teste" and ordem["lado"] == "BUY"
    assert ordem["explicacao_pendente"] is False
    assert exp.fatos[0]["regra"] == POR_ID["T1"].descricao_regra
    assert exp.fatos[0]["prazos_em_alta"] == 6


def test_explicador_fora_do_ar_nao_desfaz_a_operacao_e_desiste_depois_de_3():
    from datetime import datetime, timezone
    banco = BancoFiltrado(portfolio=[_caixa()])
    _ciclo(banco, BinanceDuble(diarios(SUBINDO)))
    for tentativa in (1, 2, 3):
        explicar_pendentes(banco, ExplicadorDuble(erro=True), POR_ID, datetime.now(timezone.utc), lambda: True)
        ordem = _ultima(banco)["order_result"]
        assert ordem["explicacao"] is None and "cota" in ordem["explicacao_erro"]
        assert ordem["explicacao_pendente"] is (tentativa < 3)
    assert banco.conta("T1")["quantity"] > 0


def test_dia_em_andamento_nao_vota():
    banco = BancoFiltrado(portfolio=[_caixa()])
    r = _ciclo(banco, BinanceDuble(diarios(CAINDO, em_andamento=1_000_000.0)))
    assert r.acao == NO_TRADE, r
    assert _ultima(banco)["features"]["votos"] == 0


def test_t1_sai_quando_a_tendencia_vira():
    banco = BancoFiltrado(portfolio=[_comprada()])
    r = _ciclo(banco, BinanceDuble(diarios(CAINDO)))
    assert r.acao == SELL, r
    assert _ultima(banco)["order_result"]["motivo"] == MOTIVO_TENDENCIA
    conta = banco.conta("T1")
    assert conta["quantity"] == 0.0 and conta["ultima_saida_em"] is not None and conta["entrada_em"] is None


def test_mantem_entre_os_limiares_sem_gravar_conta():
    serie = [100_000.0] * 70 + [70_000.0] * 35 + [75_000.0] * 5
    assert reguas.votos(serie) == 3
    banco = BancoFiltrado(portfolio=[_comprada()])
    r = _ciclo(banco, BinanceDuble(diarios(serie)))
    assert r.acao == HOLD, r
    assert [e for e in banco.escritas if e[0] == "portfolio"] == []


def test_stop_em_fechamento_nao_visto_sai_no_preco_daquele_fechamento():
    h = horarios(preco=80_000.0)
    h[-11]["fechamento"] = 63_000.0
    banco = BancoFiltrado(portfolio=[_comprada()], decisions=[_decisao_previa("T1", h[-20]["fechamento_em"])])
    r = _ciclo(banco, BinanceDuble(diarios(SUBINDO), h, preco=79_000.0))
    assert r.acao == SELL, r
    ordem = _ultima(banco)["order_result"]
    assert ordem["motivo"] == "stop de catastrofe"
    assert ordem["preco"] == 63_000.0, "sai no fechamento que furou, nao no preco de agora"
    assert ordem["preco_executavel"] == 79_000.0, "o ticker do instante fica gravado ao lado"
    assert ordem["gatilho_em"] == h[-11]["fechamento_em"]


def test_fechamento_ja_visto_nao_dispara_stop_de_novo():
    h = horarios(preco=80_000.0)
    h[-11]["fechamento"] = 63_000.0
    banco = BancoFiltrado(portfolio=[_comprada()], decisions=[_decisao_previa("T1", h[-5]["fechamento_em"])])
    assert _ciclo(banco, BinanceDuble(diarios(SUBINDO), h)).acao == HOLD


def test_reivindicacao_orfa_nao_esconde_stop_furado():
    h = horarios(preco=80_000.0)
    h[-11]["fechamento"] = 63_000.0
    banco = BancoFiltrado(portfolio=[_comprada()], decisions=[
        _decisao_previa("T1", h[-20]["fechamento_em"]),
        _decisao_previa("T1", h[-5]["fechamento_em"], status="processando")])
    r = _ciclo(banco, BinanceDuble(diarios(SUBINDO), h))
    assert r.acao == SELL and r.preco == 63_000.0, r


def test_preco_do_instante_nao_dispara_stop():
    banco = BancoFiltrado(portfolio=[_comprada()])
    r = _ciclo(banco, BinanceDuble(diarios(SUBINDO), horarios(preco=80_000.0), preco=60_000.0))
    assert r.acao == HOLD, r


def test_nao_recompra_com_o_voto_velho_depois_de_um_stop():
    d = diarios(SUBINDO)
    saida = d[-2]["fechamento_em"] + 3 * UMA_HORA   # durante o dia de hoje
    banco = BancoFiltrado(portfolio=[_caixa(ultima_saida_em=saida, ultima_saida_motivo="stop de catastrofe")])
    r = _ciclo(banco, BinanceDuble(d))
    assert r.acao == NO_TRADE and "travada" in r.detalhe, r
    assert _ultima(banco)["features"]["pode_entrar"] is False


def test_recompra_quando_um_dia_fecha_depois_da_saida():
    d = diarios(SUBINDO)
    saida = d[-3]["fechamento_em"] + 3 * UMA_HORA   # anteontem
    banco = BancoFiltrado(portfolio=[_caixa(ultima_saida_em=saida)])
    assert _ciclo(banco, BinanceDuble(d)).acao == BUY


def test_conta_antiga_sem_ultima_saida_nao_trava():
    # As saidas da hibrida (antes de 22/09) nao gravaram `ultima_saida_em`.
    banco = BancoFiltrado(portfolio=[_caixa(caixa=9_000.0)])
    assert _ciclo(banco, BinanceDuble(diarios(SUBINDO))).acao == BUY


def test_candle_ja_reivindicado_pela_mesma_carteira_sai_sem_operar():
    h = horarios()
    banco = BancoFiltrado(portfolio=[_comprada()], decisions=[_decisao_previa("T1", h[-2]["fechamento_em"])])
    r = _ciclo(banco, BinanceDuble(diarios(CAINDO), h))
    assert r.acao == "JA_PROCESSADO"
    assert [e for e in banco.escritas if e[0] == "portfolio"] == []


def test_indice_antigo_ativo_falha_alto_para_as_carteiras_novas():
    # Etapa B da migracao nao aplicada: a T1 reivindicou o candle e o indice
    # (symbol, candle) recusa a G1. Isso nao pode virar "ja processado".
    h = horarios()
    banco = BancoFiltrado(indice_antigo=True, decisions=[_decisao_previa("T1", h[-2]["fechamento_em"])])
    try:
        _ciclo(banco, BinanceDuble(diarios(SUBINDO), h), carteira="G1")
    except ErroDeEstado as erro:
        assert "etapa B" in str(erro)
        return
    raise AssertionError("indice antigo deveria falhar alto")


def test_pede_trezentos_dias_fechados():
    b = BinanceDuble(diarios(SUBINDO))
    _ciclo(BancoFiltrado(), b)
    assert [lim for _, iv, lim in b.pedidos if iv == "1d"] == [301]


def test_posicao_herdada_da_hibrida_passa_aos_niveis_da_regra_so_na_t1():
    h = horarios(preco=80_000.0)
    h[-3]["fechamento"] = 77_900.0
    herdada = _comprada(stop=78_000.0, alvo_=84_000.0)
    banco = BancoFiltrado(portfolio=[herdada], decisions=[_decisao_previa("T1", h[-10]["fechamento_em"])])
    assert _ciclo(banco, BinanceDuble(diarios(SUBINDO), h)).acao == HOLD
    conta = banco.conta("T1")
    assert abs(conta["stop_loss"] - 64_000.0) < 1e-6 and conta["take_profit"] is None
    assert _ultima(banco)["market_snapshot"]["niveis_herdados"] == {"stop_loss": 78_000.0, "take_profit": 84_000.0}


def test_conclusao_tenta_de_novo_em_erro_transitorio():
    import live.estado as estado
    esperas = []
    original, estado._esperar = estado._esperar, esperas.append
    try:
        banco = BancoFiltrado(portfolio=[_caixa()], falhas_de_update=2)
        assert _ciclo(banco, BinanceDuble(diarios(SUBINDO))).acao == BUY
        assert _ultima(banco)["status"] == "executed" and esperas == [1, 2]
    finally:
        estado._esperar = original


def test_operacao_grava_onde_o_backtest_executaria():
    d = diarios(SUBINDO)
    ref_em = d[-2]["fechamento_em"] + 1 + UMA_HORA
    h = horarios(preco=80_000.0)
    h.insert(0, {"abertura_em": ref_em, "abertura": 79_200.0, "maxima": 79_200.0, "minima": 79_200.0,
                 "fechamento": 79_200.0, "volume": 1.0, "fechamento_em": ref_em + UMA_HORA - 1})
    banco = BancoFiltrado(portfolio=[_caixa()])
    _ciclo(banco, BinanceDuble(d, h))
    ref = _ultima(banco)["order_result"]["referencia_backtest"]
    assert ref["em"] == ref_em and ref["preco"] == 79_200.0
    assert abs(ref["deslize_pct"] - (80_000.0 / 79_200.0 - 1) * 100) < 1e-9


def test_patrimonio_diario_e_gravado_uma_vez_por_dia():
    d = diarios(SUBINDO)
    h = horarios()
    banco = BancoFiltrado(portfolio=[_caixa()])
    _ciclo(banco, BinanceDuble(d, h))                       # compra
    h2 = h + [dict(h[-1], abertura_em=h[-1]["abertura_em"] + UMA_HORA, fechamento_em=h[-1]["fechamento_em"] + UMA_HORA)]
    h2[-2] = dict(h2[-2], fechamento_em=int(time.time() * 1000) - 1)   # fecha o candle que estava em curso
    _ciclo(banco, BinanceDuble(d, h2))                      # 2o ciclo do dia
    linhas = banco.linhas("patrimonio_diario", carteira="T1")
    assert len(linhas) == 1 and linhas[0]["patrimonio"] == 10_000.0 and linhas[0]["posicionada"] is False


def test_carteiras_nao_se_misturam():
    d, h = diarios(SUBINDO), horarios()
    banco = BancoFiltrado(portfolio=[_caixa("T1"), _caixa("G1")])
    assert _ciclo(banco, BinanceDuble(d, h), "T1").acao == BUY
    assert banco.conta("G1")["quantity"] == 0, "a compra da T1 nao pode mexer na conta da G1"
    assert _ciclo(banco, BinanceDuble(d, h), "G1").acao == BUY, "mesmo candle, carteiras diferentes"
    assert len(banco.decisoes("T1")) == 1 and len(banco.decisoes("G1")) == 1


def test_patrimonio_do_dia_e_o_do_fim_do_dia_mesmo_com_stop_na_varredura():
    # Regressao (revisao de 25/09): o diario era gravado antes da varredura.
    # O stop cruzou num fechamento de ONTEM que ninguem tinha visto: ontem
    # terminou vendido, e a linha de ontem tem de dizer isso.
    d = diarios(SUBINDO)
    h = horarios(preco=80_000.0)
    idx = next(i for i, c in enumerate(h) if c["fechamento_em"] <= d[-2]["fechamento_em"] and
               c["fechamento_em"] > d[-2]["fechamento_em"] - 3 * UMA_HORA)
    h[idx]["fechamento"] = 63_000.0
    banco = BancoFiltrado(portfolio=[_comprada()], decisions=[_decisao_previa("T1", h[idx - 5]["fechamento_em"])])
    r = _ciclo(banco, BinanceDuble(d, h))
    assert r.acao == SELL and r.preco == 63_000.0, r
    [linha] = banco.linhas("patrimonio_diario", carteira="T1")
    assert linha["posicionada"] is False and abs(linha["patrimonio"] - banco.conta("T1")["caixa"]) < 1e-9


def test_varredura_ignora_fechamentos_anteriores_a_entrada():
    # Regressao: compra cuja linha ficou orfa deixa `processado_ate` para
    # tras; o alvo nao pode disparar num preco anterior a propria compra.
    h = horarios(preco=80_000.0)
    h[-20]["fechamento"] = 90_000.0          # antes da entrada
    conta = _comprada("G1", alvo_=85_000.0, entrada_em=h[-10]["fechamento_em"])
    banco = BancoFiltrado(portfolio=[conta], decisions=[_decisao_previa("G1", h[-30]["fechamento_em"])])
    assert _ciclo(banco, BinanceDuble(diarios(SUBINDO), h), "G1").acao == HOLD


def test_motivo_descreve_a_acao_e_nao_so_o_sinal():
    banco = BancoFiltrado(portfolio=[_comprada()])
    r = _ciclo(banco, BinanceDuble(diarios(SUBINDO)))
    assert r.acao == HOLD and r.detalhe == "6 de 6 prazos em alta", r
    banco = BancoFiltrado(portfolio=[_caixa("T2")])
    serie = list(SUBINDO[:-1]) + [SUBINDO[-2] * 0.99]
    r = _ciclo(banco, BinanceDuble(diarios(serie)), "T2")
    assert r.acao == NO_TRADE and r.detalhe.startswith("sem rompimento"), r


# ================================================================== T2 Tartarugas


def test_t2_compra_no_rompimento_com_stop_2n():
    d = diarios(SUBINDO)
    banco = BancoFiltrado(portfolio=[_caixa("T2")])
    assert _ciclo(banco, BinanceDuble(d), "T2").acao == BUY
    n = tartarugas.leitura(d[:-1])["n"]
    conta = banco.conta("T2")
    assert abs(conta["stop_loss"] - tartarugas.nivel_de_stop(80_000.0, n)) < 1e-6
    assert conta["meta_entrada"]["motivo_stop"] == "stop 2N" and conta["take_profit"] is None


def test_t2_sem_rompimento_fica_em_caixa():
    serie = list(SUBINDO[:-1]) + [SUBINDO[-2] * 0.99]
    banco = BancoFiltrado(portfolio=[_caixa("T2")])
    assert _ciclo(banco, BinanceDuble(diarios(serie)), "T2").acao == NO_TRADE


def test_t2_sai_abaixo_da_minima_de_20_dias():
    serie = list(SUBINDO[:-1]) + [SUBINDO[-21] * 0.9]
    banco = BancoFiltrado(portfolio=[_comprada("T2", stop=40_000.0)])
    assert _ciclo(banco, BinanceDuble(diarios(serie)), "T2").acao == SELL
    assert _ultima(banco, "T2")["order_result"]["motivo"] == MOTIVO_TENDENCIA


def test_t2_stop_2n_grava_o_motivo_certo():
    h = horarios(preco=80_000.0)
    h[-4]["fechamento"] = 74_000.0
    conta = _comprada("T2", stop=75_000.0, meta_entrada={"motivo_stop": "stop 2N"})
    banco = BancoFiltrado(portfolio=[conta], decisions=[_decisao_previa("T2", h[-10]["fechamento_em"])])
    assert _ciclo(banco, BinanceDuble(diarios(SUBINDO), h), "T2").acao == SELL
    assert _ultima(banco, "T2")["order_result"]["motivo"] == "stop 2N"


# ================================================================== G1 Reguas com meta


def test_g1_compra_com_meta_de_3_atr():
    d = diarios(SUBINDO)
    banco = BancoFiltrado(portfolio=[_caixa("G1")])
    assert _ciclo(banco, BinanceDuble(d), "G1").acao == BUY
    atr = alvo.atr_pct(d[:-1])
    conta = banco.conta("G1")
    assert abs(conta["take_profit"] - 80_000.0 * (1 + 3 * atr)) < 1e-6
    assert abs(conta["alvo_pct"] - 300 * atr) < 1e-9 and conta["armado"] is True


def test_g1_vende_na_meta_e_desarma():
    h = horarios(preco=80_000.0)
    h[-6]["fechamento"] = 88_500.0
    banco = BancoFiltrado(portfolio=[_comprada("G1", alvo_=88_000.0)],
                          decisions=[_decisao_previa("G1", h[-10]["fechamento_em"])])
    r = _ciclo(banco, BinanceDuble(diarios(SUBINDO), h), "G1")
    assert r.acao == SELL and r.preco == 88_500.0, r
    assert _ultima(banco, "G1")["order_result"]["motivo"] == MOTIVO_ALVO
    conta = banco.conta("G1")
    assert conta["armado"] is False and conta["ultima_saida_em"] == h[-6]["fechamento_em"]


def test_g1_desarmada_nao_recompra_com_a_tendencia_intacta():
    d = diarios(SUBINDO)
    saida = d[-3]["fechamento_em"] + 3 * UMA_HORA   # durante ontem; ontem fechou com 6 votos
    banco = BancoFiltrado(portfolio=[_caixa("G1", armado=False, ultima_saida_em=saida, ultima_saida_motivo=MOTIVO_ALVO)])
    r = _ciclo(banco, BinanceDuble(d), "G1")
    assert r.acao == NO_TRADE and "desarmada" in r.detalhe, r


def test_g1_rearma_depois_de_um_recuo_e_da_volta_da_alta():
    serie = list(SUBINDO)
    serie[-2] *= 0.97            # anteontem: 3 votos (recuo)
    d = diarios(serie)
    saida = d[-4]["fechamento_em"] + 3 * UMA_HORA   # antes do recuo fechar
    banco = BancoFiltrado(portfolio=[_caixa("G1", armado=False, ultima_saida_em=saida, ultima_saida_motivo=MOTIVO_ALVO)])
    assert regras.compras_desde("reguas", d[:-1], saida) == [False, True]
    assert _ciclo(banco, BinanceDuble(d), "G1").acao == BUY
    assert banco.conta("G1")["armado"] is True


def test_g1_sem_historico_para_o_atr_nao_entra():
    serie = SUBINDO[-120:]        # 120 dias: Reguas prontas, ATR (150) nao
    banco = BancoFiltrado(portfolio=[_caixa("G1")])
    r = _ciclo(banco, BinanceDuble(diarios(serie)), "G1")
    assert r.acao == NO_TRADE and "ATR" in r.detalhe, r


# ================================================================== G2 Repique


def _serie_queda_curta():
    s = [50_000.0 * (1.003 ** i) for i in range(300)]
    s[-2] *= 0.95
    s[-1] = s[-2] * 0.95
    return s


def test_g2_compra_a_queda_curta_na_alta_longa():
    banco = BancoFiltrado(portfolio=[_caixa("G2")])
    assert _ciclo(banco, BinanceDuble(diarios(_serie_queda_curta())), "G2").acao == BUY
    conta = banco.conta("G2")
    assert conta["take_profit"] is None and abs(conta["stop_loss"] - 64_000.0) < 1e-6


def test_g2_vende_no_repique():
    banco = BancoFiltrado(portfolio=[_comprada("G2")])
    assert _ciclo(banco, BinanceDuble(diarios(SUBINDO)), "G2").acao == SELL
    assert _ultima(banco, "G2")["order_result"]["motivo"] == MOTIVO_REPIQUE


def test_guarda_de_saida_nao_vende_com_o_sinal_do_dia_da_compra():
    # Comprou depois do fechamento de ontem: o "repique" de ontem nao conta.
    d = diarios(SUBINDO)
    banco = BancoFiltrado(portfolio=[_comprada("G2", entrada_em=d[-2]["fechamento_em"] + 5 * UMA_HORA)])
    assert _ciclo(banco, BinanceDuble(d), "G2").acao == HOLD


# ================================================================== T3 e G3 (painel)


def _veredito(tipo, soma, dia_iso, validos=3):
    return {"id": "v1", "dia_utc": dia_iso, "simbolo": "BTCUSDT", "veredito": tipo, "soma": soma,
            "validos": validos, "votos": {"G": "UP", "N": "UP", "C": "SIDEWAYS"}, "congelado_em": "x"}


def _dia_iso(d):
    from datetime import datetime, timezone
    return datetime.fromtimestamp(d[-2]["abertura_em"] / 1000, timezone.utc).date().isoformat()


def test_t3_fica_pendente_ate_o_painel():
    banco = BancoFiltrado(portfolio=[_caixa("T3")])
    r = _ciclo(banco, BinanceDuble(diarios(SUBINDO)), "T3")
    assert r.acao == "PENDENTE" and r.pendente
    assert _ultima(banco, "T3")["status"] == "processando", "a linha fica reivindicada ate a fase do painel"


def test_t3_e_g3_compram_com_o_mesmo_veredito():
    d = diarios(SUBINDO)
    banco = BancoFiltrado(portfolio=[_caixa("T3"), _caixa("G3")])
    m = buscar_mercado(BinanceDuble(d), "BTCUSDT")
    v = _veredito("compra", 2, _dia_iso(d))
    for c in ("T3", "G3"):
        r = fase_sem_ia(banco, POR_ID[c], m)
        assert fase_painel(banco, POR_ID[c], m, r.pendente, v).acao == BUY
    assert banco.conta("T3")["take_profit"] is None
    assert banco.conta("G3")["take_profit"] is not None, "G3 tem a meta"
    assert _ultima(banco, "G3")["features"]["painel_veredito_id"] == "v1"


def test_painel_pendente_e_sem_quorum_nao_operam():
    d = diarios(SUBINDO)
    m = buscar_mercado(BinanceDuble(d), "BTCUSDT")
    for v, texto in ((None, "painel pendente"), (_veredito("sem_quorum", 0, _dia_iso(d), 1), "sem quorum")):
        banco = BancoFiltrado(portfolio=[_caixa("T3")])
        r = fase_sem_ia(banco, POR_ID["T3"], m)
        final = fase_painel(banco, POR_ID["T3"], m, r.pendente, v)
        assert final.acao == NO_TRADE and final.detalhe == texto, final


def test_t3_vende_com_veredito_de_venda():
    d = diarios(SUBINDO)
    m = buscar_mercado(BinanceDuble(d), "BTCUSDT")
    banco = BancoFiltrado(portfolio=[_comprada("T3")])
    r = fase_sem_ia(banco, POR_ID["T3"], m)
    assert fase_painel(banco, POR_ID["T3"], m, r.pendente, _veredito("venda", -1, _dia_iso(d))).acao == SELL


def test_g3_desarmada_rearma_pelos_vereditos():
    d = diarios(SUBINDO)
    m = buscar_mercado(BinanceDuble(d), "BTCUSDT")
    conta = _caixa("G3", armado=False, ultima_saida_em=d[-4]["fechamento_em"], ultima_saida_motivo=MOTIVO_ALVO)
    v = _veredito("compra", 2, _dia_iso(d))
    for historico, esperado in (([True, True], NO_TRADE), ([False, True], BUY)):
        banco = BancoFiltrado(portfolio=[conta])
        r = fase_sem_ia(banco, POR_ID["G3"], m)
        assert fase_painel(banco, POR_ID["G3"], m, r.pendente, v, historico).acao == esperado


def test_concluir_sem_painel_fecha_a_linha():
    banco = BancoFiltrado(portfolio=[_comprada("T3")])
    m = buscar_mercado(BinanceDuble(diarios(SUBINDO)), "BTCUSDT")
    r = fase_sem_ia(banco, POR_ID["T3"], m)
    final = concluir_sem_painel(banco, POR_ID["T3"], m, r.pendente, "painel pendente")
    assert final.acao == HOLD and _ultima(banco, "T3")["status"] == "hold"


def test_stop_do_conselho_roda_antes_de_qualquer_ia():
    h = horarios(preco=80_000.0)
    h[-3]["fechamento"] = 63_000.0
    banco = BancoFiltrado(portfolio=[_comprada("T3")], decisions=[_decisao_previa("T3", h[-10]["fechamento_em"])])
    r = _ciclo(banco, BinanceDuble(diarios(SUBINDO), h), "T3")
    assert r.acao == SELL and r.pendente is None, "stop resolvido sem esperar o painel"


# ================================================================== gratuidade


def test_workflow_nao_injeta_provedor_pago():
    # O provedor "claude" e pago. Com LLM_PROVEDOR no job, qualquer
    # `criar_provedor()` sem nome poderia cair nele.
    wf = (Path(__file__).resolve().parents[2] / ".github" / "workflows" / "forward-test.yml").read_text(encoding="utf-8")
    env = [linha for linha in wf.splitlines() if not linha.strip().startswith("#")]
    assert not any("ANTHROPIC_API_KEY" in linha or "LLM_PROVEDOR" in linha for linha in env)
    assert any("OPENROUTER_API_KEY" in linha for linha in env)


def test_painel_so_usa_modelos_gratis():
    from live.painel import VAGAS
    for vaga in VAGAS:
        if vaga.provedor == "openrouter":
            assert all(m.endswith(":free") for m in vaga.cadeia), vaga


# ================================================================== runner


def _rodar_tudo() -> int:
    testes = sorted((n, f) for n, f in globals().items() if n.startswith("test_") and callable(f))
    falhas = []
    for nome, funcao in testes:
        try:
            funcao()
            print(f"  ok    {nome}")
        except AssertionError as erro:
            falhas.append(nome)
            print(f"  FALHA {nome}: {erro}")
        except Exception as erro:  # noqa: BLE001
            falhas.append(nome)
            print(f"  ERRO  {nome}: {type(erro).__name__}: {erro}")
    print(f"\n{len(testes) - len(falhas)}/{len(testes)} passaram")
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(_rodar_tudo())
