"""
Preenchimento simulado -- passo 8a.

O forward test decide de verdade, mas quem preenche a ordem somos nos, ao
preco real de mercado. Este modulo e a aritmetica desse preenchimento.

## Por que espelhar o motor de backtest linha a linha

O passo 8a existe pra responder UMA pergunta: *a vantagem medida na secao
11 aparece em dado que o modelo nunca viu?* Essa comparacao so vale se a
unica coisa diferente entre backtest e ao vivo for o dado.

Entao a aritmetica aqui e a mesma de `backtest/engine.py`, de proposito:

- **compra usa TODO o caixa disponivel.** O motor faz
  `quantidade = (caixa - taxa) / preco` e zera o caixa. Ele nao usa o
  `tamanho_posicao` que o Risk Engine calcula -- aquele numero serve pra
  APROVAR ou bloquear a entrada, nao pra dimensiona-la. Dimensionar
  diferente aqui produziria uma curva de capital incomparavel com a que
  gerou os numeros da secao 11, e a comparacao e o unico motivo do
  passo 8a existir.
- **a taxa e a mesma** (`TAXA_PADRAO`), cobrada sobre o caixa na compra e
  sobre o bruto na venda.

Se um dia o motor mudar a aritmetica, este modulo tem que mudar junto --
e ha teste conferindo que os dois dao o mesmo resultado.

## O que NAO e igual, e nao da pra fazer ser

O motor executa na **abertura do candle seguinte** ao sinal. Ao vivo o
cron acorda aos :05 e preenche ao preco daquele instante, ou seja
"abertura do candle seguinte + ~5 min".

Nao da pra eliminar essa diferenca sem esperar uma hora entre decidir e
executar, o que traria problemas piores. Entao ela fica, e fica MEDIDA:
`preco_de_referencia` guarda a abertura do candle em curso e
`deslize_pct` guarda o quanto o preenchimento saiu dela. Se no fim o
deslize for irrelevante, a comparacao com o backtest segue de pe; se for
grande, o numero esta la pra descontar.
"""

from dataclasses import replace

from backtest.engine import TAXA_PADRAO
from live.estado import ContaSimulada


def comprar(
    conta: ContaSimulada,
    preco: float,
    stop_loss: float,
    take_profit: float,
    taxa_por_operacao: float = TAXA_PADRAO,
) -> tuple[ContaSimulada, dict]:
    """
    Entra na posicao com todo o caixa, como o motor de backtest faz.

    Devolve a conta nova e o registro do preenchimento. Nao grava nada --
    quem persiste e o ciclo, numa escrita atomica so.
    """
    if conta.quantidade > 0:
        raise ValueError(
            f"{conta.par} ja esta posicionada -- comprar de novo dobraria "
            f"exposicao. Este caso deveria ter sido barrado antes."
        )
    if conta.caixa <= 0:
        raise ValueError(f"{conta.par} sem caixa para comprar")
    if stop_loss is None or stop_loss <= 0:
        raise ValueError(
            f"recusando comprar {conta.par} sem stop-loss -- a posicao "
            f"ficaria invisivel para a regra 1 do Risk Engine"
        )

    taxa = conta.caixa * taxa_por_operacao
    quantidade = (conta.caixa - taxa) / preco

    nova = replace(
        conta,
        caixa=0.0,
        quantidade=quantidade,
        preco_entrada=preco,
        stop_loss=stop_loss,
        take_profit=take_profit,
    )
    preenchimento = {
        "lado": "BUY",
        "preco": preco,
        "quantidade": quantidade,
        "taxa": taxa,
        "caixa_depois": 0.0,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "simulado": True,
    }
    return nova, preenchimento


def vender(
    conta: ContaSimulada,
    preco: float,
    motivo: str,
    taxa_por_operacao: float = TAXA_PADRAO,
) -> tuple[ContaSimulada, dict]:
    """Sai da posicao inteira, como o motor de backtest faz."""
    if conta.quantidade <= 0:
        raise ValueError(f"{conta.par} nao esta posicionada -- nada a vender")

    bruto = conta.quantidade * preco
    taxa = bruto * taxa_por_operacao
    caixa = bruto - taxa

    # O resultado da operacao so e conhecido na saida, e e o que responde
    # "essa entrada valeu a pena?". Guardar aqui evita ter que reconstruir
    # depois cruzando duas linhas de `decisions`.
    #
    # O custo da entrada INCLUI a taxa de compra. A primeira versao usava
    # `quantidade * entrada`, que e so o preco pago pelos ativos -- e deixava
    # de fora a taxa. Resultado: toda operacao aparecia ~0,1% melhor do que
    # foi, e o motor de backtest (que usa o caixa inteiro gasto na entrada)
    # divergia do forward test justamente no numero que os compara. Achado
    # porque a pagina Carteira mostrou realizado de -33,12 com patrimonio em
    # -90,82 e nenhuma posicao aberta: a diferenca era a soma das 6 taxas.
    #
    # A compra e sempre com o caixa inteiro (`comprar`), entao
    # quantidade = caixa * (1 - taxa) / preco, e o caixa gasto e
    # quantidade * preco / (1 - taxa). Exato, sem precisar gravar o custo.
    entrada = conta.preco_entrada
    resultado = None
    resultado_pct = None
    if entrada:
        custo_da_entrada = conta.quantidade * entrada / (1.0 - taxa_por_operacao)
        resultado = caixa - custo_da_entrada
        # liquido de taxas, como o resultado -- o percentual bruto do preco
        # contava uma historia melhor do que a do caixa
        resultado_pct = resultado / custo_da_entrada * 100.0

    nova = replace(
        conta,
        caixa=caixa,
        quantidade=0.0,
        preco_entrada=None,
        stop_loss=None,
        take_profit=None,
    )
    preenchimento = {
        "lado": "SELL",
        "preco": preco,
        "quantidade": conta.quantidade,
        "taxa": taxa,
        "caixa_depois": caixa,
        "preco_entrada": entrada,
        "resultado": resultado,
        "resultado_pct": resultado_pct,
        "motivo": motivo,
        "simulado": True,
    }
    return nova, preenchimento


def medir_deslize(preco_preenchido: float, preco_de_referencia: float | None) -> dict:
    """
    O quanto o preenchimento ao vivo saiu da abertura do candle -- que e
    onde o backtest teria executado.

    Nao corrige nada; so registra. E o unico jeito de descobrir depois se
    a diferenca de momento de execucao explica alguma divergencia entre o
    forward test e o backtest, em vez de atribui-la a estrategia.
    """
    if not preco_de_referencia:
        return {"preco_de_referencia": None, "deslize_pct": None}
    return {
        "preco_de_referencia": preco_de_referencia,
        "deslize_pct": (preco_preenchido / preco_de_referencia - 1.0) * 100.0,
    }
