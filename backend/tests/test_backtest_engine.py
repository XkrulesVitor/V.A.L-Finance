"""
Conferencia do motor de backtest (passo 3) e das baselines (passo 4).

    python backend/tests/test_backtest_engine.py     # sem instalar nada extra
    pytest backend/tests                             # se pytest estiver disponivel

Este e o modulo onde bug e mais caro do projeto inteiro. Um motor de
backtest com vazamento de futuro nao quebra: ele mente, e mente pra
cima. Por isso a maior parte do que esta aqui nao testa "o numero saiu
certo", testa "o motor nao enxergou o que nao devia":

- `test_futuro_reescrito_nao_muda_o_passado` reescreve o historico
  depois de um ponto e exige que as decisoes anteriores saiam iguais;
- `test_estrategia_nunca_recebe_candle_do_futuro` espiona todo candle
  entregue e confere o timestamp;
- `test_buy_and_hold_bate_com_a_conta_fechada` compara com a formula
  fechada, que e a unica ancora externa que este motor tem.

Dados sinteticos, sem rede.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.engine import (  # noqa: E402
    BUY,
    HOLD,
    NO_TRADE,
    SELL,
    rodar_backtest,
)
from backtest.strategies import buy_and_hold, ema_crossover  # noqa: E402

UMA_HORA_MS = 60 * 60 * 1000
INICIO_MS = 1_700_000_000_000
CAPITAL = 10_000.0
TAXA = 0.001


# --------------------------------------------------------------------
# Apoio
# --------------------------------------------------------------------


def montar_candles(precos, aberturas=None, duracao_ms=UMA_HORA_MS):
    """
    Candles sinteticos. Por padrao abertura == fechamento, o que torna o
    preco de preenchimento previsivel na conta a mao; `aberturas` permite
    descolar os dois quando o teste precisa distinguir um do outro.
    """
    candles = []
    for i, fechamento in enumerate(precos):
        abertura = aberturas[i] if aberturas is not None else fechamento
        candles.append({
            "abertura_em": INICIO_MS + i * duracao_ms,
            "abertura": float(abertura),
            "maxima": float(max(abertura, fechamento)) * 1.001,
            "minima": float(min(abertura, fechamento)) * 0.999,
            "fechamento": float(fechamento),
            "volume": 100.0,
        })
    return candles


def serie_de_alta(quantidade=400, inicial=50_000.0, passo=0.001):
    return [inicial * (1 + passo) ** i * (1 + 0.002 * ((i % 11) - 5)) for i in range(quantidade)]


def estrategia_roteirizada(roteiro):
    """Devolve a decisao marcada pro indice; HOLD no resto."""
    def estrategia(contexto):
        return roteiro.get(contexto.indice, HOLD)
    estrategia.__name__ = "roteirizada"
    return estrategia


def perto(obtido, esperado, tolerancia=1e-9):
    if esperado == 0:
        return abs(obtido) < 1e-9
    return abs(obtido - esperado) / abs(esperado) < tolerancia


# --------------------------------------------------------------------
# A ancora externa: buy and hold tem resultado fechado
# --------------------------------------------------------------------


def test_buy_and_hold_bate_com_a_conta_fechada():
    """
    A verificacao pedida no passo 4, e a unica que compara o motor com
    algo de fora dele.

    A entrada acontece na ABERTURA do candle 1 (a decisao nasceu no
    fechamento do candle 0) e a saida no FECHAMENTO do ultimo candle,
    na liquidacao forcada. Entre os dois, duas taxas -- uma por ponta:

        saldo_final = capital * (fechamento_final / abertura_1) * (1 - taxa)^2
    """
    precos = serie_de_alta()
    candles = montar_candles(precos)

    resultado = rodar_backtest(
        candles, buy_and_hold, capital_inicial=CAPITAL, taxa_por_operacao=TAXA
    )

    preco_entrada = candles[1]["abertura"]
    preco_saida = candles[-1]["fechamento"]
    esperado = CAPITAL * (preco_saida / preco_entrada) * (1 - TAXA) ** 2

    assert perto(resultado.metricas["saldo_final"], round(esperado, 2), 1e-6), (
        f"saldo {resultado.metricas['saldo_final']} != esperado {esperado}"
    )
    assert resultado.metricas["numero_operacoes"] == 2
    assert resultado.metricas["numero_trades"] == 1


def test_buy_and_hold_sem_taxa_e_a_variacao_pura_do_preco():
    """Com taxa zero, o retorno tem que ser exatamente a variacao do preco."""
    candles = montar_candles(serie_de_alta())
    resultado = rodar_backtest(
        candles, buy_and_hold, capital_inicial=CAPITAL, taxa_por_operacao=0.0
    )

    variacao = candles[-1]["fechamento"] / candles[1]["abertura"] - 1
    assert perto(resultado.metricas["retorno_total_pct"], round(variacao * 100, 2), 1e-4)


def test_a_taxa_sai_do_resultado_e_nao_do_nada():
    """Mesma serie, taxa maior: o saldo final tem que cair na proporcao das duas pontas."""
    candles = montar_candles(serie_de_alta())
    sem_taxa = rodar_backtest(candles, buy_and_hold, capital_inicial=CAPITAL,
                              taxa_por_operacao=0.0).metricas["saldo_final"]
    com_taxa = rodar_backtest(candles, buy_and_hold, capital_inicial=CAPITAL,
                              taxa_por_operacao=TAXA).metricas["saldo_final"]

    assert perto(com_taxa, round(sem_taxa * (1 - TAXA) ** 2, 2), 1e-6)


# --------------------------------------------------------------------
# Ausencia de look-ahead
# --------------------------------------------------------------------


def test_futuro_reescrito_nao_muda_o_passado():
    """
    O teste mais forte que existe pra vazamento de futuro.

    Roda a mesma estrategia em duas series identicas ate o candle K e
    completamente diferentes depois dele. Se qualquer decisao anterior a
    K mudar, alguma coisa no motor leu adiante -- nao ha outra explicacao.
    """
    corte = 200
    precos = serie_de_alta(quantidade=400)
    candles_originais = montar_candles(precos)

    # Depois do corte, um mundo diferente: colapso em vez de alta.
    precos_alterados = list(precos[:corte]) + [
        precos[corte - 1] * (0.97 ** (i + 1)) for i in range(400 - corte)
    ]
    candles_alterados = montar_candles(precos_alterados)

    decisoes_originais, espia_original = espiar(ema_crossover)
    decisoes_alteradas, espia_alterada = espiar(ema_crossover)

    rodar_backtest(candles_originais, espia_original, capital_inicial=CAPITAL)
    rodar_backtest(candles_alterados, espia_alterada, capital_inicial=CAPITAL)

    assert decisoes_originais[:corte] == decisoes_alteradas[:corte], (
        "decisoes anteriores ao corte mudaram quando so o futuro mudou -- "
        "ha vazamento de dado futuro no motor"
    )
    # Sanidade do proprio teste: depois do corte elas PRECISAM divergir,
    # senao a serie alterada nao alterou nada e o teste nao provou nada.
    assert decisoes_originais[corte:] != decisoes_alteradas[corte:]


def espiar(estrategia):
    """Embrulha uma estrategia guardando o que ela decidiu em cada passo."""
    decisoes = []

    def espia(contexto):
        decisao = estrategia(contexto)
        decisoes.append(decisao)
        return decisao

    espia.__name__ = getattr(estrategia, "__name__", "espia")
    return decisoes, espia


def test_estrategia_nunca_recebe_candle_do_futuro():
    """Todo candle entregue tem que ser anterior ou igual ao que esta sendo avaliado."""
    candles = montar_candles(serie_de_alta())
    violacoes = []

    def fiscal(contexto):
        limite = contexto.candle_atual["abertura_em"]
        if any(candle["abertura_em"] > limite for candle in contexto.candles):
            violacoes.append(contexto.indice)
        # O candle avaliado tambem tem que ser o do proprio indice.
        if limite != candles[contexto.indice]["abertura_em"]:
            violacoes.append(contexto.indice)
        return NO_TRADE

    rodar_backtest(candles, fiscal, capital_inicial=CAPITAL)
    assert not violacoes, f"candle futuro entregue nos indices {violacoes[:5]}"


def test_decisao_do_ultimo_candle_nao_e_pedida():
    """
    Nao existe abertura seguinte pra preencher a decisao do ultimo candle,
    entao a estrategia nem chega a ser consultada la.
    """
    candles = montar_candles(serie_de_alta(quantidade=50))
    vistos = []

    def fiscal(contexto):
        vistos.append(contexto.indice)
        return NO_TRADE

    rodar_backtest(candles, fiscal, capital_inicial=CAPITAL)
    assert vistos == list(range(len(candles) - 1))


# --------------------------------------------------------------------
# Execucao e carteira
# --------------------------------------------------------------------


def test_execucao_acontece_na_abertura_do_candle_seguinte():
    """
    Fechamentos e aberturas descolados de proposito: se o motor preencher
    no fechamento que gerou o sinal (100) em vez da abertura seguinte
    (150), este teste pega.
    """
    precos = [100.0, 100.0, 100.0, 100.0]
    aberturas = [100.0, 150.0, 150.0, 150.0]
    candles = montar_candles(precos, aberturas=aberturas)

    resultado = rodar_backtest(
        candles, estrategia_roteirizada({0: BUY}),
        capital_inicial=CAPITAL, taxa_por_operacao=0.0,
    )

    compra = resultado.operacoes[0]
    assert compra["lado"] == BUY
    assert perto(compra["preco"], 150.0)
    assert perto(compra["quantidade"], CAPITAL / 150.0)


def test_ida_e_volta_no_mesmo_preco_perde_exatamente_as_duas_taxas():
    candles = montar_candles([100.0] * 8)
    resultado = rodar_backtest(
        candles, estrategia_roteirizada({0: BUY, 3: SELL}),
        capital_inicial=CAPITAL, taxa_por_operacao=TAXA,
    )

    assert perto(resultado.metricas["saldo_final"], round(CAPITAL * (1 - TAXA) ** 2, 2), 1e-6)
    assert resultado.metricas["numero_operacoes"] == 2


def test_hold_e_no_trade_nao_operam():
    candles = montar_candles(serie_de_alta(quantidade=60))

    for decisao in (HOLD, NO_TRADE):
        resultado = rodar_backtest(
            candles, lambda contexto, d=decisao: d, capital_inicial=CAPITAL,
        )
        assert resultado.metricas["numero_operacoes"] == 0
        assert resultado.metricas["saldo_final"] == CAPITAL


def test_sell_sem_posicao_nao_faz_nada():
    """V1 e spot only: SELL fecha posicao, nunca abre uma vendida (principio 5)."""
    candles = montar_candles(serie_de_alta(quantidade=60))
    resultado = rodar_backtest(
        candles, lambda contexto: SELL, capital_inicial=CAPITAL,
    )
    assert resultado.metricas["numero_operacoes"] == 0
    assert resultado.metricas["saldo_final"] == CAPITAL


def test_liquidacao_final_fecha_a_posicao_e_paga_taxa():
    candles = montar_candles([100.0] * 8)
    resultado = rodar_backtest(
        candles, estrategia_roteirizada({0: BUY}),
        capital_inicial=CAPITAL, taxa_por_operacao=TAXA,
    )

    ultima = resultado.operacoes[-1]
    assert ultima["lado"] == SELL
    assert ultima["motivo"] == "liquidacao_final"
    assert perto(resultado.curva_de_capital[-1]["patrimonio"], resultado.metricas["saldo_final"])


def test_taxa_de_acerto_conta_ida_e_volta():
    """Dois trades montados na mao: um ganhando, um perdendo -> 50%."""
    candles = montar_candles([100.0, 100.0, 100.0, 200.0, 100.0, 100.0, 50.0, 50.0])
    resultado = rodar_backtest(
        candles, estrategia_roteirizada({0: BUY, 2: SELL, 3: BUY, 5: SELL}),
        capital_inicial=CAPITAL, taxa_por_operacao=0.0,
    )

    assert resultado.metricas["numero_trades"] == 2
    assert resultado.metricas["numero_operacoes"] == 4
    assert perto(resultado.metricas["taxa_acerto_pct"], 50.0)


# --------------------------------------------------------------------
# Janela, metricas e validacoes
# --------------------------------------------------------------------


def test_janela_maxima_limita_o_que_a_estrategia_ve():
    """
    Paridade com a producao: o cron job pede um numero fixo de candles por
    ciclo, entao o backtest nao pode mostrar mais do que isso.
    """
    candles = montar_candles(serie_de_alta(quantidade=300))
    tamanhos = []

    def fiscal(contexto):
        tamanhos.append(len(contexto.candles))
        return NO_TRADE

    rodar_backtest(candles, fiscal, capital_inicial=CAPITAL, janela_maxima=50)
    assert max(tamanhos) == 50
    assert tamanhos[0] == 1  # no primeiro candle so existe um candle de historico


def test_curva_tem_um_ponto_por_candle():
    candles = montar_candles(serie_de_alta(quantidade=120))
    resultado = rodar_backtest(candles, buy_and_hold, capital_inicial=CAPITAL)
    assert len(resultado.curva_de_capital) == len(candles)


def test_max_drawdown_nunca_e_positivo():
    for precos in (serie_de_alta(), list(reversed(serie_de_alta()))):
        resultado = rodar_backtest(montar_candles(precos), buy_and_hold, capital_inicial=CAPITAL)
        assert resultado.metricas["max_drawdown_pct"] <= 0


def test_decisao_invalida_estoura_em_vez_de_virar_hold():
    candles = montar_candles(serie_de_alta(quantidade=30))
    for invalida in ("buy", None, "COMPRAR"):
        try:
            rodar_backtest(candles, lambda contexto, d=invalida: d, capital_inicial=CAPITAL)
        except ValueError:
            continue
        raise AssertionError(f"decisao {invalida!r} deveria ter estourado")


def test_candles_fora_de_ordem_sao_ordenados():
    candles = montar_candles(serie_de_alta(quantidade=120))
    embaralhados = candles[60:] + candles[:60]

    a = rodar_backtest(candles, buy_and_hold, capital_inicial=CAPITAL)
    b = rodar_backtest(embaralhados, buy_and_hold, capital_inicial=CAPITAL)
    assert a.metricas == b.metricas


def test_historico_curto_demais_estoura():
    try:
        rodar_backtest(montar_candles([100.0]), buy_and_hold)
    except ValueError:
        return
    raise AssertionError("um candle so deveria estourar")


def test_resultado_e_json_valido():
    """Vai pro campo `metrics` (jsonb) da tabela backtest_runs."""
    resultado = rodar_backtest(montar_candles(serie_de_alta()), buy_and_hold,
                               capital_inicial=CAPITAL)
    json.dumps(resultado.metricas, allow_nan=False)
    json.dumps(resultado.parametros, allow_nan=False)
    json.dumps(resultado.periodo, allow_nan=False)


# --------------------------------------------------------------------
# Baselines
# --------------------------------------------------------------------


def test_ema_crossover_nao_opera_sem_indicador():
    """Com menos de 50 candles a EMA de 50 nao existe -- e sem sinal nao ha aposta."""
    candles = montar_candles(serie_de_alta(quantidade=40))
    resultado = rodar_backtest(candles, ema_crossover, capital_inicial=CAPITAL)
    assert resultado.metricas["numero_operacoes"] == 0


def test_ema_crossover_compra_em_alta_e_sai_em_queda():
    """
    Alta longa e sustentada seguida de queda longa: a estrategia tem que
    entrar em algum ponto da subida e ter saido antes do fim da descida.
    """
    subida = [100.0 * (1.01 ** i) for i in range(150)]
    descida = [subida[-1] * (0.99 ** i) for i in range(1, 150)]
    candles = montar_candles(subida + descida)

    resultado = rodar_backtest(candles, ema_crossover, capital_inicial=CAPITAL,
                               taxa_por_operacao=0.0)
    lados = [operacao["lado"] for operacao in resultado.operacoes]

    assert lados[0] == BUY
    assert SELL in lados
    assert not any(operacao["motivo"] == "liquidacao_final" for operacao in resultado.operacoes), (
        "deveria ter saido sozinha na queda, nao ficado presa ate a liquidacao"
    )
    # E, tendo pego a subida e escapado da descida, tem que bater o buy and hold.
    referencia = rodar_backtest(candles, buy_and_hold, capital_inicial=CAPITAL,
                                taxa_por_operacao=0.0)
    assert resultado.metricas["retorno_total_pct"] > referencia.metricas["retorno_total_pct"]


# --------------------------------------------------------------------
# Runner pra quem nao tem pytest
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
        except Exception as erro:  # noqa: BLE001
            # Um teste que estoura com KeyError/TypeError e falha igual --
            # e capturar so AssertionError fazia o arquivo inteiro morrer
            # ali, escondendo o resultado de todos os testes seguintes.
            falhas.append(nome)
            print(f"  ERRO  {nome}: {type(erro).__name__}: {erro}")

    print(f"\n{len(testes) - len(falhas)}/{len(testes)} passaram")
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(_rodar_tudo())
