"""
Cadencia de consulta ao cerebro -- quando perguntar, e o que fazer entre
uma pergunta e outra.

O cerebro NAO e chamado a cada candle. Sao tres motivos, e nenhum deles
e economia por avareza:

1. **Nao cabe no free tier.** Um ano de candles de 1h sao 8.760 pontos.
   Consultar em cada um seria 8.760 chamadas pra um unico backtest, num
   limite diario da ordem de 1.000 (secao 8). O backtest do passo 7 nao
   rodaria nem uma vez.
2. **A tese nao muda a cada hora.** O cerebro devolve direcao e
   horizonte -- inclusive "longo". Reperguntar de hora em hora a um
   modelo que acabou de dizer "tendencia de alta, horizonte medio" nao
   traz informacao nova, traz variacao de amostragem: o mesmo cenario
   pode receber respostas diferentes so porque o modelo e estocastico.
3. **Operar demais custa caro.** A baseline do passo 4 mediu isso: o
   `ema_crossover` queimou 12,8% do capital inicial so em taxa, fazendo
   78 idas e voltas. Um cerebro reagindo a cada hora operaria mais que
   isso.

Entre consultas a estrategia mantem o que ja estava fazendo -- HOLD se
posicionada, NO_TRADE se de fora. Nao e "nao fazer nada": e a decisao
explicita de manter, que e um dos quatro estados oficiais da secao 6.

## Por que a regra mora num modulo so

A mesma pergunta -- "ja e hora de consultar de novo?" -- vai ser feita
em dois lugares muito diferentes: pela estrategia rodando dentro do
motor de backtest (onde "agora" e o timestamp do candle sendo avaliado,
e o processo vive do inicio ao fim da simulacao) e pelo cron job ao vivo
(onde "agora" e o relogio e o processo morre e nasce a cada ciclo).

Duplicar a regra nesses dois lugares e como ela sai de sincronia: alguem
ajusta o intervalo no backtest, esquece do cron, e a estrategia validada
deixa de ser a estrategia executada. Por isso a decisao e uma funcao
pura -- `deve_consultar(agora, ultima_consulta, intervalo)` -- que nao
guarda estado nem olha relogio. Quem tem o estado passa o estado: o
backtest guarda em memoria, o cron job vai ler da tabela `decisions` a
ultima linha com `llm_output` preenchido.
"""

from dataclasses import dataclass

from backtest.engine import HOLD, NO_TRADE

# 6 horas. Configuravel de fora (parametro em todo lugar que usa, e
# GEMINI_INTERVALO_HORAS no ambiente pro caminho ao vivo) e nao fixo no
# codigo: e um numero a calibrar no passo 7, comparando o resultado do
# backtest hibrido em cadencias diferentes, e nao uma verdade descoberta.
INTERVALO_PADRAO_HORAS = 6
INTERVALO_PADRAO_MS = INTERVALO_PADRAO_HORAS * 60 * 60 * 1000


def deve_consultar(
    agora_ms: int,
    ultima_consulta_ms: int | None,
    intervalo_ms: int = INTERVALO_PADRAO_MS,
) -> bool:
    """
    Ja passou tempo suficiente desde a ultima consulta?

    Funcao pura: nao guarda estado e nao olha o relogio. Os dois
    chamadores tem nocoes diferentes de "agora" (timestamp do candle no
    backtest, relogio de parede no cron job) e guardam a ultima consulta
    em lugares diferentes -- receber os dois como argumento e o que faz
    a mesma regra servir aos dois.

    `ultima_consulta_ms=None` significa "nunca consultou": consulta.
    """
    if ultima_consulta_ms is None:
        return True
    return agora_ms - ultima_consulta_ms >= intervalo_ms


def decisao_de_espera(posicao_aberta: bool) -> str:
    """
    O que a estrategia devolve quando nao e hora de consultar.

    Mantem o que ja estava valendo. Repare que nao existe um quinto
    estado "sem opiniao": o vocabulario da secao 6 tem quatro estados e
    esta funcao devolve um deles. HOLD com posicao aberta e NO_TRADE sem
    posicao dizem exatamente a mesma coisa -- "siga como esta" -- do lado
    certo da carteira.
    """
    return HOLD if posicao_aberta else NO_TRADE


@dataclass
class ControleDeCadencia:
    """
    Guarda o estado da cadencia pra quem vive num processo so -- o caso
    do backtest, onde a simulacao inteira roda de uma vez.

    O cron job ao vivo nao usa isto: o processo dele morre a cada ciclo,
    entao o "ultima consulta" tem que vir da tabela `decisions`, e la a
    chamada certa e a funcao pura `deve_consultar` diretamente.
    """

    intervalo_ms: int = INTERVALO_PADRAO_MS
    ultima_consulta_ms: int | None = None
    consultas: int = 0

    def deve_consultar(self, agora_ms: int) -> bool:
        return deve_consultar(agora_ms, self.ultima_consulta_ms, self.intervalo_ms)

    def registrar_consulta(self, agora_ms: int) -> None:
        self.ultima_consulta_ms = agora_ms
        self.consultas += 1
