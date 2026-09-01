"""
Estrategia hibrida -- passo 7 do roteiro (secao 10 do ARCHITECTURE.md).

"O cerebro decide, o Risk Engine valida e pode sobrepor", embrulhado
numa funcao de estrategia so: `ContextoDeDecisao -> BUY/SELL/HOLD/
NO_TRADE`, exatamente a mesma assinatura de `buy_and_hold` e
`ema_crossover`. E isso que permite medir as tres pela mesma regua no
mesmo motor, sem alterar uma linha do motor (principio 6, secao 4).

Nao ha decisao nova aqui. As duas pecas ja existem e ja sao testadas
isoladamente; este modulo e a composicao delas, e o que ele acrescenta
sao duas coisas: a ordem em que rodam e a cadencia de cada uma.

## As duas cadencias, e por que nao podem ser a mesma

Este e o ponto do modulo, e o bug que a secao 15 registrou como risco
concreto antes de existir codigo:

- **Consultar o cerebro e caro.** E uma chamada de API, com custo e
  limite diario. Segue a cadencia de 6h (secao 6).
- **Checar stop/take e barato.** E comparar um preco contra um numero
  ja gravado. Nao gasta API, nao gasta nada. Roda em TODO candle.

Amarrar as duas a mesma cadencia significa que um stop rompido as 10h
so seria executado as 12h, na proxima consulta -- ate 6 horas de
posicao andando contra, protegida por um stop que existe, esta correto,
e simplesmente nao foi olhado. A protecao viraria enfeite.

Por isso a etapa 1 do `__call__` roda antes da checagem de cadencia e
nao depende dela. A ordem nao e estilo: e a protecao.

## Horizonte -> largura do stop

O `horizon` que o cerebro devolve desde o passo 5 nao era consumido por
ninguem. Aqui ele escolhe os multiplicadores de ATR:

| Horizonte | Stop | Take |
|---|---|---|
| curto | 2x ATR | 3x ATR |
| medio | 4x ATR | 6x ATR |
| longo | 8x ATR | 12x ATR |

O motivo e a aritmetica medida no passo 6 (secao 11): em spot sem
alavancagem, `tamanho = risco / distancia_do_stop`. Stop apertado exige
posicao grande pra arriscar 1% do capital, e posicao grande estoura o
teto de exposicao. Com os padroes do passo 6, o Risk Engine aprovava 2
de 50 entradas.

Isso nao e um defeito a corrigir -- e uma consequencia coerente do
desenho. Um sistema spot, sem alavancagem, naturalmente penaliza
operacao de horizonte curto: ela pede stop apertado, que pede posicao
grande, que concentra a carteira. A tabela acima nao contorna essa
verdade, ela a torna explicita: quem quer horizonte longo ganha espaco
pro preco respirar; quem quer horizonte curto continua batendo no teto,
como deve.

Os valores do passo 6 (2x/3x) viram o caso "curto" em vez de serem
descartados.
"""

from dataclasses import replace

from backtest.engine import BUY, HOLD, NO_TRADE, SELL
from brain.cadencia import (
    INTERVALO_PADRAO_MS,
    ControleDeCadencia,
    decisao_de_espera,
)
from risk.risk_engine import (
    EstadoDaPosicao,
    ParametrosDeRisco,
    avaliar_risco,
)

# Regra do sistema, documentada na secao 6 -- nao e detalhe de ajuste
# fino. Mudar isto muda o comportamento do sistema inteiro, nao so a
# calibracao de uma rodada.
MULTIPLICADORES_POR_HORIZONTE = {
    "curto": (2.0, 3.0),
    "medio": (4.0, 6.0),
    "longo": (8.0, 12.0),
}
HORIZONTE_PADRAO = "curto"


def parametros_para_horizonte(
    horizonte: str, base: ParametrosDeRisco | None = None
) -> ParametrosDeRisco:
    """
    Troca so os multiplicadores de ATR, preservando risco por operacao e
    teto de exposicao do `base`.

    Horizonte desconhecido cai no mais conservador ("curto", stop mais
    apertado): na duvida sobre quanto espaco dar, dar menos e o erro
    barato.
    """
    base = base or ParametrosDeRisco()
    stop, take = MULTIPLICADORES_POR_HORIZONTE.get(
        horizonte, MULTIPLICADORES_POR_HORIZONTE[HORIZONTE_PADRAO]
    )
    return replace(base, multiplicador_stop=stop, multiplicador_take=take)


class EstrategiaHibrida:
    """
    Callable com memoria: guarda a cadencia, a ultima tese e os niveis de
    stop/take da posicao aberta.

    Os niveis vivem aqui, e nao no motor de backtest, porque o motor e
    agnostico a estrategia de proposito -- ele sabe de caixa e quantidade,
    nao de stop-loss. No caminho ao vivo o equivalente e a tabela
    `portfolio` (via `risk/portfolio_repo.py`); aqui e memoria de
    processo, porque a simulacao inteira roda de uma vez.
    """

    def __init__(
        self,
        analista,
        *,
        simbolo: str = "BTCUSDT",
        intervalo_ms: int = INTERVALO_PADRAO_MS,
        parametros_base: ParametrosDeRisco | None = None,
        ao_falhar: str | None = None,
    ):
        self.analista = analista
        self.simbolo = simbolo
        self.parametros_base = parametros_base or ParametrosDeRisco()
        self.ao_falhar = ao_falhar
        self.controle = ControleDeCadencia(intervalo_ms=intervalo_ms)

        self.niveis: tuple[float, float] | None = None
        self.niveis_pendentes: tuple[float, float] | None = None
        self.ultima_tese = None

        # Contadores de auditoria -- e o que responde "a hibrida operou
        # pouco porque o cerebro nao viu oportunidade, ou porque o risco
        # bloqueou?". Sem isso, os dois casos sao indistinguiveis no
        # resultado final.
        self.consultas = 0
        self.overrides_de_risco = 0
        self.bloqueios_de_risco = 0
        self.horizontes = {}
        self.direcoes_do_llm = {}
        self.__name__ = "hibrida_llm_risk"

    # ------------------------------------------------------------------

    def __call__(self, contexto) -> str:
        self._sincronizar_niveis(contexto)
        posicao = self._posicao(contexto)
        capital = contexto.caixa + contexto.quantidade * contexto.preco_atual

        # ---------- ETAPA 1: stop/take, TODO candle ----------
        # Antes da cadencia, antes de qualquer chamada de API, sem tocar
        # em `contexto.features` (que e a parte cara). So compara preco
        # contra numero ja gravado.
        if posicao.aberta:
            resultado = avaliar_risco(
                tese=self.ultima_tese or HOLD,
                atr_14=None,  # a regra 1 nao usa ATR; a regra 2 nao roda com posicao aberta
                preco_atual=contexto.preco_atual,
                posicao=posicao,
                capital_total=capital,
                parametros=self.parametros_base,
            )
            if resultado.acao_final == SELL:
                if resultado.override_do_llm:
                    self.overrides_de_risco += 1
                self.niveis = None
                return SELL

        # ---------- ETAPA 2: e hora de perguntar ao cerebro? ----------
        agora_ms = contexto.candle_atual["abertura_em"]
        if not self.controle.deve_consultar(agora_ms):
            return decisao_de_espera(posicao.aberta)

        self.controle.registrar_consulta(agora_ms)
        self.consultas += 1

        try:
            tese = self.analista.analisar(
                features=contexto.features,
                simbolo=self.simbolo,
                posicao_aberta=posicao.aberta,
                preco_atual=contexto.preco_atual,
            )
        except Exception:
            if self.ao_falhar is None:
                raise
            return self.ao_falhar

        self.ultima_tese = tese
        self.horizontes[tese.horizon] = self.horizontes.get(tese.horizon, 0) + 1
        self.direcoes_do_llm[tese.direction] = self.direcoes_do_llm.get(tese.direction, 0) + 1

        # ---------- ETAPA 3: o Risk Engine decide ----------
        parametros = parametros_para_horizonte(tese.horizon, self.parametros_base)
        resultado = avaliar_risco(
            tese=tese,
            atr_14=contexto.features["atr_14"],
            preco_atual=contexto.preco_atual,
            posicao=posicao,
            capital_total=capital,
            parametros=parametros,
        )

        if not resultado.aprovado:
            self.bloqueios_de_risco += 1
        if resultado.override_do_llm:
            self.overrides_de_risco += 1

        if resultado.acao_final == BUY and resultado.aprovado:
            # Os niveis so passam a valer quando a posicao existir de
            # fato -- a ordem so e preenchida na abertura do candle
            # seguinte (ver `backtest/engine.py`).
            self.niveis_pendentes = (resultado.stop_loss, resultado.take_profit)
        elif resultado.acao_final == SELL:
            self.niveis = None

        return resultado.acao_final

    # ------------------------------------------------------------------

    def _sincronizar_niveis(self, contexto) -> None:
        """
        Alinha os niveis guardados com a posicao que o motor realmente
        tem, no inicio de cada candle.

        A defasagem de um candle e real e precisa ser tratada: a decisao
        de comprar nasce no fechamento de `i` e so vira posicao na
        abertura de `i+1`. Enquanto isso os niveis ficam "pendentes" --
        calculados, mas ainda sem posicao pra proteger.
        """
        if contexto.posicao_aberta:
            if self.niveis_pendentes is not None:
                self.niveis = self.niveis_pendentes
                self.niveis_pendentes = None
        else:
            self.niveis = None
            self.niveis_pendentes = None

    def _posicao(self, contexto) -> EstadoDaPosicao:
        stop, take = self.niveis if self.niveis else (None, None)
        return EstadoDaPosicao(
            quantidade=contexto.quantidade,
            preco_entrada=contexto.preco_de_entrada or None,
            stop_loss=stop,
            take_profit=take,
        )

    def resumo_de_auditoria(self) -> dict:
        return {
            "consultas_ao_cerebro": self.consultas,
            "overrides_de_risco": self.overrides_de_risco,
            "bloqueios_de_risco": self.bloqueios_de_risco,
            "horizontes_devolvidos": self.horizontes,
            "direcoes_do_llm": self.direcoes_do_llm,
        }


def criar_estrategia_hibrida(analista, **kwargs) -> EstrategiaHibrida:
    """Fabrica: cada rodada recebe estado proprio, sem vazar entre simulacoes."""
    return EstrategiaHibrida(analista, **kwargs)
