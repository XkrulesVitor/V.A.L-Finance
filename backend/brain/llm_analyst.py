"""
Cerebro (LLM) -- passo 5 do roteiro (secao 10 do ARCHITECTURE.md).

Recebe o JSON de indicadores da Feature Engine e devolve uma tese de
operacao: direcao, horizonte, confianca declarada e justificativa curta.
Nunca recebe candle cru (principio 3) e nunca devolve numero de risco
(principio 2) -- stop-loss e take-profit sao do Risk Engine, no passo 6,
calculados a partir do `atr_14`.

## O contrato e um modelo Pydantic, e isso e proposital

`TeseDeOperacao` faz dois trabalhos ao mesmo tempo. Vai como
`response_schema` na chamada, entao o proprio Gemini so consegue emitir
JSON naquele formato; e valida a resposta do lado de ca, entao um
`confidence: 1.4` ou um `direction: "COMPRAR"` viram erro em vez de
virarem uma ordem. Nao e redundancia: schema do lado do modelo restringe
a geracao, validacao do lado de ca garante a invariante. Sao camadas
diferentes, e a segunda e a que o resto do sistema pode confiar.

## Sobre o provedor

Este modulo nao fala com nenhum SDK. Ele monta o prompt, define o
contrato e valida a resposta; quem conversa com o modelo e um
`ProvedorLLM` (`brain/provedores.py`). Trocar Gemini por Claude e
`LLM_PROVEDOR=claude` no ambiente -- prompt, contrato, cadencia e cache
continuam identicos, que e justamente o que torna dois modelos
comparaveis dentro do mesmo experimento.

`backend/brain/validar_ao_vivo.py --listar-modelos` mostra o que a
chave do provedor ativo enxerga hoje.
"""

import json
from typing import Literal

from pydantic import BaseModel, Field

from brain.provedores import ErroDoProvedor, criar_provedor

DIRECOES = ("BUY", "SELL", "HOLD", "NO_TRADE")
HORIZONTES = ("curto", "medio", "longo")


class TeseDeOperacao(BaseModel):
    """
    A saida do cerebro. Contrato da secao 5 do ARCHITECTURE.md.

    `symbol` nao esta aqui de proposito, embora apareca no contrato
    documentado: quem chama ja sabe qual par mandou analisar, e pedir ao
    modelo que repita o simbolo gasta token e abre a porta pra ele
    devolver um par diferente do perguntado. O campo e anexado por
    `AnalistaLLM.analisar()` ao montar o registro que vai pro
    `llm_output` -- o JSON gravado tem o formato completo.
    """

    direction: Literal["BUY", "SELL", "HOLD", "NO_TRADE"] = Field(
        description=(
            "BUY para abrir ou aumentar posicao; SELL para fechar ou reduzir "
            "posicao existente; HOLD para manter a posicao atual como esta; "
            "NO_TRADE para nao abrir posicao agora."
        )
    )
    horizon: Literal["curto", "medio", "longo"] = Field(
        description="Horizonte sugerido para a operacao."
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description=(
            "Sua confianca declarada nesta tese, de 0 a 1. Seja honesto: "
            "sinal fraco ou contraditorio merece confianca baixa."
        ),
    )
    reasoning: str = Field(
        description=(
            "Justificativa curta, em portugues, no maximo duas frases, "
            "citando os indicadores que sustentam a tese."
        )
    )


INSTRUCAO_DE_SISTEMA = """\
Voce e um analista tecnico de criptomoedas. Recebe indicadores tecnicos
ja calculados de um par e devolve uma tese de operacao no mercado spot.

REGRAS:

1. Voce propoe uma direcao. Voce NAO calcula stop-loss, take-profit nem
   tamanho de posicao -- esses numeros sao calculados por um motor
   deterministico a partir da volatilidade real do ativo, e nao devem
   aparecer na sua resposta.

2. As quatro direcoes possiveis:
   - BUY: abrir ou aumentar posicao.
   - SELL: fechar ou reduzir a posicao existente. Isso e mercado spot:
     SELL so faz sentido se ja existe posicao. Nunca significa vender a
     descoberto.
   - HOLD: ja existe posicao, e a leitura e de mante-la como esta.
   - NO_TRADE: nao existe posicao, e a leitura e de nao abrir uma agora.

3. NO_TRADE e uma resposta de primeira classe, nao um fracasso. Quando o
   quadro for fraco, contraditorio ou lateral, dizer "nao vou apostar
   nisso" e a resposta correta e esperada. Nao force uma direcao para
   parecer util. A maioria das horas de mercado nao oferece uma
   oportunidade clara.

4. `confidence` e sua confianca declarada, nao uma probabilidade
   calculada. Nao infle. Sinal fraco pede numero baixo; indicadores
   apontando para lados opostos pedem numero baixo.

5. Indicador com valor `null` significa que nao ha historico suficiente
   para calcula-lo, nao que ele vale zero. Nao raciocine em cima de
   `null`; apenas trabalhe com menos informacao e reflita isso na
   confianca.

6. Responda em portugues, e em no maximo duas frases no `reasoning`.\
"""


class ErroDoCerebro(RuntimeError):
    """Falha ao obter uma tese valida do modelo."""


class AnalistaLLM:
    """
    Fachada do cerebro. Um objeto por processo -- o cliente do SDK e
    reaproveitavel e criar um por chamada e desperdicio.

    Nao fala com nenhum SDK diretamente: delega pra um `ProvedorLLM`
    (ver `brain/provedores.py`). Trocar Gemini por Claude e uma variavel
    de ambiente (`LLM_PROVEDOR`), nao uma alteracao aqui -- o prompt, o
    contrato, a cadencia e o cache continuam identicos, que e o que
    torna dois modelos comparaveis no mesmo experimento.

    `provedor` e `cliente` existem pra injetar dublê nos testes: da pra
    exercitar prompt, validacao e tratamento de erro sem gastar chamada
    de API nem depender de rede.
    """

    def __init__(
        self,
        modelo: str | None = None,
        api_key: str | None = None,
        cliente=None,
        provedor=None,
    ):
        self.provedor = provedor or criar_provedor(
            modelo=modelo, api_key=api_key, cliente=cliente
        )
        self.chamadas = 0

    @property
    def modelo(self) -> str:
        return self.provedor.modelo

    @property
    def cliente(self):
        """O cliente do SDK por baixo -- criado sob demanda pelo provedor."""
        return self.provedor.cliente

    def analisar(
        self,
        features: dict,
        simbolo: str,
        posicao_aberta: bool = False,
        preco_atual: float | None = None,
    ) -> TeseDeOperacao:
        """
        Manda as features pro modelo e devolve a tese validada.

        `posicao_aberta` vai junto porque sem isso metade do vocabulario
        nao faz sentido: HOLD e "manter a posicao atual" e SELL e "fechar
        a posicao existente" -- um modelo que nao sabe se ha posicao nao
        tem como escolher entre HOLD e NO_TRADE. Nao viola o principio 3:
        e estado da carteira, nao candle cru.
        """
        prompt = montar_prompt(features, simbolo, posicao_aberta, preco_atual)

        try:
            tese = self.provedor.gerar(INSTRUCAO_DE_SISTEMA, prompt, TeseDeOperacao)
        except ErroDoProvedor as erro:
            # Reempacota como ErroDoCerebro pra que quem chama continue
            # tratando um tipo so, independente do provedor em uso.
            raise ErroDoCerebro(str(erro)) from erro

        self.chamadas += 1
        return tese

    def analisar_para_registro(self, features: dict, simbolo: str, **kwargs) -> dict:
        """
        Mesma analise, mas devolvendo o dicionario pronto pro campo
        `llm_output` (jsonb) da tabela `decisions` -- ja com o `symbol`,
        o provedor e o modelo usados, que e o que torna a linha auditavel
        depois. Sem o provedor, duas rodadas com modelos diferentes
        ficariam indistinguiveis no banco.
        """
        tese = self.analisar(features, simbolo, **kwargs)
        return {
            "symbol": simbolo,
            "provedor": self.provedor.nome,
            "modelo": self.modelo,
            **tese.model_dump(),
        }


def montar_prompt(
    features: dict,
    simbolo: str,
    posicao_aberta: bool,
    preco_atual: float | None = None,
) -> str:
    """
    O prompt: so indicadores e estado da carteira, nunca candle cru.

    As features vao como JSON identado em vez de prosa de proposito --
    e o mesmo formato gravado em `decisions.features`, entao o que o
    modelo viu naquele ciclo e exatamente o que ficou registrado, sem
    tradução no meio.

    Este texto e a chave do cache de respostas do backtest
    (`run_hybrid.py`), entao mudar qualquer byte aqui invalida todas as
    respostas ja pagas. Nao e motivo pra nunca mexer -- e motivo pra
    saber o custo antes.
    """
    estado = (
        "Ha uma posicao comprada aberta neste par."
        if posicao_aberta
        else "Nao ha posicao aberta neste par."
    )
    linha_preco = f"\nPreco atual: {preco_atual}\n" if preco_atual is not None else ""

    return (
        f"Par: {simbolo}\n"
        f"{estado}{linha_preco}\n"
        f"Indicadores tecnicos calculados:\n"
        f"{json.dumps(features, indent=2, ensure_ascii=False, allow_nan=False)}\n\n"
        f"Qual a sua tese de operacao?"
    )
