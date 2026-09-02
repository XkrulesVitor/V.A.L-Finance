"""
Ablação: o Risk Engine sozinho, sem cérebro.

Esta é a estratégia de controle que faltava. Ela faz exatamente o que a
híbrida faz -- **menos o LLM**:

- sem posição, compra (como o `buy_and_hold`, sem escolher momento);
- na entrada, calcula stop e alvo pelo ATR, via `avaliar_risco`;
- a cada candle, sai se um dos níveis for rompido;
- depois de sair, volta a comprar.

## Por que ela existe

O único sinal não-trivial que a híbrida produziu foi controle de perda,
não direção: no BNBUSDT ela empatou em retorno com o comprar-e-segurar
(+25,54% contra +25,01%) com **um quarto do drawdown** (−8,56% contra
−32,89%).

Duas explicações cabem nesse número, e elas levam a decisões opostas:

1. o cérebro escolheu bem as horas de estar dentro e fora;
2. o stop-loss por ATR fez todo o trabalho, e o cérebro foi decoração cara.

Esta estratégia separa as duas. Se ela reproduzir o drawdown da híbrida,
a resposta é (2) -- e a conclusão do projeto fica praticamente escrita:
o valor está numa regra de risco de três linhas, não no LLM. Se não
reproduzir, sobra evidência de que o cérebro faz algo que a regra não
faz, e aí vale continuar.

É a comparação mais barata que resta: zero chamadas de API.

Fica em módulo próprio, e não em `strategies.py`, porque aquele arquivo
é importado pela tarefa agendada que roda de madrugada -- mexer nele
para um experimento seria arriscar a rodada por conveniência.
"""

from dataclasses import replace

from backtest.engine import BUY, HOLD, NO_TRADE, SELL
from risk.risk_engine import EstadoDaPosicao, ParametrosDeRisco, avaliar_risco


class ComprarComStop:
    """
    Callable com memória: guarda os níveis da posição aberta, igual à
    híbrida. A diferença é que a decisão de entrar não consulta ninguém.
    """

    def __init__(self, parametros: ParametrosDeRisco | None = None, multiplicador_stop: float | None = None):
        base = parametros or ParametrosDeRisco()
        self.parametros = (
            replace(base, multiplicador_stop=multiplicador_stop) if multiplicador_stop else base
        )
        self.niveis: tuple[float, float] | None = None
        self.pendentes: tuple[float, float] | None = None
        self.saidas_por_stop = 0
        self.saidas_por_alvo = 0
        self.bloqueios = 0
        self.__name__ = "comprar_com_stop"

    def __call__(self, contexto) -> str:
        # Mesma sincronização da híbrida: a ordem só vira posição na
        # abertura do candle seguinte, então os níveis ficam pendentes até lá.
        if contexto.posicao_aberta:
            if self.pendentes is not None:
                self.niveis, self.pendentes = self.pendentes, None
        else:
            self.niveis = self.pendentes = None

        stop, alvo = self.niveis if self.niveis else (None, None)
        posicao = EstadoDaPosicao(
            quantidade=contexto.quantidade,
            preco_entrada=contexto.preco_de_entrada or None,
            stop_loss=stop,
            take_profit=alvo,
        )
        capital = contexto.caixa + contexto.quantidade * contexto.preco_atual

        # ---- com posição: só checa os níveis (barato, sem features) ----
        if posicao.aberta:
            resultado = avaliar_risco(
                tese=HOLD, atr_14=None, preco_atual=contexto.preco_atual,
                posicao=posicao, capital_total=capital, parametros=self.parametros,
            )
            if resultado.acao_final == SELL:
                if stop is not None and contexto.preco_atual <= stop:
                    self.saidas_por_stop += 1
                else:
                    self.saidas_por_alvo += 1
                self.niveis = None
                return SELL
            return HOLD

        # ---- sem posição: entra, se o risco permitir ----
        resultado = avaliar_risco(
            tese=BUY, atr_14=contexto.features["atr_14"], preco_atual=contexto.preco_atual,
            posicao=posicao, capital_total=capital, parametros=self.parametros,
        )
        if resultado.acao_final == BUY and resultado.aprovado:
            self.pendentes = (resultado.stop_loss, resultado.take_profit)
            return BUY

        self.bloqueios += 1
        return NO_TRADE

    def resumo(self) -> dict:
        return {
            "saidas_por_stop": self.saidas_por_stop,
            "saidas_por_alvo": self.saidas_por_alvo,
            "bloqueios": self.bloqueios,
            "multiplicador_stop": self.parametros.multiplicador_stop,
        }


def criar(multiplicador_stop: float | None = None, **kwargs) -> ComprarComStop:
    return ComprarComStop(ParametrosDeRisco(**kwargs) if kwargs else None, multiplicador_stop)
