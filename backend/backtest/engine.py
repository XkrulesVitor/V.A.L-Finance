"""
Motor de backtest -- passo 3 do roteiro (secao 10 do ARCHITECTURE.md).

Caminha candle a candle por um periodo historico, pergunta a uma
estrategia o que fazer usando SO o que ja aconteceu ate ali, aplica a
decisao numa carteira simulada e mede o resultado.

O motor e agnostico a estrategia de proposito. Ele nao sabe o que e uma
EMA, nem o que e um LLM -- recebe uma funcao e chama. E isso que permite
que a estrategia hibrida do passo 7 (cerebro + Risk Engine) rode neste
mesmo motor, comparada contra a baseline do passo 4 sem que uma linha
daqui mude. Se o motor precisar ser alterado pra acomodar a estrategia
hibrida, a comparacao perde o sentido: nao seriam mais duas estrategias
medidas pela mesma regua.

## O contrato da estrategia

Uma estrategia e qualquer callable:

    def minha_estrategia(contexto: ContextoDeDecisao) -> str: ...

que devolve uma das quatro decisoes oficiais da secao 6 -- BUY, SELL,
HOLD ou NO_TRADE. Esse vocabulario e o mesmo que o cerebro vai devolver
e que a tabela `decisions` ja registra; o backtest nao inventa um
dialeto proprio, senao o passo 7 viraria um exercicio de traducao.

## As duas regras que sustentam o resultado

**1. A estrategia nunca ve o futuro.** No candle `i` ela recebe o
historico ate `i` inclusive -- o fechamento de `i` ja aconteceu, os
candles `i+1` em diante nao existem pra ela. Um motor que vaza um unico
candle de futuro produz curva bonita e mentirosa, e o pior e que a
mentira nao aparece como erro: aparece como lucro.

**2. A ordem executa na ABERTURA do candle seguinte.** Se a decisao
nasce do fechamento de `i`, ela nao pode ser preenchida nesse mesmo
fechamento -- na vida real existe o intervalo entre observar e mandar a
ordem. Preencher no proprio fechamento que gerou o sinal e a forma mais
comum de otimismo silencioso em backtest. Aqui o preenchimento e a
abertura de `i+1`, que e o primeiro preco de fato negociavel depois da
decisao.
"""

import json
import math
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timezone

from features.feature_engine import CANDLES_NECESSARIOS, calcular_features

# As quatro decisoes oficiais (secao 6 do ARCHITECTURE.md).
BUY, SELL, HOLD, NO_TRADE = "BUY", "SELL", "HOLD", "NO_TRADE"
DECISOES_VALIDAS = (BUY, SELL, HOLD, NO_TRADE)

# 0,10% por operacao -- taxa spot padrao da Binance no nivel VIP 0.
# Fica como padrao, nao como constante fixa no codigo: taxa muda com
# volume negociado, com desconto de BNB e com corretora, e um backtest
# que ignora custo e um backtest que responde a pergunta errada
# (metodologia, secao 11).
TAXA_PADRAO = 0.001
CAPITAL_INICIAL_PADRAO = 10_000.0

MS_POR_ANO = 365.25 * 24 * 60 * 60 * 1000


# --------------------------------------------------------------------
# O que a estrategia enxerga
# --------------------------------------------------------------------


@dataclass(frozen=True)
class ContextoDeDecisao:
    """
    A fotografia de um instante do backtest, do ponto de vista da
    estrategia. Tudo aqui e passado; nada aqui e futuro.

    `candles` termina no candle que esta sendo avaliado. Os dicionarios
    de candle sao compartilhados com o motor por questao de custo (copiar
    centenas deles a cada passo dominaria o tempo de execucao) -- uma
    estrategia nao deve modifica-los.
    """

    indice: int
    candles: list[dict]
    posicao_aberta: bool
    quantidade: float
    caixa: float
    preco_de_entrada: float
    _cache: dict = field(default_factory=dict, repr=False, compare=False)

    @property
    def candle_atual(self) -> dict:
        return self.candles[-1]

    @property
    def preco_atual(self) -> float:
        """Fechamento do candle avaliado -- o ultimo preco que ja aconteceu."""
        return self.candles[-1]["fechamento"]

    @property
    def features(self) -> dict:
        """
        Indicadores da Feature Engine calculados sobre a janela visivel.

        E uma property preguicosa, e nao um campo, porque o calculo e a
        parte cara do backtest (varias medias recursivas por passo) e nem
        toda estrategia precisa dele -- `buy_and_hold` nunca olha um
        indicador. Assim quem nao usa, nao paga. O resultado fica em
        cache: chamar duas vezes no mesmo passo custa uma.
        """
        if "features" not in self._cache:
            self._cache["features"] = calcular_features(self.candles)
        return self._cache["features"]


@dataclass
class Operacao:
    """Uma ordem efetivamente preenchida."""

    indice: int
    executado_em: int  # timestamp (ms) do candle em que foi preenchida
    lado: str
    preco: float
    quantidade: float
    taxa_paga: float
    caixa_depois: float
    motivo: str  # 'estrategia' ou 'liquidacao_final'

    def como_dicionario(self) -> dict:
        return {
            "indice": self.indice,
            "executado_em": _para_iso(self.executado_em),
            "lado": self.lado,
            "preco": self.preco,
            "quantidade": self.quantidade,
            "taxa_paga": self.taxa_paga,
            "caixa_depois": self.caixa_depois,
            "motivo": self.motivo,
        }


@dataclass
class ResultadoBacktest:
    """Tudo que uma rodada produziu."""

    estrategia: str
    metricas: dict
    parametros: dict
    periodo: dict
    operacoes: list
    curva_de_capital: list

    def resumo(self) -> str:
        m = self.metricas
        return (
            f"{self.estrategia:<16} "
            f"retorno {_fmt(m['retorno_total_pct']):>9}%  "
            f"CAGR {_fmt(m['cagr_pct']):>8}%  "
            f"Sharpe {_fmt(m['sharpe']):>6}  "
            f"drawdown {_fmt(m['max_drawdown_pct']):>8}%  "
            f"acerto {_fmt(m['taxa_acerto_pct']):>6}%  "
            f"trades {m['numero_trades']:>4}  "
            f"saldo {_fmt(m['saldo_final']):>12}"
        )


# --------------------------------------------------------------------
# O motor
# --------------------------------------------------------------------


def rodar_backtest(
    candles: list[dict],
    estrategia,
    *,
    capital_inicial: float = CAPITAL_INICIAL_PADRAO,
    taxa_por_operacao: float = TAXA_PADRAO,
    janela_maxima: int = CANDLES_NECESSARIOS,
    nome_estrategia: str | None = None,
) -> ResultadoBacktest:
    """
    Simula `estrategia` sobre `candles` e devolve metricas e operacoes.

    `janela_maxima` limita quantos candles a estrategia enxerga a cada
    passo. Nao e so economia de tempo -- e paridade com a producao: o
    cron job do passo 2 pede exatamente `CANDLES_NECESSARIOS` candles a
    cada ciclo, entao dar a estrategia o historico inteiro no backtest a
    colocaria num mundo que ela nao vai encontrar quando rodar de
    verdade. Backtest so vale se mede a estrategia que vai existir.

    Posicao e cheia: compra usa todo o caixa, venda zera a posicao. Sem
    posicao parcial, sem stop-loss, sem tamanho de posicao calculado --
    isso e o motor base. Dimensionamento e risco entram pelo Risk Engine
    (passo 6), do lado da estrategia, sem mexer aqui.
    """
    nome = nome_estrategia or getattr(estrategia, "__name__", "estrategia")

    if len(candles) < 2:
        raise ValueError(
            "backtest precisa de pelo menos 2 candles: a decisao nasce no "
            "fechamento de um e e preenchida na abertura do seguinte."
        )
    if not 0 <= taxa_por_operacao < 1:
        raise ValueError(f"taxa_por_operacao fora de faixa: {taxa_por_operacao}")
    if capital_inicial <= 0:
        raise ValueError(f"capital_inicial precisa ser positivo: {capital_inicial}")
    if janela_maxima < 1:
        raise ValueError(f"janela_maxima precisa ser >= 1: {janela_maxima}")

    candles = sorted(candles, key=lambda c: c["abertura_em"])

    caixa = float(capital_inicial)
    quantidade = 0.0
    preco_de_entrada = 0.0
    custo_da_entrada = 0.0  # quanto de caixa a posicao atual consumiu

    operacoes: list[Operacao] = []
    trades: list[dict] = []  # ida e volta fechadas, pra taxa de acerto
    curva: list[dict] = []
    decisao_pendente: str | None = None

    for i, candle in enumerate(candles):
        # 1. Preenche o que foi decidido no candle anterior, na abertura
        #    deste. Isto vem antes de qualquer outra coisa no passo.
        if decisao_pendente is not None:
            preco = candle["abertura"]

            if decisao_pendente == BUY and quantidade == 0 and caixa > 0:
                custo_da_entrada = caixa
                taxa = caixa * taxa_por_operacao
                quantidade = (caixa - taxa) / preco
                caixa = 0.0
                preco_de_entrada = preco
                operacoes.append(
                    Operacao(i, candle["abertura_em"], BUY, preco, quantidade,
                             taxa, caixa, "estrategia")
                )

            elif decisao_pendente == SELL and quantidade > 0:
                bruto = quantidade * preco
                taxa = bruto * taxa_por_operacao
                caixa = bruto - taxa
                trades.append({
                    "entrada": preco_de_entrada,
                    "saida": preco,
                    "resultado": caixa - custo_da_entrada,
                })
                operacoes.append(
                    Operacao(i, candle["abertura_em"], SELL, preco, quantidade,
                             taxa, caixa, "estrategia")
                )
                quantidade = 0.0
                preco_de_entrada = 0.0
                custo_da_entrada = 0.0

            decisao_pendente = None

        # 2. Marca a carteira a mercado no fechamento deste candle.
        curva.append({
            "abertura_em": candle["abertura_em"],
            "patrimonio": caixa + quantidade * candle["fechamento"],
        })

        # 3. Pergunta a estrategia -- vendo so ate aqui. O ultimo candle
        #    nao e consultado: nao existe abertura seguinte pra preencher.
        if i < len(candles) - 1:
            inicio_janela = max(0, i + 1 - janela_maxima)
            contexto = ContextoDeDecisao(
                indice=i,
                candles=candles[inicio_janela : i + 1],
                posicao_aberta=quantidade > 0,
                quantidade=quantidade,
                caixa=caixa,
                preco_de_entrada=preco_de_entrada,
            )
            decisao_pendente = _validar_decisao(estrategia(contexto), nome, i)

    # 4. Liquidacao forcada no fechamento do ultimo candle. Sem isso, uma
    #    estrategia que termina comprada seria comparada com outra que
    #    termina em caixa sem ter pago pra sair -- e o custo de sair e
    #    real. Todas terminam liquidadas, medidas pela mesma regua.
    ultimo = candles[-1]
    if quantidade > 0:
        preco = ultimo["fechamento"]
        bruto = quantidade * preco
        taxa = bruto * taxa_por_operacao
        caixa = bruto - taxa
        trades.append({
            "entrada": preco_de_entrada,
            "saida": preco,
            "resultado": caixa - custo_da_entrada,
        })
        operacoes.append(
            Operacao(len(candles) - 1, ultimo["abertura_em"], SELL, preco,
                     quantidade, taxa, caixa, "liquidacao_final")
        )
        quantidade = 0.0
        curva[-1]["patrimonio"] = caixa

    saldo_final = caixa

    return ResultadoBacktest(
        estrategia=nome,
        metricas=_calcular_metricas(curva, operacoes, trades, capital_inicial, saldo_final),
        parametros={
            "capital_inicial": capital_inicial,
            "taxa_por_operacao": taxa_por_operacao,
            "janela_maxima": janela_maxima,
            "execucao": "abertura do candle seguinte a decisao",
            "posicao": "cheia (all-in / all-out)",
        },
        periodo={
            "inicio": _para_iso(candles[0]["abertura_em"]),
            "fim": _para_iso(ultimo["abertura_em"]),
            "candles": len(candles),
        },
        operacoes=[operacao.como_dicionario() for operacao in operacoes],
        curva_de_capital=curva,
    )


def _validar_decisao(decisao, nome_estrategia: str, indice: int) -> str:
    """
    Uma decisao fora do vocabulario oficial e erro, nao aviso.

    Silenciar (tratando desconhecido como HOLD) esconderia justamente o
    tipo de bug que interessa: uma estrategia devolvendo "buy" minusculo
    ou None viraria "nunca operou", e o backtest reportaria retorno zero
    como se fosse resultado, e nao defeito.
    """
    if decisao not in DECISOES_VALIDAS:
        raise ValueError(
            f"estrategia '{nome_estrategia}' devolveu {decisao!r} no candle "
            f"{indice}; esperado um de {DECISOES_VALIDAS}"
        )
    return decisao


# --------------------------------------------------------------------
# Metricas
# --------------------------------------------------------------------


def _calcular_metricas(curva, operacoes, trades, capital_inicial, saldo_final) -> dict:
    """
    As metricas de uma rodada.

    Sharpe usa retorno livre de risco zero. E uma simplificacao
    deliberada e vale registrar: com juro americano longe de zero, o
    Sharpe daqui sai mais generoso que o classico. Serve pra comparar
    estrategias entre si dentro deste projeto -- que e o uso que ele tem
    aqui (secao 11) -- e nao pra comparar com Sharpe publicado de fundo.
    """
    patrimonios = [ponto["patrimonio"] for ponto in curva]
    duracao_ms = _duracao_do_candle_ms(curva)
    tempo_total_ms = curva[-1]["abertura_em"] - curva[0]["abertura_em"]
    anos = tempo_total_ms / MS_POR_ANO if tempo_total_ms > 0 else 0.0

    retorno_total = saldo_final / capital_inicial - 1

    cagr = None
    if anos > 0 and saldo_final > 0:
        cagr = (saldo_final / capital_inicial) ** (1 / anos) - 1

    # Retornos periodo a periodo da curva de capital.
    retornos = [
        patrimonios[i] / patrimonios[i - 1] - 1
        for i in range(1, len(patrimonios))
        if patrimonios[i - 1] > 0
    ]

    sharpe = None
    if len(retornos) > 1 and duracao_ms:
        desvio = statistics.stdev(retornos)
        if desvio > 0:
            periodos_por_ano = MS_POR_ANO / duracao_ms
            sharpe = (statistics.fmean(retornos) / desvio) * math.sqrt(periodos_por_ano)

    # Max drawdown: a maior queda desde um pico ja atingido.
    max_drawdown = 0.0
    pico = patrimonios[0]
    for patrimonio in patrimonios:
        pico = max(pico, patrimonio)
        if pico > 0:
            max_drawdown = min(max_drawdown, patrimonio / pico - 1)

    vencedores = sum(1 for trade in trades if trade["resultado"] > 0)
    taxa_acerto = (vencedores / len(trades)) if trades else None

    return {
        "saldo_inicial": round(capital_inicial, 2),
        "saldo_final": round(saldo_final, 2),
        "retorno_total_pct": round(retorno_total * 100, 2),
        "cagr_pct": round(cagr * 100, 2) if cagr is not None else None,
        "sharpe": round(sharpe, 2) if sharpe is not None else None,
        "max_drawdown_pct": round(max_drawdown * 100, 2),
        "taxa_acerto_pct": round(taxa_acerto * 100, 2) if taxa_acerto is not None else None,
        "numero_operacoes": len(operacoes),
        "numero_trades": len(trades),
        "anos": round(anos, 3),
        "taxas_pagas": round(sum(operacao.taxa_paga for operacao in operacoes), 2),
    }


def _duracao_do_candle_ms(curva) -> float | None:
    """
    Duracao de um candle, pela mediana das distancias -- mediana e nao
    media porque buraco no historico distorce a media e nao a mediana.
    E o que converte o Sharpe por candle em Sharpe anualizado.
    """
    if len(curva) < 2:
        return None
    distancias = [
        curva[i]["abertura_em"] - curva[i - 1]["abertura_em"] for i in range(1, len(curva))
    ]
    duracao = statistics.median(distancias)
    return float(duracao) if duracao > 0 else None


# --------------------------------------------------------------------
# Utilitarios
# --------------------------------------------------------------------


def _para_iso(timestamp_ms: int) -> str:
    """Timestamp em ms -> ISO 8601 UTC, o formato que o Postgres espera."""
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc).isoformat()


def _fmt(valor) -> str:
    return "-" if valor is None else f"{valor:,.2f}"


def salvar_json(resultado: ResultadoBacktest, caminho) -> None:
    """Grava a rodada inteira -- inclusive curva e operacoes -- num arquivo."""
    with open(caminho, "w", encoding="utf-8") as arquivo:
        json.dump(
            {
                "estrategia": resultado.estrategia,
                "periodo": resultado.periodo,
                "parametros": resultado.parametros,
                "metricas": resultado.metricas,
                "operacoes": resultado.operacoes,
                "curva_de_capital": resultado.curva_de_capital,
            },
            arquivo,
            indent=2,
            allow_nan=False,
        )
