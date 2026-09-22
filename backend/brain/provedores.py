"""
Provedores de LLM -- a camada que torna o cerebro portatil.

O passo 5 nasceu amarrado ao Gemini: o SDK, o formato de structured
output e o nome do modelo estavam todos dentro de `llm_analyst.py`.
Funcionava, mas fazia de "trocar de LLM" uma reescrita em vez de uma
variavel de ambiente -- e trocar de LLM e algo que este projeto vai
querer fazer, seja por custo, por cota, ou pra responder "o resultado
ruim e do modelo ou da ideia?".

Aqui cada provedor sabe tres coisas, e so elas:

1. como montar seu cliente a partir de uma chave;
2. como pedir uma resposta que obedeca a um schema Pydantic;
3. como devolver essa resposta ja validada.

Todo o resto -- o prompt, o contrato `TeseDeOperacao`, a cadencia, o
cache, a checagem de confianca -- fica fora e nao muda quando o provedor
muda. E isso que permite comparar dois modelos no MESMO experimento: so
a caixa que gera a tese e diferente.

## Como escolher

    LLM_PROVEDOR=gemini        # padrao
    LLM_PROVEDOR=claude

    LLM_MODELO=...             # opcional, vale para qualquer provedor
    GEMINI_MODELO=...          # alternativa especifica
    CLAUDE_MODELO=...

## Como adicionar um terceiro (OpenAI, Mistral, o que for)

Herde de `ProvedorLLM`, implemente `_criar_cliente` e `gerar`, registre
em `PROVEDORES`. Nao ha nenhum outro ponto de contato -- se for preciso
tocar em outro arquivo pra plugar um provedor novo, a abstracao vazou, e
o vazamento e um bug.

Nao ha um provedor OpenAI aqui de proposito: escrever um sem SDK
instalado e sem chave pra testar seria codigo morto se passando por
recurso. O molde acima e o que falta, e sao ~20 linhas.
"""

import os
from abc import ABC, abstractmethod

from pydantic import BaseModel, ValidationError


class ErroDoProvedor(RuntimeError):
    """Falha ao obter uma resposta valida do modelo."""


class ProvedorLLM(ABC):
    """
    Contrato minimo de um provedor.

    O cliente e criado sob demanda: instanciar um provedor nao pode
    exigir chave de API, senao importar o modulo pra rodar um teste
    offline ja quebraria.
    """

    nome: str = "?"
    modelo_padrao: str = "?"
    variavel_de_chave: str = "?"
    variavel_de_modelo: str = "?"

    def __init__(
        self,
        modelo: str | None = None,
        api_key: str | None = None,
        cliente=None,
        timeout_s: float | None = None,
    ):
        # `timeout_s` e opcional e so vale para o cliente criado aqui. Sem ele
        # o SDK do Gemini espera para sempre (HttpOptions.timeout = None) e o
        # da Anthropic, 600 s com novas tentativas. Quem esta no caminho de
        # algo que nao pode esperar -- o explicador, entre um par e outro do
        # ciclo ao vivo -- passa um valor curto.
        self.timeout_s = timeout_s
        self.modelo = (
            modelo
            or os.environ.get("LLM_MODELO")
            or os.environ.get(self.variavel_de_modelo)
            or self.modelo_padrao
        )
        self._cliente = cliente
        self._api_key = api_key

    @property
    def cliente(self):
        if self._cliente is None:
            chave = self._api_key or os.environ.get(self.variavel_de_chave)
            if not chave:
                raise ErroDoProvedor(
                    f"{self.variavel_de_chave} ausente no ambiente -- necessaria "
                    f"para o provedor {self.nome!r}. Veja backend/.env.example."
                )
            self._cliente = self._criar_cliente(chave)
        return self._cliente

    @abstractmethod
    def _criar_cliente(self, chave: str): ...

    @abstractmethod
    def gerar(self, instrucao_de_sistema: str, prompt: str, schema: type[BaseModel]) -> BaseModel:
        """Devolve uma instancia de `schema` ja validada, ou levanta ErroDoProvedor."""

    def listar_modelos(self) -> list[str]:
        """Nomes que a chave enxerga hoje. Vazio se o provedor nao expuser."""
        return []

    def __repr__(self) -> str:
        return f"<{type(self).__name__} modelo={self.modelo}>"


def _validar_do_texto(texto, schema):
    """
    Ultimo recurso comum aos provedores: validar o texto cru.

    Falha aqui e erro, nunca um valor padrao -- um cerebro que devolve
    HOLD em silencio quando a chamada deu errado e indistinguivel de um
    cerebro que decidiu manter a posicao.
    """
    if not texto:
        raise ErroDoProvedor("o modelo respondeu vazio")
    try:
        return schema.model_validate_json(texto)
    except ValidationError as erro:
        raise ErroDoProvedor(f"resposta fora do contrato: {erro}") from erro


class ProvedorGemini(ProvedorLLM):
    """
    Google Gemini via `google-genai` (o `google-generativeai` e legado).

    Usa `models.generate_content` com `response_schema`, que aceita o
    modelo Pydantic direto e devolve a instancia validada em
    `response.parsed`. O SDK tambem expoe `client.interactions`, mais
    novo, mas la o schema tem que ser serializado na mao e a resposta
    validada na mao, sem ganho pra este uso.
    """

    nome = "gemini"
    modelo_padrao = "gemini-3.1-flash-lite"
    variavel_de_chave = "GEMINI_API_KEY"
    variavel_de_modelo = "GEMINI_MODELO"

    def _criar_cliente(self, chave):
        from google import genai

        if self.timeout_s:
            from google.genai import types

            return genai.Client(
                api_key=chave,
                http_options=types.HttpOptions(timeout=int(self.timeout_s * 1000)),
            )
        return genai.Client(api_key=chave)

    def gerar(self, instrucao_de_sistema, prompt, schema):
        from google.genai import types

        try:
            resposta = self.cliente.models.generate_content(
                model=self.modelo,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=instrucao_de_sistema,
                    response_mime_type="application/json",
                    response_schema=schema,
                    # Temperatura baixa, nao zero: o que se quer e
                    # estabilidade entre ciclos parecidos, nao repeticao.
                    temperature=0.2,
                ),
            )
        except Exception as erro:  # noqa: BLE001 -- o SDK levanta varios tipos
            raise ErroDoProvedor(
                f"chamada ao Gemini falhou: {type(erro).__name__}: {erro}"
            ) from erro

        tese = getattr(resposta, "parsed", None)
        if isinstance(tese, schema):
            return tese
        return _validar_do_texto(getattr(resposta, "text", None), schema)

    def listar_modelos(self):
        return [getattr(modelo, "name", "?") for modelo in self.cliente.models.list()]


class ProvedorClaude(ProvedorLLM):
    """
    Anthropic Claude via `anthropic`.

    Structured output usa o helper `messages.parse()` com
    `output_format=<modelo Pydantic>`, que devolve a instancia ja
    validada em `response.parsed_output`.

    Sobre o modelo padrao: fica em `claude-opus-5`, o padrao da
    Anthropic. **Escolher um modelo mais barato e decisao sua, nao do
    codigo** -- para esta tarefa (ler ~10 indicadores e devolver uma
    direcao) o `claude-haiku-4-5` e plausivelmente suficiente e custa
    ~5x menos. Uma variavel resolve:

        CLAUDE_MODELO=claude-haiku-4-5

    Nao existe camada gratuita na API da Anthropic -- e pre-pago.
    """

    nome = "claude"
    modelo_padrao = "claude-opus-5"
    variavel_de_chave = "ANTHROPIC_API_KEY"
    variavel_de_modelo = "CLAUDE_MODELO"

    def _criar_cliente(self, chave):
        import anthropic

        if self.timeout_s:
            return anthropic.Anthropic(api_key=chave, timeout=self.timeout_s, max_retries=1)
        return anthropic.Anthropic(api_key=chave)

    def gerar(self, instrucao_de_sistema, prompt, schema):
        try:
            resposta = self.cliente.messages.parse(
                model=self.modelo,
                # A tese sao ~130 tokens, mas o Opus 5 pensa por padrao e
                # o raciocinio conta contra este teto. Folga aqui e
                # barata; estourar o teto trunca a resposta no meio.
                max_tokens=8192,
                system=instrucao_de_sistema,
                messages=[{"role": "user", "content": prompt}],
                output_format=schema,
            )
        except Exception as erro:  # noqa: BLE001
            raise ErroDoProvedor(
                f"chamada ao Claude falhou: {type(erro).__name__}: {erro}"
            ) from erro

        # Recusa por politica volta com HTTP 200 e stop_reason 'refusal'.
        # Checar antes de ler o conteudo separa "o modelo se recusou" de
        # "o modelo respondeu errado" -- causas diferentes, tratamentos
        # diferentes.
        if getattr(resposta, "stop_reason", None) == "refusal":
            detalhes = getattr(resposta, "stop_details", None)
            raise ErroDoProvedor(
                f"o modelo recusou a requisicao "
                f"(categoria: {getattr(detalhes, 'category', '?')})"
            )

        tese = getattr(resposta, "parsed_output", None)
        if isinstance(tese, schema):
            return tese

        texto = next(
            (
                bloco.text
                for bloco in getattr(resposta, "content", [])
                if getattr(bloco, "type", "") == "text"
            ),
            None,
        )
        return _validar_do_texto(texto, schema)

    def listar_modelos(self):
        return [modelo.id for modelo in self.cliente.models.list()]


PROVEDORES: dict[str, type[ProvedorLLM]] = {
    ProvedorGemini.nome: ProvedorGemini,
    ProvedorClaude.nome: ProvedorClaude,
}

PROVEDOR_PADRAO = "gemini"


def criar_provedor(
    nome: str | None = None,
    modelo: str | None = None,
    api_key: str | None = None,
    cliente=None,
    timeout_s: float | None = None,
) -> ProvedorLLM:
    """
    Monta o provedor pedido, ou o de `LLM_PROVEDOR`, ou o padrao.

    Nome desconhecido e erro imediato e explicito: um typo em
    `LLM_PROVEDOR` caindo em silencio no Gemini faria uma rodada inteira
    rodar no modelo errado e depois ser comparada como se fosse do outro.
    """
    # Um `nome` passado explicitamente e sempre respeitado, mesmo vazio:
    # quem chamou quis dizer alguma coisa, e "" nao e um provedor. Ja um
    # `LLM_PROVEDOR=` em branco no .env e a forma normal de dizer "nao
    # configurei isso" -- ai o padrao vale.
    if nome is None:
        nome = (os.environ.get("LLM_PROVEDOR") or "").strip() or PROVEDOR_PADRAO

    escolhido = nome.strip().lower()
    if escolhido not in PROVEDORES:
        raise ErroDoProvedor(
            f"provedor {nome!r} desconhecido; disponiveis: {sorted(PROVEDORES)}"
        )
    return PROVEDORES[escolhido](
        modelo=modelo, api_key=api_key, cliente=cliente, timeout_s=timeout_s
    )
