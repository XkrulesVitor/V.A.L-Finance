"""
Adapter para a Binance (testnet).

Isola tudo que e especifico da Binance atras de uma interface fixa
(buscar_preco, buscar_candles, buscar_historico, enviar_ordem...).
Quando o projeto expandir pra outro mercado, escreve-se um adapter novo
com essas mesmas funcoes -- o resto do sistema nao muda (ver escopo,
secao 6).
"""

import os
from binance import Client


def _formatar_klines(klines) -> list[dict]:
    """
    Kline cru da Binance (lista posicional) -> dicionario nomeado.

    `fechamento_em` (indice 6 do kline) e o instante em que o candle
    fecha. A Binance sempre devolveu esse campo; o adapter e que o
    descartava. Ele volta porque e a unica forma direta de saber se o
    ultimo candle ja fechou ou ainda esta em andamento -- distincao que
    importa pra decisao ao vivo (ver `features/candles.py`). Inferir isso
    da duracao funciona, mas e conta; o campo e o dado.
    """
    return [
        {
            "abertura_em": k[0],
            "abertura": float(k[1]),
            "maxima": float(k[2]),
            "minima": float(k[3]),
            "fechamento": float(k[4]),
            "volume": float(k[5]),
            "fechamento_em": k[6],
        }
        for k in klines
    ]


class BinanceAdapter:
    def __init__(self, testnet: bool = True, somente_dados_publicos: bool = False):
        """
        somente_dados_publicos: monta o cliente sem exigir chave de API.

        Preco e candle sao endpoints publicos na Binance -- rodar um
        backtest nao deveria exigir credencial nenhuma, e exigir seria
        fricção sem contrapartida. Com a flag ligada, `consultar_saldo` e
        `enviar_ordem` passam a falhar cedo e com mensagem propria, em vez
        de deixar a corretora recusar por autenticacao la na frente.
        """
        self.somente_dados_publicos = somente_dados_publicos

        if somente_dados_publicos:
            api_key = api_secret = ""
        else:
            api_key = os.environ["BINANCE_API_KEY"]
            api_secret = os.environ["BINANCE_API_SECRET"]

        self.client = Client(api_key, api_secret, testnet=testnet)

    def buscar_preco(self, simbolo: str) -> float:
        """Preco atual de um par, ex: 'BTCUSDT'."""
        ticker = self.client.get_symbol_ticker(symbol=simbolo)
        return float(ticker["price"])

    def buscar_candles(self, simbolo: str, intervalo: str = "1h", limite: int = 100) -> list[dict]:
        """
        Candles (OHLCV) mais recentes.
        intervalo: '1m', '5m', '15m', '1h', '4h', '1d', etc.
        """
        klines = self.client.get_klines(symbol=simbolo, interval=intervalo, limit=limite)
        return _formatar_klines(klines)

    def buscar_historico(
        self,
        simbolo: str,
        intervalo: str = "1h",
        inicio: str = "1 year ago UTC",
        fim: str | None = None,
    ) -> list[dict]:
        """
        Candles de um periodo longo, pro backtest (passo 3 do roteiro).

        Diferente de `buscar_candles`, que pega os N mais recentes numa
        requisicao so: aqui a python-binance pagina sozinha. A Binance
        devolve no maximo 1000 candles por chamada, e um ano em 1h sao
        ~8.760 -- ou seja, ~9 requisicoes encadeadas que a lib resolve
        internamente. Nao ha motivo pra reimplementar essa paginacao.

        `inicio` e `fim` aceitam o que a python-binance aceita: texto em
        linguagem natural ("1 year ago UTC", "1 Jan, 2025") ou timestamp
        em milissegundos. `fim=None` significa "ate agora".

        Atencao ao ambiente: para backtest, monte o adapter com
        `testnet=False`. A testnet e um ambiente de execucao de ordens,
        nao uma fonte de historico -- o livro dela e raso e sintetico, e
        um backtest rodado em cima disso mede ruido, nao mercado. Dado
        historico vem da API publica de producao, que nao exige chave.
        """
        klines = self.client.get_historical_klines(simbolo, intervalo, inicio, fim)
        return _formatar_klines(klines)

    def consultar_saldo(self, ativo: str = "USDT") -> float:
        """Saldo disponivel na conta testnet."""
        self._exigir_credenciais("consultar_saldo")
        saldo = self.client.get_asset_balance(asset=ativo)
        return float(saldo["free"]) if saldo else 0.0

    def enviar_ordem(self, simbolo: str, lado: str, quantidade: float) -> dict:
        """
        Envia ordem a mercado na testnet.
        lado: 'BUY' ou 'SELL'. SELL fecha/reduz posicao -- V1 e spot only,
        sem venda a descoberto (ver escopo, secao 4).
        """
        self._exigir_credenciais("enviar_ordem")
        side = Client.SIDE_BUY if lado.upper() == "BUY" else Client.SIDE_SELL
        return self.client.create_order(
            symbol=simbolo,
            side=side,
            type=Client.ORDER_TYPE_MARKET,
            quantity=quantidade,
        )

    def _exigir_credenciais(self, operacao: str) -> None:
        if self.somente_dados_publicos:
            raise RuntimeError(
                f"'{operacao}' exige credencial da Binance, mas este adapter foi "
                f"criado com somente_dados_publicos=True (modo backtest/leitura)."
            )
