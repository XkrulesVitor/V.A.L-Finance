"""
Conferencia do Risk Engine (passo 6).

    python backend/tests/test_risk_engine.py
    pytest backend/tests

Sem rede: `avaliar_risco` e uma funcao pura, entao tudo aqui e
aritmetica com numeros escolhidos a mao.

O teste mais importante do arquivo -- e provavelmente do projeto ate
aqui -- e `test_stop_rompido_sobrepoe_o_hold_do_llm`. Ele reproduz o
cenario exato medido na validacao do passo 5: posicao aberta, preco
abaixo do stop registrado, e o cerebro dizendo HOLD "para evitar
realizar prejuizo". Se esse teste passar a falhar um dia, o vies de
aversao a perda do modelo voltou a ter caminho livre pra carteira.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from risk.portfolio_repo import (  # noqa: E402
    COLUNAS_DE_RISCO,
    ErroDePortfolio,
    _e_coluna_ausente,
    buscar_posicao,
)
from risk.risk_engine import (  # noqa: E402
    BUY,
    HOLD,
    NO_TRADE,
    SELL,
    EstadoDaPosicao,
    ParametrosDeRisco,
    avaliar_risco,
)

CAPITAL = 10_000.0


def tese(direcao, confidence=0.7, horizon="medio"):
    """Dicionario no formato de `TeseDeOperacao` -- o engine aceita os dois."""
    return {
        "direction": direcao,
        "horizon": horizon,
        "confidence": confidence,
        "reasoning": "teste",
    }


def perto(a, b, tol=1e-9):
    return abs(a - b) <= tol


# --------------------------------------------------------------------
# REGRA 1 -- a autoridade de sobrepor o cerebro
# --------------------------------------------------------------------


def test_stop_rompido_sobrepoe_o_hold_do_llm():
    """
    O cenario do passo 5, reproduzido.

    Posicao aberta a 100.000 com stop em 96.000. O preco caiu para
    95.000 -- abaixo do stop. O cerebro, como fez na validacao real,
    responde HOLD ("melhor nao realizar prejuizo agora").

    O Risk Engine tem que sair da posicao mesmo assim.
    """
    posicao = EstadoDaPosicao(
        quantidade=0.1, preco_entrada=100_000.0, stop_loss=96_000.0, take_profit=106_000.0
    )
    resultado = avaliar_risco(
        tese=tese(HOLD),
        atr_14=2_000.0,
        preco_atual=95_000.0,
        posicao=posicao,
        capital_total=CAPITAL,
    )

    assert resultado.acao_final == SELL, resultado.acao_final
    assert resultado.override_do_llm is True
    assert resultado.aprovado is True
    assert resultado.direcao_do_llm == HOLD
    assert resultado.tamanho_posicao == 0.1
    assert "Stop-loss" in resultado.motivo
    assert "HOLD" in resultado.motivo, "o motivo precisa dizer o que foi sobreposto"


def test_take_profit_ultrapassado_sobrepoe_o_hold_do_llm():
    posicao = EstadoDaPosicao(
        quantidade=0.1, preco_entrada=100_000.0, stop_loss=96_000.0, take_profit=106_000.0
    )
    resultado = avaliar_risco(
        tese=tese(HOLD), atr_14=2_000.0, preco_atual=107_000.0,
        posicao=posicao, capital_total=CAPITAL,
    )

    assert resultado.acao_final == SELL
    assert resultado.override_do_llm is True
    assert "Take-profit" in resultado.motivo


def test_override_vale_tambem_contra_buy():
    """A regra 1 nao consulta a tese -- sobrepoe qualquer direcao, nao so HOLD."""
    posicao = EstadoDaPosicao(quantidade=0.1, preco_entrada=100_000.0, stop_loss=96_000.0)
    resultado = avaliar_risco(
        tese=tese(BUY), atr_14=2_000.0, preco_atual=95_000.0,
        posicao=posicao, capital_total=CAPITAL,
    )
    assert resultado.acao_final == SELL
    assert resultado.override_do_llm is True


def test_sell_do_llm_no_stop_nao_conta_como_override():
    """Se o cerebro ja concordava, nao houve discordancia a registrar."""
    posicao = EstadoDaPosicao(quantidade=0.1, preco_entrada=100_000.0, stop_loss=96_000.0)
    resultado = avaliar_risco(
        tese=tese(SELL), atr_14=2_000.0, preco_atual=95_000.0,
        posicao=posicao, capital_total=CAPITAL,
    )
    assert resultado.acao_final == SELL
    assert resultado.override_do_llm is False


def test_preco_exatamente_no_nivel_ja_dispara():
    """Nivel atingido e nivel atingido -- nao se perde o gatilho por um centavo."""
    posicao = EstadoDaPosicao(quantidade=0.1, preco_entrada=100_000.0,
                              stop_loss=96_000.0, take_profit=106_000.0)
    no_stop = avaliar_risco(tese(HOLD), 2_000.0, 96_000.0, posicao, CAPITAL)
    no_alvo = avaliar_risco(tese(HOLD), 2_000.0, 106_000.0, posicao, CAPITAL)
    assert no_stop.acao_final == SELL
    assert no_alvo.acao_final == SELL


def test_dentro_dos_niveis_nao_dispara():
    posicao = EstadoDaPosicao(quantidade=0.1, preco_entrada=100_000.0,
                              stop_loss=96_000.0, take_profit=106_000.0)
    resultado = avaliar_risco(tese(HOLD), 2_000.0, 100_500.0, posicao, CAPITAL)
    assert resultado.acao_final == HOLD
    assert resultado.override_do_llm is False


def test_posicao_sem_niveis_registrados_nao_dispara():
    """Nivel None nao existe, logo nao pode ser rompido."""
    posicao = EstadoDaPosicao(quantidade=0.1, preco_entrada=100_000.0)
    resultado = avaliar_risco(tese(HOLD), 2_000.0, 1.0, posicao, CAPITAL)
    assert resultado.acao_final == HOLD


def test_sem_posicao_niveis_antigos_nao_disparam():
    resultado = avaliar_risco(
        tese(NO_TRADE), 2_000.0, 1.0,
        EstadoDaPosicao(quantidade=0.0, stop_loss=96_000.0), CAPITAL,
    )
    assert resultado.acao_final == NO_TRADE


# --------------------------------------------------------------------
# REGRA 2 -- abertura de posicao
# --------------------------------------------------------------------


def test_tamanho_de_posicao_bate_com_a_formula_na_mao():
    """
    Conta fechada, feita a mao:

        risco em dinheiro   = 10.000 x 1%     = 100
        distancia do stop   = 2 x 5.000       = 10.000
        tamanho             = 100 / 10.000    = 0,01
        stop                = 100.000 - 10.000 = 90.000
        alvo                = 100.000 + 3 x 5.000 = 115.000
        exposicao           = 0,01 x 100.000  = 1.000  (10% do capital, dentro do teto)
    """
    resultado = avaliar_risco(
        tese=tese(BUY), atr_14=5_000.0, preco_atual=100_000.0,
        posicao=EstadoDaPosicao(), capital_total=CAPITAL,
        parametros=ParametrosDeRisco(
            multiplicador_stop=2.0, multiplicador_take=3.0,
            risco_por_operacao=0.01, exposicao_maxima_pct=0.50,
        ),
    )

    assert resultado.aprovado is True
    assert resultado.acao_final == BUY
    assert perto(resultado.stop_loss, 90_000.0)
    assert perto(resultado.take_profit, 115_000.0)
    assert perto(resultado.tamanho_posicao, 0.01)
    assert resultado.override_do_llm is False

    # E a invariante que a formula existe pra garantir: se o stop for
    # atingido, a perda e exatamente o risco declarado.
    perda_no_stop = resultado.tamanho_posicao * (100_000.0 - resultado.stop_loss)
    assert perto(perda_no_stop, CAPITAL * 0.01)


def test_multiplicadores_sao_configuraveis():
    comum = dict(tese=tese(BUY), atr_14=5_000.0, preco_atual=100_000.0,
                 posicao=EstadoDaPosicao(), capital_total=CAPITAL)

    largo = avaliar_risco(**comum, parametros=ParametrosDeRisco(
        multiplicador_stop=4.0, multiplicador_take=6.0, exposicao_maxima_pct=1.0))
    assert perto(largo.stop_loss, 80_000.0)
    assert perto(largo.take_profit, 130_000.0)
    # Stop mais largo -> menos unidades para o mesmo risco em dinheiro.
    assert perto(largo.tamanho_posicao, 100.0 / 20_000.0)


def test_risco_por_operacao_e_configuravel():
    comum = dict(tese=tese(BUY), atr_14=5_000.0, preco_atual=100_000.0,
                 posicao=EstadoDaPosicao(), capital_total=CAPITAL)
    dobro = avaliar_risco(**comum, parametros=ParametrosDeRisco(
        risco_por_operacao=0.02, exposicao_maxima_pct=1.0))
    assert perto(dobro.tamanho_posicao, 0.02)


def test_exposicao_no_limite_bloqueia_com_motivo_claro():
    """
    Stop apertado (ATR pequeno) faz o tamanho por risco explodir em
    nocional. Com teto de 50%, tem que bloquear -- e dizer por que.

        distancia = 2 x 200 = 400
        tamanho   = 100 / 400 = 0,25
        exposicao = 0,25 x 100.000 = 25.000  (250% do capital!)
    """
    resultado = avaliar_risco(
        tese=tese(BUY), atr_14=200.0, preco_atual=100_000.0,
        posicao=EstadoDaPosicao(), capital_total=CAPITAL,
        parametros=ParametrosDeRisco(exposicao_maxima_pct=0.50),
    )

    assert resultado.aprovado is False
    assert resultado.acao_final == NO_TRADE
    assert "Exposicao" in resultado.motivo
    assert "teto" in resultado.motivo
    # O tamanho que teria sido exigido segue no resultado, pra auditoria.
    assert perto(resultado.tamanho_posicao, 0.25)


def test_exatamente_no_teto_de_exposicao_passa():
    """
    exposicao = tamanho x preco; teto = capital x pct.
    Escolhido pra bater exatamente em 5.000 = 50% de 10.000.
    """
    resultado = avaliar_risco(
        tese=tese(BUY), atr_14=1_000.0, preco_atual=100_000.0,
        posicao=EstadoDaPosicao(), capital_total=CAPITAL,
        parametros=ParametrosDeRisco(risco_por_operacao=0.01, exposicao_maxima_pct=0.50),
    )
    # distancia = 2.000; tamanho = 100/2.000 = 0,05; exposicao = 5.000 == teto
    assert perto(resultado.tamanho_posicao, 0.05)
    assert resultado.aprovado is True


def test_sem_atr_nao_opera():
    for atr in (None, 0.0, -5.0, float("nan")):
        resultado = avaliar_risco(
            tese=tese(BUY), atr_14=atr, preco_atual=100_000.0,
            posicao=EstadoDaPosicao(), capital_total=CAPITAL,
        )
        assert resultado.aprovado is False, f"atr={atr}"
        assert "ATR" in resultado.motivo


def test_volatilidade_maior_que_o_preco_bloqueia():
    """Stop calculado abaixo de zero nao e um stop."""
    resultado = avaliar_risco(
        tese=tese(BUY), atr_14=60_000.0, preco_atual=100_000.0,
        posicao=EstadoDaPosicao(), capital_total=CAPITAL,
    )
    assert resultado.aprovado is False
    assert "Stop calculado" in resultado.motivo


def test_capital_ou_preco_invalido_bloqueia():
    assert not avaliar_risco(tese(BUY), 5_000.0, 100_000.0,
                             EstadoDaPosicao(), 0.0).aprovado
    assert not avaliar_risco(tese(BUY), 5_000.0, 0.0,
                             EstadoDaPosicao(), CAPITAL).aprovado


# --------------------------------------------------------------------
# REGRAS 3, 4, 5 e as combinacoes restantes
# --------------------------------------------------------------------


def test_fechar_posicao_e_sempre_aprovado():
    posicao = EstadoDaPosicao(quantidade=0.1, preco_entrada=100_000.0,
                              stop_loss=90_000.0, take_profit=115_000.0)
    resultado = avaliar_risco(tese(SELL), 5_000.0, 100_000.0, posicao, CAPITAL)
    assert resultado.aprovado is True
    assert resultado.acao_final == SELL
    assert resultado.tamanho_posicao == 0.1
    assert resultado.override_do_llm is False


def test_hold_com_posicao_mantem_sem_ordem():
    posicao = EstadoDaPosicao(quantidade=0.1, preco_entrada=100_000.0, stop_loss=90_000.0)
    resultado = avaliar_risco(tese(HOLD), 5_000.0, 100_000.0, posicao, CAPITAL)
    assert resultado.acao_final == HOLD
    assert resultado.tamanho_posicao == 0.0
    assert resultado.override_do_llm is False


def test_no_trade_sem_posicao_nao_gera_ordem():
    resultado = avaliar_risco(tese(NO_TRADE), 5_000.0, 100_000.0, EstadoDaPosicao(), CAPITAL)
    assert resultado.acao_final == NO_TRADE
    assert resultado.tamanho_posicao == 0.0
    assert resultado.override_do_llm is False


def test_buy_com_posicao_aberta_nao_aumenta():
    posicao = EstadoDaPosicao(quantidade=0.1, preco_entrada=100_000.0, stop_loss=90_000.0)
    resultado = avaliar_risco(tese(BUY), 5_000.0, 100_000.0, posicao, CAPITAL)
    assert resultado.acao_final == HOLD
    assert resultado.aprovado is False
    assert resultado.override_do_llm is True


def test_sell_sem_posicao_nao_vira_venda_a_descoberto():
    """Principio 5: V1 e spot only."""
    resultado = avaliar_risco(tese(SELL), 5_000.0, 100_000.0, EstadoDaPosicao(), CAPITAL)
    assert resultado.acao_final == NO_TRADE
    assert resultado.aprovado is False
    assert resultado.override_do_llm is True
    assert "descoberto" in resultado.motivo


def test_hold_sem_posicao_vira_no_trade():
    resultado = avaliar_risco(tese(HOLD), 5_000.0, 100_000.0, EstadoDaPosicao(), CAPITAL)
    assert resultado.acao_final == NO_TRADE
    assert resultado.override_do_llm is True


def test_no_trade_com_posicao_mantem():
    posicao = EstadoDaPosicao(quantidade=0.1, preco_entrada=100_000.0, stop_loss=90_000.0)
    resultado = avaliar_risco(tese(NO_TRADE), 5_000.0, 100_000.0, posicao, CAPITAL)
    assert resultado.acao_final == HOLD
    assert resultado.override_do_llm is True


def test_todas_as_oito_combinacoes_tem_resposta():
    """Quatro direcoes x com/sem posicao -- nenhuma pode estourar."""
    com = EstadoDaPosicao(quantidade=0.1, preco_entrada=100_000.0,
                          stop_loss=90_000.0, take_profit=115_000.0)
    sem = EstadoDaPosicao()
    for direcao in (BUY, SELL, HOLD, NO_TRADE):
        for posicao in (com, sem):
            r = avaliar_risco(tese(direcao), 5_000.0, 100_000.0, posicao, CAPITAL)
            assert r.acao_final in (BUY, SELL, HOLD, NO_TRADE)
            assert isinstance(r.aprovado, bool)
            assert r.motivo


# --------------------------------------------------------------------
# Contrato de saida
# --------------------------------------------------------------------


def test_contrato_de_saida():
    resultado = avaliar_risco(tese(BUY), 5_000.0, 100_000.0, EstadoDaPosicao(), CAPITAL)
    d = resultado.como_dicionario()

    assert set(d) == {
        "aprovado", "acao_final", "motivo", "stop_loss", "take_profit",
        "tamanho_posicao", "override_do_llm", "direcao_do_llm",
    }
    json.dumps(d, allow_nan=False)


def test_a_direcao_original_do_llm_nunca_se_perde():
    """
    Sem isso o override some do registro: `risk_result` lido isolado
    mostraria so a acao final, sem sinal de que houve discordancia.
    """
    posicao = EstadoDaPosicao(quantidade=0.1, preco_entrada=100_000.0, stop_loss=96_000.0)
    d = avaliar_risco(tese(HOLD), 2_000.0, 95_000.0, posicao, CAPITAL).como_dicionario()

    assert d["direcao_do_llm"] == HOLD
    assert d["acao_final"] == SELL
    assert d["override_do_llm"] is True


def test_aceita_tese_como_objeto_dicionario_ou_string():
    class TeseFalsa:
        direction = BUY

    for entrada in (TeseFalsa(), {"direction": BUY}, BUY):
        r = avaliar_risco(entrada, 5_000.0, 100_000.0, EstadoDaPosicao(), CAPITAL)
        assert r.acao_final == BUY


def test_direcao_invalida_estoura():
    for invalida in ("COMPRAR", "buy", None, ""):
        try:
            avaliar_risco({"direction": invalida}, 5_000.0, 100_000.0,
                          EstadoDaPosicao(), CAPITAL)
        except ValueError:
            continue
        raise AssertionError(f"direcao {invalida!r} deveria ter estourado")


# --------------------------------------------------------------------
# A casca do portfolio -- falhar nao pode virar "sem posicao"
# --------------------------------------------------------------------


class SupabaseFalso:
    """
    Dublê minimo do cliente. `erro` faz a consulta estourar; `linhas`
    define o que ela devolve quando nao estoura.
    """

    def __init__(self, linhas=None, erro=None):
        self.linhas = linhas or []
        self.erro = erro
        self.colunas_pedidas = None

    def table(self, _nome):
        return self

    def select(self, colunas):
        self.colunas_pedidas = colunas
        if self.erro:
            raise self.erro
        return self

    def eq(self, *_a, **_k):
        return self

    def limit(self, *_a, **_k):
        return self

    def execute(self):
        if self.erro:
            raise self.erro
        return type("R", (), {"data": self.linhas})()


def test_leitura_pede_as_colunas_pelo_nome_e_nao_com_asterisco():
    """
    Regressao de um bug real, pego so ao testar contra o banco de
    verdade: com `select("*")` numa tabela sem as colunas de risco, a
    consulta tem SUCESSO e devolve a posicao sem stop nenhum. Uma posicao
    com stop lida como se nao tivesse faz a regra 1 nunca disparar --
    exatamente o contrario do que este modulo existe pra garantir.
    """
    falso = SupabaseFalso(linhas=[])
    buscar_posicao(falso, "BTCUSDT")

    assert falso.colunas_pedidas != "*"
    for coluna in COLUNAS_DE_RISCO:
        assert coluna in falso.colunas_pedidas


def test_falha_de_leitura_levanta_em_vez_de_devolver_posicao_vazia():
    falso = SupabaseFalso(erro=RuntimeError("conexao caiu"))
    try:
        buscar_posicao(falso, "BTCUSDT")
    except ErroDePortfolio:
        return
    raise AssertionError(
        "falha de leitura devolveu posicao em vez de levantar -- "
        "seria interpretada como 'estou de fora' e o stop deixaria de ser checado"
    )


def test_coluna_ausente_e_reconhecida_nos_dois_formatos_do_postgrest():
    """
    Erro real de leitura (Postgres) e de escrita (cache do PostgREST).
    Os dois textos vieram do banco de verdade.
    """
    leitura = "{'message': 'column portfolio.preco_entrada does not exist', 'code': '42703'}"
    escrita = ("{'message': \"Could not find the 'preco_entrada' column of 'portfolio' "
               "in the schema cache\", 'code': 'PGRST204'}")
    assert _e_coluna_ausente(leitura)
    assert _e_coluna_ausente(escrita)
    assert not _e_coluna_ausente("timeout de rede")


def test_ausencia_de_linha_e_sem_posicao_de_verdade():
    """Tabela sem linha para o par significa mesmo 'sem posicao' -- isso pode degradar."""
    posicao = buscar_posicao(SupabaseFalso(linhas=[]), "BTCUSDT")
    assert posicao.aberta is False
    assert posicao.stop_loss is None


def test_linha_existente_vira_estado_da_posicao():
    posicao = buscar_posicao(SupabaseFalso(linhas=[{
        "asset": "BTCUSDT", "quantity": 0.25, "preco_entrada": 100_000.0,
        "stop_loss": 96_000.0, "take_profit": 106_000.0,
    }]), "BTCUSDT")

    assert posicao.aberta is True
    assert perto(posicao.quantidade, 0.25)
    assert perto(posicao.stop_loss, 96_000.0)
    assert perto(posicao.take_profit, 106_000.0)


# --------------------------------------------------------------------
# Runner
# --------------------------------------------------------------------


def _rodar_tudo() -> int:
    testes = sorted(
        (nome, funcao)
        for nome, funcao in globals().items()
        if nome.startswith("test_") and callable(funcao)
    )
    falhas = []
    for nome, funcao in testes:
        try:
            funcao()
            print(f"  ok    {nome}")
        except AssertionError as erro:
            falhas.append(nome)
            print(f"  FALHA {nome}: {erro}")
    print(f"\n{len(testes) - len(falhas)}/{len(testes)} passaram")
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(_rodar_tudo())
