"""
Conferencia da estrategia hibrida (passo 7).

    python backend/tests/test_hybrid_strategy.py
    pytest backend/tests

Sem rede: o analista e injetado. Nenhum teste aqui gasta chamada do
Gemini -- verificar ordem de execucao e escolha de multiplicador com
cota de API seria desperdicio.

Os dois testes que mais importam:

- `test_stop_rompido_executa_no_candle_e_nao_espera_a_cadencia`
  reproduz o bug que a secao 15 registrou como risco concreto antes de
  existir codigo: um stop rompido 2h depois da ultima consulta tem que
  sair NA HORA, e nao daqui a 4h quando o cerebro for consultado de
  novo.
- `test_horizonte_escolhe_o_multiplicador` confirma que o `horizon`
  devolvido pelo cerebro -- que ate o passo 6 ninguem consumia --
  realmente chega em `avaliar_risco()` e muda a largura do stop.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.engine import BUY, HOLD, NO_TRADE, SELL, rodar_backtest  # noqa: E402
from brain.hybrid_strategy import (  # noqa: E402
    MULTIPLICADORES_POR_HORIZONTE,
    EstrategiaHibrida,
    parametros_para_horizonte,
)
from brain.llm_analyst import TeseDeOperacao  # noqa: E402
from features.feature_engine import calcular_features  # noqa: E402
from risk.risk_engine import ParametrosDeRisco  # noqa: E402

UMA_HORA_MS = 60 * 60 * 1000
INICIO_MS = 1_700_000_000_000
CAPITAL = 10_000.0

# Amplitude de 2% do preco para que o ATR fique grande o bastante para a
# entrada caber no teto de exposicao. Com ATR menor que ~1% do preco, o
# Risk Engine bloqueia por exposicao (secao 11) e o teste nao chegaria a
# testar o que quer.
PRECO = 100_000.0
AMPLITUDE = 2_000.0


def candle(i, fechamento=PRECO, amplitude=AMPLITUDE):
    return {
        "abertura_em": INICIO_MS + i * UMA_HORA_MS,
        "abertura": fechamento,
        "maxima": fechamento + amplitude / 2,
        "minima": fechamento - amplitude / 2,
        "fechamento": fechamento,
        "volume": 100.0,
        "fechamento_em": INICIO_MS + (i + 1) * UMA_HORA_MS - 1,
    }


def serie(quantidade, fechamentos=None):
    """Serie plana, com fechamentos pontuais sobrescritos por indice."""
    fechamentos = fechamentos or {}
    return [candle(i, fechamentos.get(i, PRECO)) for i in range(quantidade)]


class AnalistaFalso:
    def __init__(self, direcao=BUY, horizonte="curto", teses=None):
        self.chamadas = 0
        self.indices_chamados = []
        self._teses = teses
        self._padrao = TeseDeOperacao(
            direction=direcao, horizon=horizonte, confidence=0.7, reasoning="teste"
        )

    def analisar(self, features, simbolo, posicao_aberta=False, preco_atual=None):
        self.chamadas += 1
        if self._teses:
            return self._teses[min(self.chamadas - 1, len(self._teses) - 1)]
        return self._padrao


def perto(a, b, tol=1e-6):
    return a is not None and abs(a - b) <= tol


def rodar(candles, estrategia):
    """Roda o backtest guardando a decisao de cada candle."""
    decisoes = []
    original = estrategia.__call__

    class Espia:
        __name__ = "hibrida_espiada"

        def __call__(self, contexto):
            decisao = original(contexto)
            decisoes.append((contexto.indice, decisao))
            return decisao

    resultado = rodar_backtest(
        candles, Espia(), capital_inicial=CAPITAL, taxa_por_operacao=0.0
    )
    return resultado, decisoes


# --------------------------------------------------------------------
# O bug que nao e negociavel
# --------------------------------------------------------------------


def test_stop_rompido_executa_no_candle_e_nao_espera_a_cadencia():
    """
    Consulta ao cerebro no candle 18 (primeiro com ATR disponivel) manda
    BUY. A posicao abre no 19. No candle 21 -- DUAS horas depois da
    consulta, quatro horas antes da proxima -- o preco despenca abaixo do
    stop.

    O SELL tem que sair no proprio candle 21. Se sair no 24, os dois
    relogios foram acoplados e a protecao virou enfeite.
    """
    candles = serie(30, fechamentos={21: 90_000.0, 22: 90_000.0, 23: 90_000.0})
    estrategia = EstrategiaHibrida(AnalistaFalso(BUY, "curto"), intervalo_ms=6 * UMA_HORA_MS)
    _, decisoes = rodar(candles, estrategia)

    por_indice = dict(decisoes)
    assert por_indice[18] == BUY, f"esperava BUY no 18, veio {por_indice[18]}"
    assert por_indice[21] == SELL, (
        f"stop rompido no candle 21 devolveu {por_indice[21]} -- "
        f"a regra 1 esta presa na cadencia de 6h"
    )
    # 19 e 20 sao candles de espera: posicao aberta, nada rompido.
    assert por_indice[19] == HOLD
    assert por_indice[20] == HOLD
    assert estrategia.overrides_de_risco >= 1


def test_a_saida_forcada_nao_gasta_chamada_de_api():
    """A checagem de stop e barata de proposito -- nao pode chamar o modelo."""
    candles = serie(30, fechamentos={21: 90_000.0, 22: 90_000.0})
    analista = AnalistaFalso(BUY, "curto")
    estrategia = EstrategiaHibrida(analista, intervalo_ms=6 * UMA_HORA_MS)

    chamadas_por_indice = []
    original = estrategia.__call__

    class Espia:
        __name__ = "espia"

        def __call__(self, contexto):
            antes = analista.chamadas
            decisao = original(contexto)
            chamadas_por_indice.append((contexto.indice, decisao, analista.chamadas - antes))
            return decisao

    rodar_backtest(candles, Espia(), capital_inicial=CAPITAL, taxa_por_operacao=0.0)

    no_21 = [linha for linha in chamadas_por_indice if linha[0] == 21][0]
    assert no_21[1] == SELL
    assert no_21[2] == 0, "a saida forcada consultou o cerebro -- nao deveria"


def test_regra_1_roda_em_todo_candle_com_posicao_aberta():
    """
    Varre todos os candles possiveis de ruptura e confirma que o SELL sai
    sempre no proprio candle, nunca no seguinte multiplo de 6h.
    """
    for indice_da_queda in (20, 21, 22, 23):
        candles = serie(
            32, fechamentos={i: 90_000.0 for i in range(indice_da_queda, 32)}
        )
        estrategia = EstrategiaHibrida(
            AnalistaFalso(BUY, "curto"), intervalo_ms=6 * UMA_HORA_MS
        )
        _, decisoes = rodar(candles, estrategia)
        por_indice = dict(decisoes)
        assert por_indice[indice_da_queda] == SELL, (
            f"queda no candle {indice_da_queda} nao saiu no mesmo candle: "
            f"{por_indice[indice_da_queda]}"
        )


def test_take_profit_tambem_dispara_fora_da_cadencia():
    candles = serie(30, fechamentos={i: 130_000.0 for i in range(21, 30)})
    estrategia = EstrategiaHibrida(AnalistaFalso(BUY, "curto"), intervalo_ms=6 * UMA_HORA_MS)
    _, decisoes = rodar(candles, estrategia)
    assert dict(decisoes)[21] == SELL


# --------------------------------------------------------------------
# Horizonte -> multiplicador
# --------------------------------------------------------------------


def test_parametros_para_horizonte_mapeia_a_tabela_oficial():
    for horizonte, (stop, take) in MULTIPLICADORES_POR_HORIZONTE.items():
        p = parametros_para_horizonte(horizonte)
        assert p.multiplicador_stop == stop
        assert p.multiplicador_take == take

    assert parametros_para_horizonte("curto").multiplicador_stop == 2.0
    assert parametros_para_horizonte("medio").multiplicador_stop == 4.0
    assert parametros_para_horizonte("longo").multiplicador_stop == 8.0


def test_horizonte_desconhecido_cai_no_mais_conservador():
    p = parametros_para_horizonte("inventado")
    assert p.multiplicador_stop == MULTIPLICADORES_POR_HORIZONTE["curto"][0]


def test_parametros_por_horizonte_preservam_risco_e_teto():
    base = ParametrosDeRisco(risco_por_operacao=0.005, exposicao_maxima_pct=0.33)
    p = parametros_para_horizonte("longo", base)
    assert p.risco_por_operacao == 0.005
    assert p.exposicao_maxima_pct == 0.33
    assert p.multiplicador_stop == 8.0


def test_horizonte_escolhe_o_multiplicador():
    """
    Ponta a ponta: o `horizon` da tese muda o stop que a estrategia
    guarda. Tres casos, um por horizonte.

    O ATR e o mesmo nos tres (mesma serie), entao a distancia do stop
    tem que ficar na proporcao exata dos multiplicadores: medio = 2x
    curto, longo = 4x curto.
    """
    distancias = {}
    for horizonte in ("curto", "medio", "longo"):
        candles = serie(30)
        estrategia = EstrategiaHibrida(
            AnalistaFalso(BUY, horizonte),
            intervalo_ms=6 * UMA_HORA_MS,
            # Teto alto para que os tres passem e o teste meca o stop, e
            # nao o bloqueio por exposicao.
            parametros_base=ParametrosDeRisco(exposicao_maxima_pct=10.0),
        )
        rodar(candles, estrategia)
        assert estrategia.niveis is not None, f"{horizonte}: nenhuma posicao aberta"
        stop, take = estrategia.niveis
        distancias[horizonte] = PRECO - stop
        # O alvo segue a mesma proporcao (3/2 da distancia do stop).
        assert perto(take - PRECO, (PRECO - stop) * 1.5, tol=1e-3)

    assert perto(distancias["medio"], distancias["curto"] * 2, tol=1e-3)
    assert perto(distancias["longo"], distancias["curto"] * 4, tol=1e-3)


def test_stop_mais_largo_permite_posicao_menor_e_passa_no_teto():
    """
    O motivo de a tabela existir: com o mesmo teto de exposicao, o
    horizonte longo entra onde o curto e bloqueado.

    ATR pequeno (0,4% do preco) -- o caso que o passo 6 mediu como
    bloqueado em 48 de 50 amostras.
    """
    candles = serie(30)
    for i, c in enumerate(candles):  # amplitude estreita: ATR ~ 0,4% do preco
        c["maxima"] = PRECO + 200.0
        c["minima"] = PRECO - 200.0

    resultados = {}
    for horizonte in ("curto", "longo"):
        estrategia = EstrategiaHibrida(
            AnalistaFalso(BUY, horizonte), intervalo_ms=6 * UMA_HORA_MS
        )
        resultado, _ = rodar(candles, estrategia)
        resultados[horizonte] = resultado.metricas["numero_operacoes"]

    assert resultados["curto"] == 0, "stop apertado deveria estourar o teto de exposicao"
    assert resultados["longo"] > 0, "stop largo deveria caber no teto"


# --------------------------------------------------------------------
# Cadencia e estado
# --------------------------------------------------------------------


def test_entre_consultas_nao_gasta_api():
    candles = serie(49)
    analista = AnalistaFalso(NO_TRADE, "curto")
    estrategia = EstrategiaHibrida(analista, intervalo_ms=6 * UMA_HORA_MS)
    rodar(candles, estrategia)

    esperado = len([i for i in range(len(candles) - 1) if i % 6 == 0])
    assert analista.chamadas == esperado == 8
    assert estrategia.consultas == 8


def test_sem_posicao_e_sem_consulta_e_no_trade():
    candles = serie(13)
    estrategia = EstrategiaHibrida(AnalistaFalso(NO_TRADE), intervalo_ms=6 * UMA_HORA_MS)
    _, decisoes = rodar(candles, estrategia)
    por_indice = dict(decisoes)
    assert all(por_indice[i] == NO_TRADE for i in range(1, 6))


def test_niveis_sao_limpos_quando_a_posicao_fecha():
    """
    Depois do stop, sem posicao: nao pode sobrar nivel pendurado, que
    dispararia sozinho numa entrada futura contra um numero velho.

    O analista para de pedir BUY depois da primeira entrada, senao a
    estrategia reabriria posicao no candle 24 e o teste mediria os
    niveis da posicao NOVA em vez da limpeza da antiga.
    """
    compra = TeseDeOperacao(direction=BUY, horizon="curto", confidence=0.7, reasoning="x")
    fora = TeseDeOperacao(direction=NO_TRADE, horizon="curto", confidence=0.3, reasoning="x")
    candles = serie(30, fechamentos={i: 90_000.0 for i in range(21, 30)})

    estrategia = EstrategiaHibrida(
        AnalistaFalso(teses=[compra] * 4 + [fora] * 10), intervalo_ms=6 * UMA_HORA_MS
    )

    niveis_por_indice = {}
    original = estrategia.__call__

    class Espia:
        __name__ = "espia"

        def __call__(self, contexto):
            decisao = original(contexto)
            niveis_por_indice[contexto.indice] = estrategia.niveis
            return decisao

    rodar_backtest(candles, Espia(), capital_inicial=CAPITAL, taxa_por_operacao=0.0)

    assert niveis_por_indice[20] is not None, "posicao aberta deveria ter niveis"
    assert niveis_por_indice[21] is None, "o SELL forcado deveria limpar os niveis"
    for indice in range(22, 29):
        assert niveis_por_indice[indice] is None, f"nivel pendurado no candle {indice}"
    assert estrategia.niveis is None


def test_rodadas_nao_compartilham_estado():
    candles = serie(30)
    a = EstrategiaHibrida(AnalistaFalso(BUY, "curto"), intervalo_ms=6 * UMA_HORA_MS)
    b = EstrategiaHibrida(AnalistaFalso(BUY, "curto"), intervalo_ms=6 * UMA_HORA_MS)
    rodar(candles, a)
    rodar(candles, b)
    assert a.consultas == b.consultas
    assert a.niveis == b.niveis


def test_falha_do_modelo_interrompe_por_padrao():
    class Quebrado:
        chamadas = 0

        def analisar(self, **kwargs):
            raise RuntimeError("429 RESOURCE_EXHAUSTED")

    try:
        rodar(serie(20), EstrategiaHibrida(Quebrado(), intervalo_ms=6 * UMA_HORA_MS))
    except RuntimeError:
        return
    raise AssertionError("falha do modelo deveria ter interrompido a rodada")


def test_auditoria_conta_consultas_e_bloqueios():
    candles = serie(30)
    for i, c in enumerate(candles):  # ATR estreito -> bloqueio por exposicao
        c["maxima"] = PRECO + 200.0
        c["minima"] = PRECO - 200.0

    estrategia = EstrategiaHibrida(AnalistaFalso(BUY, "curto"), intervalo_ms=6 * UMA_HORA_MS)
    rodar(candles, estrategia)
    resumo = estrategia.resumo_de_auditoria()

    assert resumo["consultas_ao_cerebro"] > 0
    assert resumo["bloqueios_de_risco"] > 0
    assert resumo["direcoes_do_llm"].get(BUY, 0) > 0
    json.dumps(resumo, allow_nan=False)


def test_e_uma_estrategia_valida_para_o_motor():
    """Mesma assinatura das baselines -- o motor nao pode notar diferenca."""
    candles = serie(30)
    estrategia = EstrategiaHibrida(AnalistaFalso(BUY, "medio"), intervalo_ms=6 * UMA_HORA_MS)
    resultado = rodar_backtest(
        candles, estrategia, capital_inicial=CAPITAL, taxa_por_operacao=0.001
    )
    for chave in ("retorno_total_pct", "cagr_pct", "sharpe", "max_drawdown_pct",
                  "taxa_acerto_pct", "numero_operacoes", "saldo_final"):
        assert chave in resultado.metricas
    json.dumps(resultado.metricas, allow_nan=False)


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
