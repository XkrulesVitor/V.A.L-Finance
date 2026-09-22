"""
O LLM que so explica -- a partir de 2026-09-22.

Ate aqui o LLM decidia: lia indicadores e devolvia uma tese de compra ou
venda. Os estudos de setembro/2026 (ARCHITECTURE.md, secao "Votacao
entre estrategias e tendencia diaria") nao acharam evidencia de que ele
acrescente vantagem sobre uma regra -- e os backtests dele estao
contaminados por memorizacao do periodo anterior ao corte do modelo.
Entao a decisao virou deterministica (`estrategia/tendencia_diaria.py`)
e o LLM ficou com o que ele faz bem: traduzir o que aconteceu em uma
frase que qualquer pessoa entende.

## Nunca bloqueia

A explicacao e pedida DEPOIS que a operacao ja foi executada e gravada.
Se o provedor cair, a operacao nao muda -- so fica sem frase. Por isso
`explicar` nunca levanta excecao: devolve o texto ou o motivo da falha.

## Nem trava

"Nao bloquear" nao e so capturar excecao: uma chamada que nunca volta
tambem bloqueia. A explicacao roda dentro do ciclo de um par, e o par
seguinte so e conferido depois dela; sem limite, uma conexao pendurada com
o provedor segurava o outro par ate o job ser morto (15 min). Por isso o
provedor do explicador e criado com `TIMEOUT_S` curto.

## Custo

So e chamado quando ha operacao. A regra faz ~3 operacoes por trimestre
por ativo; com dois ativos isso da poucas chamadas por mes, contra as 8
por dia do cerebro antigo.
"""

import json

from pydantic import BaseModel, Field

TIMEOUT_S = 30.0

INSTRUCAO = (
    "Voce explica operacoes de uma carteira simulada de criptomoedas para "
    "uma pessoa leiga, em portugues do Brasil. Uma ou duas frases curtas. "
    "A decisao ja foi tomada por uma regra fixa: voce nao opina sobre ela, "
    "nao faz previsao de preco e nao recomenda nada. Diga o que a regra viu "
    "e o que fez, usando so os dados recebidos. Sem jargao: em vez de "
    "\"media movel\", diga \"a media dos ultimos N dias\"."
)


class Explicacao(BaseModel):
    texto: str = Field(description="uma ou duas frases, sem previsao e sem recomendacao")


class Explicador:
    def __init__(self, provedor=None):
        self._provedor = provedor

    @property
    def provedor(self):
        # Criado sob demanda: um ciclo sem operacao nao precisa de chave.
        if self._provedor is None:
            from brain.provedores import criar_provedor
            self._provedor = criar_provedor(timeout_s=TIMEOUT_S)
        return self._provedor

    def explicar(self, fatos: dict) -> tuple[str | None, str | None]:
        """(texto, erro). Exatamente um dos dois e None."""
        try:
            prompt = "Operacao executada:\n" + json.dumps(fatos, ensure_ascii=False, indent=1)
            resposta = self.provedor.gerar(INSTRUCAO, prompt, Explicacao)
            texto = (resposta.texto or "").strip()
            return (texto[:500], None) if texto else (None, "resposta vazia")
        except Exception as erro:  # noqa: BLE001 -- explicar nunca derruba o ciclo
            return None, f"{type(erro).__name__}: {erro}"[:300]
