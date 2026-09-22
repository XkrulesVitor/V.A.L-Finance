"""
Conferencia da regra de tendencia diaria e do ciclo ao vivo que a usa.

    python backend/tests/test_tendencia_diaria.py

Sem rede: Supabase, Binance e explicador sao dubles (os mesmos do
`test_ciclo_ao_vivo.py`, que conhecem o schema real das tabelas).

## O que mais importa aqui

- **o dia em andamento nao vota.** O estudo usa sempre o voto do dia
  anterior; se o ciclo ao vivo deixasse o dia corrente entrar, ele
  decidiria com um fechamento que ainda nao aconteceu -- e o numero do
  backtest deixaria de valer para ele.
- **o stop e conferido em todo fechamento de 1h nao visto**, e a saida
  sai no preco daquele fechamento.
- **depois de um stop, nao recompra com o voto velho.**
- **o explicador nunca bloqueia**: se o LLM cair, a operacao fica
  gravada igual.
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backtest.engine import BUY, HOLD, NO_TRADE, SELL  # noqa: E402
from estrategia import tendencia_diaria as regra  # noqa: E402
from live.ciclo_tendencia import MOTIVO_STOP, MOTIVO_TENDENCIA, rodar_ciclo_tendencia  # noqa: E402
from test_ciclo_ao_vivo import UMA_HORA, SupabaseDuble, _candles  # noqa: E402

UM_DIA = 24 * UMA_HORA


# ------------------------------------------------------------ a regra pura

def test_votos_contam_os_prazos_em_alta():
    subindo = [100.0 + i for i in range(120)]
    caindo = [300.0 - i for i in range(120)]
    assert regra.votos(subindo) == 6
    assert regra.votos(caindo) == 0


def test_historico_curto_nao_vota():
    assert regra.votos([100.0] * (max(regra.LOOKBACKS) - 1)) is None
    assert regra.decidir(None, False) == NO_TRADE
    assert regra.decidir(None, True) == HOLD, "sem dado, quem esta dentro fica"


def test_histerese():
    # fora: entra com 4+
    assert regra.decidir(4, False) == BUY
    assert regra.decidir(3, False) == NO_TRADE
    # dentro: sai com 2-
    assert regra.decidir(3, True) == HOLD
    assert regra.decidir(2, True) == SELL
    # entre os dois, cada lado mantem o que faz: e isso que evita o rodizio
    assert regra.decidir(3, False) == NO_TRADE and regra.decidir(3, True) == HOLD


def test_entrada_segurada_ate_um_dia_fechar_depois_da_saida():
    assert regra.decidir(6, False, pode_entrar=False) == NO_TRADE
    assert regra.decidir(1, True, pode_entrar=False) == SELL, "a trava so segura entrada"
    saida = 1_000_000
    assert not regra.voto_vale_para_entrada(saida, saida)
    assert not regra.voto_vale_para_entrada(saida - 1, saida)
    assert regra.voto_vale_para_entrada(saida + 1, saida)
    assert regra.voto_vale_para_entrada(saida, None)


# ------------------------------------------------------------ dubles

def _diarios(fechamentos, em_andamento=None):
    """Dias fechados terminando ontem, mais o dia de hoje em andamento."""
    hoje = int(time.time() * 1000) // UM_DIA * UM_DIA
    n = len(fechamentos)
    saida = []
    for i, f in enumerate(fechamentos):
        ab = hoje - (n - i) * UM_DIA
        saida.append({"abertura_em": ab, "abertura": f, "maxima": f, "minima": f,
                      "fechamento": f, "volume": 1.0, "fechamento_em": ab + UM_DIA - 1})
    f = em_andamento if em_andamento is not None else fechamentos[-1]
    saida.append({"abertura_em": hoje, "abertura": f, "maxima": f, "minima": f,
                  "fechamento": f, "volume": 1.0, "fechamento_em": hoje + UM_DIA - 1})
    return saida


SUBINDO = [50_000.0 + 300 * i for i in range(110)]    # ultimo 82.700: 6 votos
CAINDO = [110_000.0 - 300 * i for i in range(110)]    # 0 votos


class BinanceDuble:
    def __init__(self, diarios, horarios=None, preco=80_000.0):
        self.diarios = diarios
        self.horarios = horarios if horarios is not None else _candles(n=72, preco=preco)
        self.preco = preco
        self.intervalos = []

    def buscar_candles(self, simbolo, intervalo="1h", limite=100):
        self.intervalos.append((intervalo, limite))
        return self.diarios if intervalo == "1d" else self.horarios

    def buscar_preco(self, simbolo):
        return self.preco


class ExplicadorDuble:
    def __init__(self, erro=False):
        self.erro = erro
        self.fatos = None

    def explicar(self, fatos):
        self.fatos = fatos
        return (None, "RuntimeError: cota") if self.erro else ("frase de teste", None)


def _conta(qtd=0.125, caixa=0.0, entrada=80_000.0, stop=64_000.0):
    return [{"asset": "BTCUSDT", "quantity": qtd, "caixa": caixa,
             "preco_entrada": entrada, "stop_loss": stop, "take_profit": None}]


def _gravacoes(banco, tabela):
    return [e[2] for e in banco.escritas if e[0] == tabela and e[1] in ("upsert", "update")]


# ------------------------------------------------------------ o ciclo

def test_compra_com_stop_de_catastrofe_e_sem_alvo():
    banco = SupabaseDuble(portfolio=[{"asset": "BTCUSDT", "quantity": 0, "caixa": 10_000.0}])
    exp = ExplicadorDuble()
    r = rodar_ciclo_tendencia(banco, BinanceDuble(_diarios(SUBINDO)), exp, "BTCUSDT")
    assert r.acao == BUY, r
    conta = _gravacoes(banco, "portfolio")[-1]
    assert abs(conta["stop_loss"] - 80_000.0 * (1 - regra.STOP_CATASTROFE)) < 1e-6
    assert conta["take_profit"] is None, "regra de tendencia nao corta o ganho no alvo"
    assert conta["caixa"] == 0.0
    assert exp.fatos["operacao"] == "compra" and exp.fatos["prazos_em_alta"] == 6


def test_explicacao_e_anexada_depois_da_operacao_gravada():
    banco = SupabaseDuble(portfolio=[{"asset": "BTCUSDT", "quantity": 0, "caixa": 10_000.0}])
    rodar_ciclo_tendencia(banco, BinanceDuble(_diarios(SUBINDO)), ExplicadorDuble(), "BTCUSDT")
    ordem = [e for e in banco.escritas if e[0] in ("portfolio", "decisions") and e[1] != "insert"]
    tabelas = [e[0] for e in ordem]
    assert tabelas.index("portfolio") < len(tabelas) - 1, "conta gravada antes da explicacao"
    ultima = ordem[-1][2]
    assert ultima["order_result"]["explicacao"] == "frase de teste"
    assert ultima["order_result"]["lado"] == "BUY", "a explicacao nao pode apagar o preenchimento"


def test_explicador_fora_do_ar_nao_desfaz_a_operacao():
    banco = SupabaseDuble(portfolio=[{"asset": "BTCUSDT", "quantity": 0, "caixa": 10_000.0}])
    r = rodar_ciclo_tendencia(banco, BinanceDuble(_diarios(SUBINDO)), ExplicadorDuble(erro=True), "BTCUSDT")
    assert r.acao == BUY
    assert _gravacoes(banco, "portfolio")[-1]["quantity"] > 0
    final = banco.ultima_decisao()["order_result"]
    assert final["explicacao"] is None and "cota" in final["explicacao_erro"]


def test_dia_em_andamento_nao_vota():
    # Fechados caindo (0 votos). O dia de hoje, ainda aberto, disparou --
    # se ele entrasse na conta viraria 6 votos e compraria.
    diarios = _diarios(CAINDO, em_andamento=1_000_000.0)
    banco = SupabaseDuble(portfolio=[{"asset": "BTCUSDT", "quantity": 0, "caixa": 10_000.0}])
    r = rodar_ciclo_tendencia(banco, BinanceDuble(diarios), ExplicadorDuble(), "BTCUSDT")
    assert r.acao == NO_TRADE, r
    assert banco.ultima_decisao()["features"]["votos"] == 0


def test_sai_quando_a_tendencia_vira():
    banco = SupabaseDuble(portfolio=_conta())
    r = rodar_ciclo_tendencia(banco, BinanceDuble(_diarios(CAINDO)), ExplicadorDuble(), "BTCUSDT")
    assert r.acao == SELL, r
    assert banco.ultima_decisao()["order_result"]["motivo"] == MOTIVO_TENDENCIA
    assert _gravacoes(banco, "portfolio")[-1]["quantity"] == 0.0


def test_mantem_entre_os_limiares_sem_gravar_conta():
    # 3 votos: os prazos curtos em alta, os longos em baixa.
    serie = [100_000.0] * 70 + [70_000.0] * 35 + [75_000.0] * 5
    assert regra.votos(serie) == 3, regra.votos(serie)
    banco = SupabaseDuble(portfolio=_conta())
    r = rodar_ciclo_tendencia(banco, BinanceDuble(_diarios(serie)), ExplicadorDuble(), "BTCUSDT")
    assert r.acao == HOLD, r
    assert _gravacoes(banco, "portfolio") == []


def test_stop_em_fechamento_nao_visto_sai_no_preco_daquele_fechamento():
    horarios = _candles(n=72, preco=80_000.0)
    # 10 horas atras um fechamento furou o stop (64.000) e voltou.
    furou = horarios[-11]
    furou["fechamento"] = 63_000.0
    processado_ate = horarios[-20]["fechamento_em"]
    banco = SupabaseDuble(portfolio=_conta(), decisions=[{"candle_fechamento_em": processado_ate}])
    # tendencia ainda em alta: sem o stop, manteria
    r = rodar_ciclo_tendencia(banco, BinanceDuble(_diarios(SUBINDO), horarios=horarios),
                              ExplicadorDuble(), "BTCUSDT")
    assert r.acao == SELL, r
    ordem = banco.ultima_decisao()["order_result"]
    assert ordem["motivo"] == MOTIVO_STOP
    assert ordem["preco"] == 63_000.0, "sai no fechamento que furou, nao no preco de agora"
    assert ordem["gatilho_em"] == furou["fechamento_em"]


def test_fechamento_ja_visto_nao_dispara_stop_de_novo():
    horarios = _candles(n=72, preco=80_000.0)
    horarios[-11]["fechamento"] = 63_000.0
    processado_ate = horarios[-5]["fechamento_em"]  # ja passou daquele candle
    banco = SupabaseDuble(portfolio=_conta(), decisions=[{"candle_fechamento_em": processado_ate}])
    r = rodar_ciclo_tendencia(banco, BinanceDuble(_diarios(SUBINDO), horarios=horarios),
                              ExplicadorDuble(), "BTCUSDT")
    assert r.acao == HOLD, r


def test_nao_recompra_com_o_voto_velho_depois_de_um_stop():
    # Stop disparou hoje (depois do fechamento de ontem). Os votos de ontem
    # ainda dizem 6 -- os mesmos que mandaram comprar.
    diarios = _diarios(SUBINDO)
    saida = diarios[-2]["fechamento_em"] + 3 * UMA_HORA
    banco = SupabaseDuble(
        portfolio=[{"asset": "BTCUSDT", "quantity": 0, "caixa": 9_000.0}],
        decisions=[{"candle_fechamento_em": saida,
                    "order_result": {"lado": "SELL", "motivo": MOTIVO_STOP, "gatilho_em": saida}}],
    )
    r = rodar_ciclo_tendencia(banco, BinanceDuble(diarios), ExplicadorDuble(), "BTCUSDT")
    assert r.acao == NO_TRADE, r
    assert "aguardando" in r.detalhe


def test_recompra_quando_um_dia_fecha_depois_da_saida():
    diarios = _diarios(SUBINDO)
    saida = diarios[-3]["fechamento_em"] + 3 * UMA_HORA  # anteontem
    banco = SupabaseDuble(
        portfolio=[{"asset": "BTCUSDT", "quantity": 0, "caixa": 9_000.0}],
        decisions=[{"candle_fechamento_em": saida,
                    "order_result": {"lado": "SELL", "motivo": MOTIVO_STOP, "gatilho_em": saida}}],
    )
    r = rodar_ciclo_tendencia(banco, BinanceDuble(diarios), ExplicadorDuble(), "BTCUSDT")
    assert r.acao == BUY, r


def test_saida_de_outra_estrategia_nao_trava_a_entrada():
    # Uma venda da hibrida (por alvo) depois do ultimo fechamento diario nao
    # e um stop da regra e nao pode segurar a entrada.
    diarios = _diarios(SUBINDO)
    saida = diarios[-2]["fechamento_em"] + 3 * UMA_HORA
    banco = SupabaseDuble(
        portfolio=[{"asset": "BTCUSDT", "quantity": 0, "caixa": 9_000.0}],
        decisions=[{"candle_fechamento_em": saida,
                    "order_result": {"lado": "SELL", "motivo": "alvo atingido"}}],
    )
    r = rodar_ciclo_tendencia(banco, BinanceDuble(diarios), ExplicadorDuble(), "BTCUSDT")
    assert r.acao == BUY, r


def test_candle_ja_reivindicado_sai_sem_operar():
    banco = SupabaseDuble(portfolio=_conta(), candle_duplicado=True)
    r = rodar_ciclo_tendencia(banco, BinanceDuble(_diarios(CAINDO)), ExplicadorDuble(), "BTCUSDT")
    assert r.acao == "JA_PROCESSADO"
    assert _gravacoes(banco, "portfolio") == []


def test_pede_dias_suficientes_para_o_maior_prazo():
    b = BinanceDuble(_diarios(SUBINDO))
    banco = SupabaseDuble(portfolio=[{"asset": "BTCUSDT", "quantity": 0, "caixa": 10_000.0}])
    rodar_ciclo_tendencia(banco, b, ExplicadorDuble(), "BTCUSDT")
    dias = [lim for iv, lim in b.intervalos if iv == "1d"]
    assert dias and dias[0] >= max(regra.LOOKBACKS) + 1, "o dia em andamento e descartado"


# ------------------------------------------------ banco que filtra de verdade
#
# O `SupabaseDuble` compartilhado ignora os filtros (eq, neq, order) e
# devolve a tabela inteira. Foi por isso que a reivindicacao orfa passou
# pelos testes: o duble nao tinha como distinguir "processando" de
# concluida. Este aplica os filtros que o ciclo usa, inclusive caminho JSON
# (`order_result->>lado`), e guarda o que foi escrito como um banco guardaria.

class _Consulta:
    def __init__(self, banco, tabela):
        self.banco, self.tabela = banco, tabela
        self.filtros, self.ordem, self.limite, self.op, self.reg = [], None, None, "select", None
        self._negar = False

    @staticmethod
    def _valor(linha, coluna):
        if "->>" in coluna:
            base, chave = coluna.split("->>")
            v = (linha.get(base) or {}).get(chave)
            return None if v is None else str(v)
        return linha.get(coluna)

    def select(self, *_):
        return self

    def eq(self, c, v):
        esperado = str(v) if "->>" in c else v
        self.filtros.append(lambda linha: self._valor(linha, c) == esperado)
        return self

    def neq(self, c, v):
        self.filtros.append(lambda linha: self._valor(linha, c) != v)
        return self

    @property
    def not_(self):
        self._negar = True
        return self

    def is_(self, c, _nulo):
        negar, self._negar = self._negar, False
        self.filtros.append(lambda linha: (self._valor(linha, c) is None) != negar)
        return self

    def order(self, c, desc=False):
        self.ordem = (c, desc)
        return self

    def limit(self, n):
        self.limite = n
        return self

    def insert(self, r):
        self.op, self.reg = "insert", r
        return self

    def upsert(self, r, on_conflict=None):
        self.op, self.reg = "upsert", r
        return self

    def update(self, r):
        self.op, self.reg = "update", r
        return self

    def execute(self):
        linhas = self.banco.tabelas.setdefault(self.tabela, [])

        def resposta(dados):
            return type("R", (), {"data": dados})()

        if self.op == "select":
            sel = [linha for linha in linhas if all(f(linha) for f in self.filtros)]
            if self.ordem:
                sel.sort(key=lambda linha: linha.get(self.ordem[0]) or 0, reverse=self.ordem[1])
            return resposta(sel[: self.limite] if self.limite else sel)
        if self.op == "update" and self.banco.falhas_de_update:
            self.banco.falhas_de_update -= 1
            raise RuntimeError("503 Service Unavailable")
        self.banco.escritas.append((self.tabela, self.op, dict(self.reg)))
        if self.op == "insert":
            nova = {"id": f"d{len(linhas) + 1}", **self.reg}
            linhas.append(nova)
            return resposta([nova])
        if self.op == "upsert":
            for linha in linhas:
                if linha.get("asset") == self.reg["asset"]:
                    linha.update(self.reg)
                    return resposta([linha])
            linhas.append(dict(self.reg))
            return resposta([self.reg])
        alvo = [linha for linha in linhas if all(f(linha) for f in self.filtros)]
        for linha in alvo:
            linha.update(self.reg)
        return resposta(alvo)


class BancoFiltrado:
    def __init__(self, portfolio=None, decisions=None, falhas_de_update=0):
        self.tabelas = {"portfolio": list(portfolio or []), "decisions": list(decisions or [])}
        self.escritas = []
        self.falhas_de_update = falhas_de_update

    def table(self, nome):
        return _Consulta(self, nome)


def test_reivindicacao_orfa_nao_esconde_stop_furado():
    # Regressao (revisao de 21/09). Ultima decisao concluida ha 20h; depois
    # dela, uma reivindicacao ficou "processando" (o ciclo morreu). Entre as
    # duas, um fechamento furou o stop. A orfa nao pode contar como vista.
    horarios = _candles(n=72, preco=80_000.0)
    horarios[-11]["fechamento"] = 63_000.0
    banco = BancoFiltrado(portfolio=_conta(), decisions=[
        {"id": "a", "symbol": "BTCUSDT", "status": "hold",
         "candle_fechamento_em": horarios[-20]["fechamento_em"]},
        {"id": "b", "symbol": "BTCUSDT", "status": "processando",
         "candle_fechamento_em": horarios[-5]["fechamento_em"]},
    ])
    r = rodar_ciclo_tendencia(banco, BinanceDuble(_diarios(SUBINDO), horarios=horarios),
                              ExplicadorDuble(), "BTCUSDT")
    assert r.acao == SELL, r
    assert r.preco == 63_000.0


def test_posicao_herdada_da_hibrida_passa_aos_niveis_da_regra():
    # Regressao (revisao de 21/09): stop por ATR a 78.000 e alvo a 84.000.
    # Um fechamento a 77.900 NAO e um stop de catastrofe da regra.
    horarios = _candles(n=72, preco=80_000.0)
    horarios[-3]["fechamento"] = 77_900.0
    herdada = {**_conta()[0], "stop_loss": 78_000.0, "take_profit": 84_000.0}
    banco = BancoFiltrado(portfolio=[herdada], decisions=[
        {"id": "a", "symbol": "BTCUSDT", "status": "hold",
         "candle_fechamento_em": horarios[-10]["fechamento_em"]},
    ])
    r = rodar_ciclo_tendencia(banco, BinanceDuble(_diarios(SUBINDO), horarios=horarios),
                              ExplicadorDuble(), "BTCUSDT")
    assert r.acao == HOLD, r
    conta = banco.tabelas["portfolio"][0]
    assert abs(conta["stop_loss"] - 64_000.0) < 1e-6 and conta["take_profit"] is None
    atualizacoes = [e[2] for e in banco.escritas if e[0] == "decisions" and e[1] == "update"]
    assert atualizacoes[-1]["market_snapshot"]["niveis_herdados"] == {
        "stop_loss": 78_000.0, "take_profit": 84_000.0}


def test_preco_do_instante_nao_dispara_stop():
    # So fechamentos de 1h contam, como no estudo. O ticker abaixo do stop
    # com todos os fechamentos acima nao vende.
    banco = BancoFiltrado(portfolio=_conta())
    horarios = _candles(n=72, preco=80_000.0)  # todos os fechamentos acima do stop
    r = rodar_ciclo_tendencia(banco, BinanceDuble(_diarios(SUBINDO), horarios=horarios, preco=60_000.0),
                              ExplicadorDuble(), "BTCUSDT")
    assert r.acao == HOLD, r


def test_trava_so_olha_stops_da_regra_e_do_proprio_par():
    from live.estado import ultima_saida_ms
    banco = BancoFiltrado(decisions=[
        {"id": "1", "symbol": "BTCUSDT", "status": "executed", "candle_fechamento_em": 100,
         "order_result": {"lado": "SELL", "motivo": MOTIVO_STOP, "gatilho_em": 90}},
        {"id": "2", "symbol": "BTCUSDT", "status": "executed", "candle_fechamento_em": 300,
         "order_result": {"lado": "SELL", "motivo": "alvo atingido"}},
        {"id": "3", "symbol": "ETHUSDT", "status": "executed", "candle_fechamento_em": 400,
         "order_result": {"lado": "SELL", "motivo": MOTIVO_STOP, "gatilho_em": 390}},
    ])
    assert ultima_saida_ms(banco, "BTCUSDT", MOTIVO_STOP) == 90
    assert ultima_saida_ms(banco, "ETHUSDT", MOTIVO_STOP) == 390
    assert ultima_saida_ms(banco, "BNBUSDT", MOTIVO_STOP) is None


def test_conclusao_tenta_de_novo_em_erro_transitorio():
    import live.estado as estado
    esperas = []
    original, estado._esperar = estado._esperar, esperas.append
    try:
        banco = BancoFiltrado(portfolio=[{"asset": "BTCUSDT", "quantity": 0, "caixa": 10_000.0}],
                              falhas_de_update=2)
        r = rodar_ciclo_tendencia(banco, BinanceDuble(_diarios(SUBINDO)), ExplicadorDuble(), "BTCUSDT")
        assert r.acao == BUY, r
        linha = banco.tabelas["decisions"][0]
        assert linha["status"] == "executed" and linha["order_result"]["lado"] == "BUY"
        assert esperas == [1, 2]
    finally:
        estado._esperar = original


def test_operacao_grava_onde_o_backtest_executaria():
    # O estudo executa a decisao do voto de D na abertura das 01:00 UTC de
    # D+1. A compra grava esse preco e o deslize contra ele.
    diarios = _diarios(SUBINDO)
    ref_em = diarios[-2]["fechamento_em"] + 1 + UMA_HORA
    horarios = _candles(n=72, preco=80_000.0)
    horarios.insert(0, {"abertura_em": ref_em, "abertura": 79_200.0, "maxima": 79_200.0,
                        "minima": 79_200.0, "fechamento": 79_200.0, "volume": 1.0,
                        "fechamento_em": ref_em + UMA_HORA - 1})
    banco = BancoFiltrado(portfolio=[{"asset": "BTCUSDT", "quantity": 0, "caixa": 10_000.0}])
    rodar_ciclo_tendencia(banco, BinanceDuble(diarios, horarios=horarios), ExplicadorDuble(), "BTCUSDT")
    ref = banco.tabelas["decisions"][0]["order_result"]["referencia_backtest"]
    assert ref["em"] == ref_em and ref["preco"] == 79_200.0
    assert abs(ref["deslize_pct"] - (80_000.0 / 79_200.0 - 1) * 100) < 1e-9


def test_referencia_fica_pendente_se_o_candle_ainda_nao_abriu():
    banco = BancoFiltrado(portfolio=[{"asset": "BTCUSDT", "quantity": 0, "caixa": 10_000.0}])
    rodar_ciclo_tendencia(banco, BinanceDuble(_diarios(SUBINDO)), ExplicadorDuble(), "BTCUSDT")
    ref = banco.tabelas["decisions"][0]["order_result"]["referencia_backtest"]
    assert ref["em"] is not None and ref["preco"] is None and ref["deslize_pct"] is None


def test_leitura_diz_se_a_regra_esta_travada():
    diarios = _diarios(SUBINDO)
    saida = diarios[-2]["fechamento_em"] + 3 * UMA_HORA
    banco = BancoFiltrado(
        portfolio=[{"asset": "BTCUSDT", "quantity": 0, "caixa": 9_000.0}],
        decisions=[{"id": "s", "symbol": "BTCUSDT", "status": "executed", "candle_fechamento_em": saida,
                    "order_result": {"lado": "SELL", "motivo": MOTIVO_STOP, "gatilho_em": saida}}],
    )
    rodar_ciclo_tendencia(banco, BinanceDuble(diarios), ExplicadorDuble(), "BTCUSDT")
    nova = [linha for linha in banco.tabelas["decisions"] if linha["id"] != "s"][0]
    assert nova["features"]["pode_entrar"] is False and nova["features"]["votos"] == 6


def test_explicador_real_tem_timeout_curto():
    # Sem limite, uma conexao pendurada com o provedor segurava o par
    # seguinte ate o job morrer. O cliente so e criado sob demanda, entao
    # isto nao precisa de chave.
    from live.explicador import TIMEOUT_S, Explicador
    assert 0 < TIMEOUT_S <= 60
    assert Explicador().provedor.timeout_s == TIMEOUT_S


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
