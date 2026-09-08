"""
Conferencia do cerebro (passo 5): cadencia, filtro de candle fechado e
contrato de saida.

    python backend/tests/test_brain.py
    pytest backend/tests

NENHUM teste aqui chama o Gemini. O analista e injetavel justamente pra
isso: cadencia, prompt, validacao e tratamento de erro sao testaveis com
um dublê, e gastar cota de API pra verificar logica de calendario seria
desperdicio. A verificacao contra o modelo de verdade e outra coisa, e
mora em `backend/brain/validar_ao_vivo.py`.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.engine import BUY, HOLD, NO_TRADE, SELL, rodar_backtest  # noqa: E402
from brain.cadencia import (  # noqa: E402
    INTERVALO_PADRAO_MS,
    ControleDeCadencia,
    decisao_de_espera,
    deve_consultar,
)
from brain.llm_analyst import (  # noqa: E402
    AnalistaLLM,
    ErroDoCerebro,
    TeseDeOperacao,
    montar_prompt,
)
from brain.strategy import criar_estrategia_do_cerebro  # noqa: E402
from features.candles import somente_fechados  # noqa: E402
from features.feature_engine import calcular_features  # noqa: E402

UMA_HORA_MS = 60 * 60 * 1000
INICIO_MS = 1_700_000_000_000


# --------------------------------------------------------------------
# Apoio
# --------------------------------------------------------------------


def montar_candles(quantidade, preco=100_000.0, volume=100.0, duracao_ms=UMA_HORA_MS):
    return [
        {
            "abertura_em": INICIO_MS + i * duracao_ms,
            "abertura": preco,
            "maxima": preco * 1.005,
            "minima": preco * 0.995,
            "fechamento": preco * (1 + 0.001 * ((i % 9) - 4)),
            "volume": volume,
            "fechamento_em": INICIO_MS + (i + 1) * duracao_ms - 1,
        }
        for i in range(quantidade)
    ]


TESE_PADRAO = TeseDeOperacao(
    direction=NO_TRADE, horizon="curto", confidence=0.4, reasoning="sinal fraco"
)


class AnalistaFalso:
    """Conta chamadas e registra o que recebeu, sem tocar em rede."""

    def __init__(self, teses=None):
        self.chamadas = 0
        self.recebidos = []
        self._teses = list(teses) if teses else None

    def analisar(self, features, simbolo, posicao_aberta=False, preco_atual=None):
        self.recebidos.append({
            "features": features, "simbolo": simbolo,
            "posicao_aberta": posicao_aberta, "preco_atual": preco_atual,
        })
        self.chamadas += 1
        if self._teses:
            return self._teses[(self.chamadas - 1) % len(self._teses)]
        return TESE_PADRAO


class AnalistaQuebrado:
    def __init__(self):
        self.chamadas = 0

    def analisar(self, **kwargs):
        self.chamadas += 1
        raise ErroDoCerebro("limite de requisicao estourado")


class RespostaFalsa:
    def __init__(self, parsed=None, text=None):
        self.parsed = parsed
        self.text = text


class ClienteFalso:
    """Dublê do google-genai: registra a chamada e devolve o que mandarem."""

    def __init__(self, resposta):
        self.chamadas = []
        resposta_alvo = resposta

        class Modelos:
            def generate_content(_self, *, model, contents, config):
                self.chamadas.append({"model": model, "contents": contents, "config": config})
                return resposta_alvo

        self.models = Modelos()


def perto(a, b, tol=1e-9):
    return abs(a - b) <= tol


# --------------------------------------------------------------------
# Cadencia -- a regra pura
# --------------------------------------------------------------------


def test_primeira_consulta_sempre_acontece():
    assert deve_consultar(INICIO_MS, None) is True


def test_cadencia_respeita_a_fronteira_exata():
    seis_horas = 6 * UMA_HORA_MS
    assert deve_consultar(INICIO_MS + seis_horas - 1, INICIO_MS, seis_horas) is False
    assert deve_consultar(INICIO_MS + seis_horas, INICIO_MS, seis_horas) is True
    assert deve_consultar(INICIO_MS + seis_horas + 1, INICIO_MS, seis_horas) is True


def test_intervalo_padrao_e_de_seis_horas():
    assert INTERVALO_PADRAO_MS == 6 * UMA_HORA_MS


def test_decisao_de_espera_mantem_o_que_estava_valendo():
    assert decisao_de_espera(posicao_aberta=True) == HOLD
    assert decisao_de_espera(posicao_aberta=False) == NO_TRADE


def test_controle_guarda_estado():
    controle = ControleDeCadencia(intervalo_ms=6 * UMA_HORA_MS)
    assert controle.deve_consultar(INICIO_MS)
    controle.registrar_consulta(INICIO_MS)
    assert not controle.deve_consultar(INICIO_MS + UMA_HORA_MS)
    assert controle.deve_consultar(INICIO_MS + 6 * UMA_HORA_MS)
    assert controle.consultas == 1


# --------------------------------------------------------------------
# Cadencia dentro do motor de backtest -- o teste que importa
# --------------------------------------------------------------------


def test_cerebro_e_consultado_so_a_cada_6h_e_nao_a_cada_candle():
    """
    O requisito central da cadencia: 49 candles de 1h, mas o modelo so
    pode ser chamado de 6 em 6 horas. Os outros 40 passos tem que sair
    sem chamada nenhuma de API.
    """
    candles = montar_candles(49)
    analista = AnalistaFalso()
    estrategia = criar_estrategia_do_cerebro(analista, intervalo_ms=6 * UMA_HORA_MS)

    indices_consultados = []
    original = analista.analisar

    def espionar(**kwargs):
        indices_consultados.append(len(indices_consultados))
        return original(**kwargs)

    analista.analisar = espionar
    rodar_backtest(candles, estrategia, capital_inicial=10_000.0)

    # O motor consulta a estrategia nos indices 0..47 (o ultimo candle
    # nao e consultado -- nao ha abertura seguinte pra preencher).
    consultas_esperadas = len([i for i in range(len(candles) - 1) if i % 6 == 0])
    assert analista.chamadas == consultas_esperadas, (
        f"{analista.chamadas} chamadas, esperado {consultas_esperadas}"
    )
    assert analista.chamadas == 8
    # 48 passos, 8 consultas: 40 passos sem chamada nenhuma.
    assert (len(candles) - 1) - analista.chamadas == 40


def test_cadencia_e_configuravel_e_nao_fixa_no_codigo():
    candles = montar_candles(25)

    for horas, esperado in ((1, 24), (12, 2), (24, 1)):
        analista = AnalistaFalso()
        estrategia = criar_estrategia_do_cerebro(
            analista, intervalo_ms=horas * UMA_HORA_MS
        )
        rodar_backtest(candles, estrategia, capital_inicial=10_000.0)
        assert analista.chamadas == esperado, f"{horas}h -> {analista.chamadas}"


def test_entre_consultas_a_estrategia_mantem_a_posicao():
    """
    Consulta no candle 0 mandando BUY; dali ate a proxima consulta, todo
    passo tem que devolver HOLD (posicionada) sem chamar o modelo.
    """
    candles = montar_candles(13)
    tese_compra = TeseDeOperacao(
        direction=BUY, horizon="medio", confidence=0.7, reasoning="tendencia de alta"
    )
    analista = AnalistaFalso(teses=[tese_compra])
    estrategia = criar_estrategia_do_cerebro(analista, intervalo_ms=6 * UMA_HORA_MS)

    decididas = []
    for i in range(len(candles) - 1):
        contexto = ContextoSimulado(i, candles[: i + 1], posicao_aberta=i >= 1)
        decididas.append(estrategia(contexto))

    assert decididas[0] == BUY          # consulta
    assert decididas[1:6] == [HOLD] * 5  # espera, ja posicionada
    assert analista.chamadas == 2        # candle 0 e candle 6


def test_sem_posicao_a_espera_e_no_trade():
    candles = montar_candles(7)
    analista = AnalistaFalso()
    estrategia = criar_estrategia_do_cerebro(analista, intervalo_ms=6 * UMA_HORA_MS)

    decididas = [
        estrategia(ContextoSimulado(i, candles[: i + 1], posicao_aberta=False))
        for i in range(6)
    ]
    assert decididas[1:] == [NO_TRADE] * 5
    assert analista.chamadas == 1


class ContextoSimulado:
    """Contexto minimo, com a mesma superficie que a estrategia consome."""

    def __init__(self, indice, candles, posicao_aberta=False):
        self.indice = indice
        self.candles = candles
        self.posicao_aberta = posicao_aberta

    @property
    def candle_atual(self):
        return self.candles[-1]

    @property
    def preco_atual(self):
        return self.candles[-1]["fechamento"]

    @property
    def features(self):
        return calcular_features(self.candles)


def test_rodadas_diferentes_nao_compartilham_cadencia():
    """Cada fabrica cria memoria propria -- senao a 2a rodada comecaria adiantada."""
    candles = montar_candles(13)
    a, b = AnalistaFalso(), AnalistaFalso()
    rodar_backtest(candles, criar_estrategia_do_cerebro(a, intervalo_ms=6 * UMA_HORA_MS),
                   capital_inicial=10_000.0)
    rodar_backtest(candles, criar_estrategia_do_cerebro(b, intervalo_ms=6 * UMA_HORA_MS),
                   capital_inicial=10_000.0)
    assert a.chamadas == b.chamadas == 2


def test_falha_do_modelo_interrompe_a_rodada_por_padrao():
    candles = montar_candles(10)
    estrategia = criar_estrategia_do_cerebro(AnalistaQuebrado())
    try:
        rodar_backtest(candles, estrategia, capital_inicial=10_000.0)
    except ErroDoCerebro:
        return
    raise AssertionError("erro do modelo deveria ter interrompido o backtest")


def test_ao_falhar_permite_degradar_no_caminho_ao_vivo():
    candles = montar_candles(10)
    quebrado = AnalistaQuebrado()
    estrategia = criar_estrategia_do_cerebro(quebrado, ao_falhar=NO_TRADE)
    resultado = rodar_backtest(candles, estrategia, capital_inicial=10_000.0)
    assert resultado.metricas["numero_operacoes"] == 0
    assert quebrado.chamadas >= 1


# --------------------------------------------------------------------
# Contrato de saida
# --------------------------------------------------------------------


def test_schema_rejeita_confianca_fora_da_faixa():
    for invalida in (-0.1, 1.1, 2.0):
        try:
            TeseDeOperacao(direction=BUY, horizon="curto",
                           confidence=invalida, reasoning="x")
        except Exception:
            continue
        raise AssertionError(f"confidence={invalida} deveria ter sido rejeitada")


def test_schema_rejeita_direcao_fora_do_vocabulario():
    for invalida in ("COMPRAR", "buy", "LONG", ""):
        try:
            TeseDeOperacao(direction=invalida, horizon="curto",
                           confidence=0.5, reasoning="x")
        except Exception:
            continue
        raise AssertionError(f"direction={invalida!r} deveria ter sido rejeitada")


def test_schema_aceita_as_quatro_direcoes_oficiais():
    for direcao in (BUY, SELL, HOLD, NO_TRADE):
        tese = TeseDeOperacao(direction=direcao, horizon="medio",
                              confidence=0.5, reasoning="x")
        assert tese.direction == direcao


def test_resposta_vazia_estoura_em_vez_de_virar_hold():
    analista = AnalistaLLM(cliente=ClienteFalso(RespostaFalsa(parsed=None, text=None)))
    try:
        analista.analisar({"rsi_14": 50}, "BTCUSDT")
    except ErroDoCerebro:
        return
    raise AssertionError("resposta vazia deveria estourar")


def test_resposta_fora_do_contrato_estoura():
    ruim = json.dumps({"direction": "TALVEZ", "horizon": "curto",
                       "confidence": 0.5, "reasoning": "x"})
    analista = AnalistaLLM(cliente=ClienteFalso(RespostaFalsa(parsed=None, text=ruim)))
    try:
        analista.analisar({"rsi_14": 50}, "BTCUSDT")
    except ErroDoCerebro:
        return
    raise AssertionError("resposta fora do contrato deveria estourar")


def test_texto_cru_valido_e_aceito_quando_parsed_vem_vazio():
    bom = json.dumps({"direction": "NO_TRADE", "horizon": "curto",
                      "confidence": 0.3, "reasoning": "lateral"})
    analista = AnalistaLLM(cliente=ClienteFalso(RespostaFalsa(parsed=None, text=bom)))
    tese = analista.analisar({"rsi_14": 50}, "BTCUSDT")
    assert tese.direction == NO_TRADE


def test_registro_leva_symbol_provedor_e_modelo():
    """
    O registro que vai pro `llm_output` precisa dizer QUEM respondeu.

    Com o provedor trocavel por variavel de ambiente, duas rodadas --
    uma no Gemini, outra no Claude -- produziriam linhas identicas no
    banco se so o modelo fosse gravado e alguem trocasse o padrao. O
    par (provedor, modelo) e o que torna a linha auditavel.
    """
    cliente = ClienteFalso(RespostaFalsa(parsed=TESE_PADRAO))
    analista = AnalistaLLM(modelo="modelo-de-teste", cliente=cliente)
    registro = analista.analisar_para_registro({"rsi_14": 50}, "ETHUSDT")

    assert registro["symbol"] == "ETHUSDT"
    assert registro["modelo"] == "modelo-de-teste"
    assert registro["provedor"] == "gemini"
    assert set(registro) == {"symbol", "provedor", "modelo", "direction",
                             "horizon", "confidence", "reasoning"}
    json.dumps(registro, allow_nan=False)


# --------------------------------------------------------------------
# O prompt
# --------------------------------------------------------------------


def test_prompt_nao_leva_candle_cru():
    """Principio 3: o cerebro nunca ve dado bruto."""
    candles = montar_candles(300)
    features = calcular_features(candles)
    prompt = montar_prompt(features, "BTCUSDT", posicao_aberta=False)

    for campo_cru in ("abertura_em", "maxima", "minima", "fechamento_em"):
        assert campo_cru not in prompt, f"prompt vazou o campo cru {campo_cru}"
    assert "rsi_14" in prompt and "atr_14" in prompt


def test_prompt_diz_se_ha_posicao():
    features = calcular_features(montar_candles(300))
    assert "Nao ha posicao aberta" in montar_prompt(features, "BTCUSDT", False)
    assert "posicao comprada aberta" in montar_prompt(features, "BTCUSDT", True)


def test_prompt_aceita_features_com_none():
    """Historico curto: a Feature Engine devolve None, e isso tem que serializar."""
    features = calcular_features(montar_candles(30))
    assert features["ema_200"] is None
    prompt = montar_prompt(features, "BTCUSDT", posicao_aberta=False)
    assert "null" in prompt


# --------------------------------------------------------------------
# Candle em andamento
# --------------------------------------------------------------------


def test_descarta_o_candle_que_ainda_nao_fechou():
    candles = montar_candles(10)
    # "Agora" e meio do ultimo candle: ele ainda esta aberto.
    agora = candles[-1]["abertura_em"] + UMA_HORA_MS // 2
    fechados = somente_fechados(candles, agora_ms=agora)

    assert len(fechados) == 9
    assert fechados[-1]["abertura_em"] == candles[-2]["abertura_em"]


def test_mantem_todos_quando_todos_ja_fecharam():
    candles = montar_candles(10)
    agora = candles[-1]["fechamento_em"] + 1
    assert len(somente_fechados(candles, agora_ms=agora)) == 10


def test_funciona_sem_o_campo_fechamento_em():
    """Candle de arquivo antigo: a duracao e inferida das aberturas."""
    candles = [
        {k: v for k, v in candle.items() if k != "fechamento_em"}
        for candle in montar_candles(10)
    ]
    agora = candles[-1]["abertura_em"] + UMA_HORA_MS // 2
    assert len(somente_fechados(candles, agora_ms=agora)) == 9


def test_lista_vazia_nao_quebra():
    assert somente_fechados([]) == []


def test_candle_aberto_subestima_o_volume_relativo():
    """
    A razao de o filtro existir, demonstrada com numero.

    Vinte e um candles de volume 100, e um candle em andamento que so
    acumulou 10 ate agora. Com ele na conta, o volume relativo sai ~0.1 --
    o cerebro leria "volume muito abaixo do normal" quando na verdade o
    candle so comecou. Sem ele, sai 1.0.
    """
    candles = montar_candles(22)
    candles[-1]["volume"] = 10.0  # 10% do normal: candle recem-aberto

    com_o_aberto = calcular_features(candles)["volume_relativo"]
    agora = candles[-1]["abertura_em"] + UMA_HORA_MS // 2
    sem_o_aberto = calcular_features(somente_fechados(candles, agora_ms=agora))["volume_relativo"]

    assert perto(com_o_aberto, 0.1, tol=0.01), com_o_aberto
    assert perto(sem_o_aberto, 1.0, tol=0.01), sem_o_aberto
    assert sem_o_aberto > com_o_aberto


def test_feature_engine_continua_pura():
    """
    O filtro nao pode ter vazado pra dentro da Feature Engine: a mesma
    lista de candles tem que dar o mesmo resultado sempre, independente
    de que horas sao.
    """
    candles = montar_candles(300)
    assert calcular_features(candles) == calcular_features(candles)
    assert "fechamento_em" in candles[-1]  # o campo existe...
    # ...e mesmo assim nao muda nada no calculo: quem filtra e quem chama.
    sem_campo = [{k: v for k, v in c.items() if k != "fechamento_em"} for c in candles]
    assert calcular_features(candles) == calcular_features(sem_campo)


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
