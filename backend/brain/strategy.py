"""
O cerebro empacotado como funcao de estrategia.

Serve pra que o cerebro ja nasca com a assinatura que o motor de
backtest espera -- `ContextoDeDecisao -> BUY | SELL | HOLD | NO_TRADE` --
mesmo antes de existir uma estrategia hibrida de verdade.

**Isto ainda nao e a estrategia hibrida do passo 7.** Falta o Risk
Engine (passo 6). Sem ele o que existe aqui e um LLM solto: uma direcao
sem stop-loss, sem take-profit e sem tamanho de posicao calculados, ou
seja, sem nada que transforme uma opiniao em ordem responsavel. O
passo 7 vai compor esta funcao com o Risk Engine; a assinatura nao muda,
so entra uma camada entre a tese e a decisao final.

Custo: rodar isto num backtest gasta chamada de API de verdade. Com
cadencia de 6h, um ano de candles de 1h da ~1.460 consultas -- ja acima
do limite diario do free tier (secao 8), e por isso o passo 7 vai
precisar decidir periodo e cadencia com essa conta na mao. Um ano
inteiro consultando de hora em hora seriam 8.760.
"""

from brain.cadencia import (
    INTERVALO_PADRAO_MS,
    ControleDeCadencia,
    decisao_de_espera,
)
from brain.llm_analyst import AnalistaLLM


def criar_estrategia_do_cerebro(
    analista: AnalistaLLM | None = None,
    *,
    simbolo: str = "BTCUSDT",
    intervalo_ms: int = INTERVALO_PADRAO_MS,
    ao_falhar: str | None = None,
):
    """
    Devolve uma funcao de estrategia pronta pro motor de backtest.

    E uma fabrica, e nao uma funcao solta, porque a cadencia precisa de
    memoria entre um candle e outro -- e essa memoria fica na closure,
    isolada por rodada. Duas simulacoes criadas por esta fabrica nao
    compartilham estado, o que importa: um contador de "ultima consulta"
    global vazaria de uma rodada pra outra e a segunda comecaria com a
    cadencia ja adiantada.

    `ao_falhar`: o que devolver se a chamada ao modelo der erro (limite
    de requisicao, rede, resposta fora do contrato). None -- o padrao --
    propaga a excecao e interrompe a rodada. E o padrao certo pra
    backtest: uma rodada com metade das consultas engolidas por erro nao
    e um resultado ruim, e um resultado invalido, e continuar em silencio
    o transformaria num numero em que alguem poderia acreditar. Pro
    caminho ao vivo, onde derrubar o ciclo e pior que perder uma
    consulta, passar "NO_TRADE" ou "HOLD" e razoavel.
    """
    analista = analista or AnalistaLLM()
    controle = ControleDeCadencia(intervalo_ms=intervalo_ms)

    def estrategia(contexto):
        # "Agora" e o timestamp do candle sendo avaliado, nunca o relogio
        # da maquina: dentro do backtest o tempo e o do dado, e consultar
        # o relogio aqui faria a cadencia depender de quando a simulacao
        # rodou em vez de quando os candles aconteceram.
        agora_ms = contexto.candle_atual["abertura_em"]

        if not controle.deve_consultar(agora_ms):
            return decisao_de_espera(contexto.posicao_aberta)

        controle.registrar_consulta(agora_ms)

        try:
            tese = analista.analisar(
                features=contexto.features,
                simbolo=simbolo,
                posicao_aberta=contexto.posicao_aberta,
                preco_atual=contexto.preco_atual,
            )
        except Exception:
            if ao_falhar is None:
                raise
            return ao_falhar

        # A direcao do modelo passa direto. BUY com posicao aberta e SELL
        # sem posicao ja sao no-op no motor (spot only, principio 5), e
        # deixar a tese chegar sem maquiagem mantem o registro fiel ao que
        # o cerebro de fato disse -- que e o que o principio 7 vai precisar
        # pra medir confianca declarada contra acerto real.
        return tese.direction

    estrategia.__name__ = "cerebro_llm"
    estrategia.controle_de_cadencia = controle  # exposto pra inspecao/testes
    estrategia.analista = analista
    return estrategia
