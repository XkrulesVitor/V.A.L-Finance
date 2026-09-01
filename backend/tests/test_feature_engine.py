"""
Conferencia da Feature Engine (passo 2 do roteiro).

Roda de dois jeitos, de proposito:

    python backend/tests/test_feature_engine.py     # sem instalar nada alem do requirements
    pytest backend/tests                            # se pytest estiver disponivel

Por isso os testes sao funcoes com `assert` puro e sem nenhum import de
pytest -- pytest coleta assim mesmo, e o runner no fim do arquivo cobre
quem nao quer instalar dependencia de teste so pra conferir um numero.
`pytest` fica fora do requirements.txt por isso: ele e o que o Render
instala a cada execucao do cron job, e nao ha motivo de pagar esse
download em producao.

Os dados sao sinteticos e deterministicos -- nenhum teste aqui toca a
rede, entao isto roda sem chave da Binance e sem Supabase.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from features.feature_engine import (  # noqa: E402
    JANELA_VOLUME,
    PERIODO_ATR,
    calcular_features,
)

UMA_HORA_MS = 60 * 60 * 1000
INICIO_MS = 1_700_000_000_000

CHAVES_ESPERADAS = {
    "rsi_14",
    "macd",
    "ema_20",
    "ema_50",
    "ema_200",
    "atr_14",
    "volume_relativo",
    "retorno_1h",
    "retorno_24h",
    "retorno_7d",
}


# --------------------------------------------------------------------
# Apoio
# --------------------------------------------------------------------


def montar_candles(fechamentos, volumes=None, amplitude=0.01, duracao_ms=UMA_HORA_MS):
    """Candles sinteticos no mesmo formato que `buscar_candles()` devolve."""
    volumes = volumes if volumes is not None else [100.0] * len(fechamentos)
    candles = []
    for i, fechamento in enumerate(fechamentos):
        meia_amplitude = fechamento * amplitude / 2
        candles.append(
            {
                "abertura_em": INICIO_MS + i * duracao_ms,
                "abertura": fechamentos[i - 1] if i else fechamento,
                "maxima": fechamento + meia_amplitude,
                "minima": fechamento - meia_amplitude,
                "fechamento": fechamento,
                "volume": volumes[i],
            }
        )
    return candles


def serie_de_alta(quantidade=300, inicial=100_000.0, passo=0.002):
    """Tendencia de alta suave, com uma oscilacao pra nao ser reta perfeita."""
    return [
        inicial * (1 + passo) ** i * (1 + 0.001 * ((i % 7) - 3))
        for i in range(quantidade)
    ]


def perto(obtido, esperado, tolerancia=1e-6):
    """Comparacao relativa -- evita depender de pytest.approx."""
    if obtido is None:
        return False
    if esperado == 0:
        return abs(obtido) < tolerancia
    return abs(obtido - esperado) / abs(esperado) < tolerancia


def perto_absoluto(obtido, esperado, tolerancia):
    """
    Comparacao por diferenca absoluta. E a certa pros retornos: eles saem
    arredondados em 2 casas, entao um retorno de 0.30% ja carrega ate
    0.005 de erro de arredondamento -- o que em termos relativos e quase
    2%, e faria uma comparacao relativa acusar falha sem haver bug.
    """
    return obtido is not None and abs(obtido - esperado) <= tolerancia


def atr_de_referencia(candles, periodo=PERIODO_ATR):
    """
    ATR de Wilder implementado do zero, na forma de livro-texto
    `(anterior * (n-1) + tr) / n`.

    Existe pra ser um segundo par de olhos: a Feature Engine escreve a
    mesma media como `anterior + (tr - anterior)/n`. Sao algebricamente
    identicas, mas o seed e os limites do loop foram digitados duas
    vezes, de forma independente -- que e onde esse tipo de indicador
    costuma errar de verdade.
    """
    amplitudes = []
    for i, candle in enumerate(candles):
        if i == 0:
            amplitudes.append(candle["maxima"] - candle["minima"])
            continue
        fechamento_anterior = candles[i - 1]["fechamento"]
        amplitudes.append(
            max(
                candle["maxima"] - candle["minima"],
                abs(candle["maxima"] - fechamento_anterior),
                abs(candle["minima"] - fechamento_anterior),
            )
        )

    atr = sum(amplitudes[:periodo]) / periodo
    for i in range(periodo, len(amplitudes)):
        atr = (atr * (periodo - 1) + amplitudes[i]) / periodo
    return atr


# --------------------------------------------------------------------
# Testes
# --------------------------------------------------------------------


def test_formato_e_json_valido():
    """
    O resultado vai direto pra uma coluna jsonb. `allow_nan=False` e o
    ponto do teste: `json.dumps` aceita NaN por padrao e cospe um `NaN`
    literal, que nao e JSON valido -- o erro so apareceria la no insert
    do Supabase, com o cron job ja meio caminho andado.
    """
    features = calcular_features(montar_candles(serie_de_alta()))

    assert set(features) == CHAVES_ESPERADAS
    assert set(features["macd"]) == {"linha", "sinal", "histograma"}
    json.dumps(features, allow_nan=False)

    for chave, valor in features.items():
        if chave == "macd":
            continue
        assert valor is not None, f"{chave} deveria ter valor com 300 candles"


def test_rsi_fica_entre_0_e_100():
    for serie in (serie_de_alta(), list(reversed(serie_de_alta()))):
        rsi = calcular_features(montar_candles(serie))["rsi_14"]
        assert 0 <= rsi <= 100, rsi


def test_rsi_satura_em_alta_e_em_queda():
    so_subindo = [100.0 + i for i in range(60)]
    assert calcular_features(montar_candles(so_subindo))["rsi_14"] == 100.0
    assert calcular_features(montar_candles(list(reversed(so_subindo))))["rsi_14"] == 0.0


def test_rsi_de_preco_travado_e_neutro():
    """Sem alta nem queda nao ha forca pra lado nenhum -- 50, nao None."""
    assert calcular_features(montar_candles([100.0] * 60))["rsi_14"] == 50.0


def test_atr_e_positivo_e_bate_com_a_recursao_independente():
    candles = montar_candles(serie_de_alta())
    atr = calcular_features(candles)["atr_14"]

    assert atr > 0
    assert perto(atr, atr_de_referencia(candles), tolerancia=1e-6), atr


def test_atr_de_amplitude_constante_e_a_propria_amplitude():
    """Todo candle andando exatamente 100, sem gap: o ATR tem que ser 100."""
    candles = [
        {
            "abertura_em": INICIO_MS + i * UMA_HORA_MS,
            "abertura": 1000.0,
            "maxima": 1050.0,
            "minima": 950.0,
            "fechamento": 1000.0,
            "volume": 10.0,
        }
        for i in range(50)
    ]
    assert perto(calcular_features(candles)["atr_14"], 100.0)


def test_atr_enxerga_gap():
    """
    Amplitude interna identica, mas com salto entre candles: o ATR do
    segundo caso tem que ser maior. Se der igual, o True Range virou
    `maxima - minima` e a volatilidade real ficou subestimada -- o que
    no passo 6 sairia como stop-loss apertado demais.
    """
    sem_gap = montar_candles([1000.0] * 60, amplitude=0.01)
    com_gap = montar_candles(
        [1000.0 if i % 2 else 1100.0 for i in range(60)], amplitude=0.01
    )
    assert calcular_features(com_gap)["atr_14"] > calcular_features(sem_gap)["atr_14"]


def test_emas_se_ordenam_numa_tendencia_de_alta():
    features = calcular_features(montar_candles(serie_de_alta()))
    assert features["ema_20"] > features["ema_50"] > features["ema_200"]


def test_macd_histograma_e_linha_menos_sinal():
    macd = calcular_features(montar_candles(serie_de_alta()))["macd"]
    assert perto(macd["histograma"], macd["linha"] - macd["sinal"], tolerancia=1e-4)


def test_macd_e_positivo_em_alta_e_negativo_em_queda():
    alta = calcular_features(montar_candles(serie_de_alta()))["macd"]
    queda = calcular_features(montar_candles(list(reversed(serie_de_alta()))))["macd"]
    assert alta["linha"] > 0
    assert queda["linha"] < 0


def test_volume_relativo():
    """Base constante em 100 e um candle final de 200 -> exatamente 2.0."""
    quantidade = 60
    volumes = [100.0] * (quantidade - 1) + [200.0]
    features = calcular_features(montar_candles([1000.0] * quantidade, volumes=volumes))
    assert perto(features["volume_relativo"], 2.0)


def test_volume_relativo_ignora_o_proprio_candle_na_media():
    """
    A media de referencia usa os `JANELA_VOLUME` candles ANTERIORES. Se o
    candle atual entrasse nela, um pico de 200 contra base 100 daria
    ~1.90 em vez de 2.00 -- ou seja, o pico se esconderia sozinho.
    """
    quantidade = JANELA_VOLUME + 1
    volumes = [100.0] * JANELA_VOLUME + [200.0]
    features = calcular_features(montar_candles([1000.0] * quantidade, volumes=volumes))
    assert perto(features["volume_relativo"], 2.0)


def test_retornos_batem_com_a_conta_na_mao():
    fechamentos = serie_de_alta(quantidade=300)
    features = calcular_features(montar_candles(fechamentos))

    for chave, candles_atras in (("retorno_1h", 1), ("retorno_24h", 24), ("retorno_7d", 168)):
        esperado = (fechamentos[-1] / fechamentos[-1 - candles_atras] - 1) * 100
        assert perto_absoluto(features[chave], esperado, 0.005), chave


def test_retornos_acompanham_candles_de_outra_duracao():
    """
    Com candles de 4h, `retorno_24h` tem que olhar 6 candles atras, nao
    24 -- a janela e de tempo, nao de barras.
    """
    fechamentos = serie_de_alta(quantidade=300)
    features = calcular_features(montar_candles(fechamentos, duracao_ms=4 * UMA_HORA_MS))

    esperado = (fechamentos[-1] / fechamentos[-1 - 6] - 1) * 100
    assert perto_absoluto(features["retorno_24h"], esperado, 0.005)
    # 1h e menor que um candle de 4h: nao da pra responder, e None e a
    # resposta honesta.
    assert features["retorno_1h"] is None


def test_historico_curto_devolve_none_e_nunca_nan():
    features = calcular_features(montar_candles(serie_de_alta(quantidade=30)))

    assert features["ema_20"] is not None
    assert features["rsi_14"] is not None
    assert features["ema_50"] is None
    assert features["ema_200"] is None
    assert features["retorno_7d"] is None
    json.dumps(features, allow_nan=False)


def test_lista_vazia_nao_quebra_o_ciclo():
    """
    Adapter sem dados nao pode derrubar o cron job -- ele grava a linha
    com features vazias e segue pro proximo par.
    """
    features = calcular_features([])

    assert set(features) == CHAVES_ESPERADAS
    assert all(valor is None for chave, valor in features.items() if chave != "macd")
    json.dumps(features, allow_nan=False)


def test_candles_fora_de_ordem_dao_o_mesmo_resultado():
    candles = montar_candles(serie_de_alta())
    embaralhados = candles[150:] + candles[:150]
    assert calcular_features(embaralhados) == calcular_features(candles)


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
            print(f"  ok   {nome}")
        except AssertionError as erro:
            falhas.append((nome, erro))
            print(f"  FALHA {nome}: {erro}")

    print(f"\n{len(testes) - len(falhas)}/{len(testes)} passaram")
    return 1 if falhas else 0


def _amostra() -> None:
    """Imprime um resultado real pra conferir a olho que os numeros fazem sentido."""
    features = calcular_features(montar_candles(serie_de_alta()))
    print("\nExemplo de saida (serie sintetica em alta):")
    print(json.dumps(features, indent=2, allow_nan=False))


if __name__ == "__main__":
    codigo = _rodar_tudo()
    _amostra()
    sys.exit(codigo)
