"""
Conferencia do adapter da Binance.

    python backend/tests/test_binance_adapter.py

Sem rede: o cliente da corretora e substituido por um duble.

## Por que este arquivo existe

`binance_adapter.py` era o modulo de maior risco sem teste nenhum -- e o
unico ponto do sistema que fala com a corretora, e no passo 8 sera ele
que envia ordens.

O que motivou escrever agora foi um erro concreto: a primeira execucao do
cron no GitHub Actions morreu com HTTP 451, "Service unavailable from a
restricted location". A Binance geo-bloqueia o IP do runner (Phoenix,
EUA). Medido de dentro do runner em 2026-09-04:

    api.binance.com          451
    testnet.binance.vision   451
    data-api.binance.vision  200

E os candles do `data-api` sao identicos aos do mainnet, campo a campo,
enquanto os do testnet NAO sao: mesmo instante, fechamento diferente e
volume de ~5% do real. Como `volume_relativo` e uma das features
gravadas, coletar do testnet distorcia o dado na origem.

Os testes abaixo travam as duas coisas que essa correcao depende:
o endpoint usado em modo publico, e o fato de que modo publico nao pede
credencial.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest import mock  # noqa: E402

import adapters.binance_adapter as adapter_mod  # noqa: E402
from adapters.binance_adapter import (  # noqa: E402
    URL_DADOS_PUBLICOS,
    BinanceAdapter,
    _formatar_klines,
)

KLINE_CRU = [
    1788487200000, "80968.01000000", "80968.01000000", "80669.45000000",
    "80831.99000000", "433.77504000", 1788490799999, "35039220.51046570",
    80848, "155.25388000", "12541000.00", "0",
]


class ClienteDuble:
    """Substitui o Client da python-binance. Registra como foi construido."""

    def __init__(self, api_key, api_secret, testnet=False, ping=True, **kwargs):
        self.api_key = api_key
        self.api_secret = api_secret
        self.testnet = testnet
        self.ping_pedido = ping
        self.API_URL = "https://api.binance.com/api"

    def get_symbol_ticker(self, symbol):
        return {"symbol": symbol, "price": "80906.74000000"}

    def get_klines(self, symbol, interval, limit):
        return [KLINE_CRU] * limit


def _com_duble():
    return mock.patch.object(adapter_mod, "Client", ClienteDuble)


def _sem_credenciais():
    ambiente = {k: v for k, v in os.environ.items()
                if k not in ("BINANCE_API_KEY", "BINANCE_API_SECRET")}
    return mock.patch.dict(os.environ, ambiente, clear=True)


# ------------------------------------------------------ formatacao do kline

def test_kline_vira_dicionario_nomeado():
    linha = _formatar_klines([KLINE_CRU])[0]
    assert linha["abertura"] == 80968.01
    assert linha["maxima"] == 80968.01
    assert linha["minima"] == 80669.45
    assert linha["fechamento"] == 80831.99
    assert linha["volume"] == 433.77504


def test_kline_preserva_fechamento_em():
    # `fechamento_em` e a unica forma direta de saber se o candle ja
    # fechou -- e `features/candles.py` depende disso pra descartar o
    # candle em andamento.
    linha = _formatar_klines([KLINE_CRU])[0]
    assert linha["abertura_em"] == 1788487200000
    assert linha["fechamento_em"] == 1788490799999
    assert linha["fechamento_em"] > linha["abertura_em"]


def test_numeros_viram_float_e_nao_texto():
    # A Binance devolve tudo como string. Se escapar uma, a Feature Engine
    # faz aritmetica de texto e o erro aparece longe daqui.
    linha = _formatar_klines([KLINE_CRU])[0]
    for campo in ("abertura", "maxima", "minima", "fechamento", "volume"):
        assert isinstance(linha[campo], float), f"{campo} nao virou float"


# ------------------------------------------------------------ modo publico

def test_modo_publico_usa_data_api():
    # Regressao do HTTP 451: api.binance.com e testnet.binance.vision sao
    # geo-bloqueados no runner do GitHub Actions; data-api nao e.
    with _com_duble(), _sem_credenciais():
        a = BinanceAdapter(somente_dados_publicos=True)
        assert a.client.API_URL == URL_DADOS_PUBLICOS, (
            f"modo publico devia apontar pro data-api, apontou {a.client.API_URL}"
        )


def test_modo_publico_nao_exige_credencial():
    with _com_duble(), _sem_credenciais():
        a = BinanceAdapter(somente_dados_publicos=True)
        assert a.client.api_key == ""
        assert a.client.api_secret == ""


def test_modo_publico_nao_pinga_no_init():
    # O ping do __init__ ia pro endpoint antigo, antes da troca de URL --
    # era ele que estourava 451 antes do adapter poder fazer qualquer coisa.
    with _com_duble(), _sem_credenciais():
        a = BinanceAdapter(somente_dados_publicos=True)
        assert a.client.ping_pedido is False, "init nao pode pingar"


def test_testnet_nao_vaza_pro_modo_publico():
    # Nao existe testnet do endpoint publico, e o livro do testnet tem
    # volume irreal. Pedir os dois junto tem que continuar dando dado real.
    with _com_duble(), _sem_credenciais():
        a = BinanceAdapter(testnet=True, somente_dados_publicos=True)
        assert a.client.API_URL == URL_DADOS_PUBLICOS


# ---------------------------------------------------------- modo autenticado

def test_modo_autenticado_le_as_chaves_do_ambiente():
    with _com_duble(), mock.patch.dict(
        os.environ, {"BINANCE_API_KEY": "chave", "BINANCE_API_SECRET": "segredo"}
    ):
        a = BinanceAdapter(testnet=True, somente_dados_publicos=False)
        assert a.client.api_key == "chave"
        assert a.client.testnet is True


def test_modo_autenticado_sem_chave_falha_cedo():
    with _com_duble(), _sem_credenciais():
        try:
            BinanceAdapter(somente_dados_publicos=False)
        except KeyError:
            pass
        else:
            raise AssertionError("sem credencial devia falhar na construcao")


def test_modo_autenticado_nao_usa_data_api():
    # data-api nao aceita autenticacao nem ordens. Se o modo autenticado
    # herdasse essa URL, o passo 8 falharia na hora de operar.
    with _com_duble(), mock.patch.dict(
        os.environ, {"BINANCE_API_KEY": "k", "BINANCE_API_SECRET": "s"}
    ):
        a = BinanceAdapter(somente_dados_publicos=False)
        assert a.client.API_URL != URL_DADOS_PUBLICOS


# --------------------------------------------------------------- consultas

def test_buscar_preco_devolve_float():
    with _com_duble(), _sem_credenciais():
        a = BinanceAdapter(somente_dados_publicos=True)
        preco = a.buscar_preco("BTCUSDT")
        assert isinstance(preco, float)
        assert preco == 80906.74


def test_buscar_candles_respeita_o_limite():
    with _com_duble(), _sem_credenciais():
        a = BinanceAdapter(somente_dados_publicos=True)
        candles = a.buscar_candles("BTCUSDT", "1h", 7)
        assert len(candles) == 7
        assert candles[0]["fechamento"] == 80831.99


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
