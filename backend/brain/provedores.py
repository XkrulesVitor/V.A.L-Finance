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

import json
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass

from pydantic import BaseModel, ValidationError


class ErroDoProvedor(RuntimeError):
    """Falha ao obter uma resposta valida do modelo."""


@dataclass
class RespostaBruta:
    """
    Uma tentativa, com tudo o que a auditoria do painel precisa -- inclusive
    quando falha. `tipo_erro` separa o que e normal em modelo gratis
    (`transitoria`: 429 do upstream, 5xx, timeout) do que exige gente
    (`configuracao`: chave, pagamento, politica de dados) e do que tira so
    aquele modelo do dia (`modelo`: 404, instrucao de sistema recusada).
    `conta_diaria` e a cota de modelos gratis da conta OpenRouter esgotada.
    """

    ok: bool
    texto: str | None = None
    http_status: int | None = None
    modelo_efetivo: str | None = None
    id_geracao: str | None = None
    tokens_entrada: int | None = None
    tokens_saida: int | None = None
    tokens_raciocinio: int | None = None
    limit_source: str | None = None
    erro: str | None = None
    tipo_erro: str | None = None    # transitoria | modelo | configuracao | conta_diaria | bug
    retry_after: float | None = None


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

    def chamar_bruto(self, sistema, usuario, forma="sistema", schema=None,
                     temperature=0.2, max_tokens=4000, json_objeto=True) -> RespostaBruta:
        """
        Uma tentativa, sem nova tentativa e sem validar -- quem chama (o
        painel) grava tudo e decide. `forma="embutido"` junta sistema e
        usuario numa mensagem so, para modelos que recusam instrucao de
        sistema (candidato: Gemma pela API do Google). Os Gemma nao recebem
        `response_schema`: o JSON vai descrito no texto.
        """
        from google.genai import types

        config = {"temperature": temperature, "max_output_tokens": max_tokens}
        if forma == "sistema":
            config["system_instruction"] = sistema
            conteudo = usuario
        else:
            conteudo = f"{sistema}\n\n{usuario}"
        if json_objeto and schema is not None and not self.modelo.startswith("gemma"):
            config.update(response_mime_type="application/json", response_schema=schema)
        # O cliente e resolvido FORA do try: chave ausente (secret nao criado
        # no GitHub vira string vazia) e erro de configuracao, nao falha
        # transitoria -- senao a vaga fica muda com o job verde.
        try:
            cliente = self.cliente
        except ErroDoProvedor as erro:
            return RespostaBruta(False, erro=str(erro)[:500], tipo_erro="configuracao")
        try:
            resposta = cliente.models.generate_content(
                model=self.modelo, contents=conteudo, config=types.GenerateContentConfig(**config))
        except Exception as erro:  # noqa: BLE001
            codigo = getattr(erro, "code", None) or getattr(erro, "status_code", None)
            texto = f"{type(erro).__name__}: {erro}"
            return RespostaBruta(False, http_status=codigo if isinstance(codigo, int) else None,
                                 erro=texto[:500], tipo_erro=_classificar(codigo, texto))
        uso = getattr(resposta, "usage_metadata", None)
        return RespostaBruta(
            True, texto=getattr(resposta, "text", None), http_status=200, modelo_efetivo=self.modelo,
            id_geracao=getattr(resposta, "response_id", None),
            tokens_entrada=getattr(uso, "prompt_token_count", None),
            tokens_saida=getattr(uso, "candidates_token_count", None),
            tokens_raciocinio=getattr(uso, "thoughts_token_count", None),
        )


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


class ProvedorOpenRouter(ProvedorLLM):
    """
    OpenRouter: uma API so para centenas de modelos, via HTTP simples.

    ## Gratis por construcao

    O projeto e 100% gratuito, e a chave e de plano gratuito (0 creditos).
    Por isso este provedor RECUSA qualquer modelo cujo id nao termine em
    ":free" -- um typo em `OPENROUTER_MODELO` nao pode virar cobranca, nem
    uma chamada que falha por falta de credito e parece "modelo fora do
    ar". Para liberar modelo pago e preciso dizer isso explicitamente
    (`OPENROUTER_PERMITIR_PAGO=1`).

    ## Modelos gratis sao instaveis

    Medido em 24/09/2026: de 4 modelos :free chamados em sequencia, 3
    devolveram 429 "temporarily rate-limited upstream" e so um respondeu.
    Duas defesas, nesta ordem:

    1. `reservas`: o OpenRouter aceita uma lista em `models` e tenta a
       proxima se a primeira falhar, no mesmo pedido. O modelo que
       respondeu de fato volta no campo `model` e fica em
       `ultimo_modelo`, para a auditoria nao confundir quem votou.
    2. nova tentativa com espera curta em 429/5xx, poucas vezes: o job do
       GitHub tem 15 minutos, e esperar muito aqui atrasa o par seguinte.

    ## Saida estruturada

    Poucos modelos gratis aceitam `json_schema`; quase todos aceitam
    `json_object` ou nada. Entao o schema vai escrito na instrucao, a
    resposta e pedida como objeto JSON, e o texto e validado pelo
    Pydantic -- com a mesma regra dos outros provedores: fora do contrato
    e erro, nunca um valor padrao.
    """

    nome = "openrouter"
    modelo_padrao = "nvidia/nemotron-3-super-120b-a12b:free"
    variavel_de_chave = "OPENROUTER_API_KEY"
    variavel_de_modelo = "OPENROUTER_MODELO"

    URL = "https://openrouter.ai/api/v1/chat/completions"
    TENTATIVAS = 3
    ESPERA_S = 4.0

    def __init__(self, *args, reservas: list[str] | None = None, esperar=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.reservas = list(reservas or [])
        self.ultimo_modelo: str | None = None
        self._esperar = esperar or __import__("time").sleep
        pago = [m for m in [self.modelo, *self.reservas] if not m.endswith(":free")]
        if pago and os.environ.get("OPENROUTER_PERMITIR_PAGO") != "1":
            raise ErroDoProvedor(
                f"modelo(s) pago(s) recusado(s): {pago}. O projeto e gratuito; "
                f"use ids terminando em ':free' ou defina OPENROUTER_PERMITIR_PAGO=1."
            )

    def _criar_cliente(self, chave):
        import httpx

        return httpx.Client(
            timeout=self.timeout_s or 60.0,
            headers={
                "Authorization": f"Bearer {chave}",
                "Content-Type": "application/json",
                # Identificacao opcional que o OpenRouter usa no painel dele.
                "X-Title": "V.A.L Finance",
            },
        )

    def gerar(self, instrucao_de_sistema, prompt, schema):
        instrucao = (
            f"{instrucao_de_sistema}\n\nResponda APENAS com um objeto JSON valido, sem texto "
            f"antes ou depois e sem bloco de codigo, seguindo este JSON Schema:\n"
            f"{json.dumps(schema.model_json_schema(), ensure_ascii=False)}"
        )
        corpo = {
            "model": self.modelo,
            "messages": [
                {"role": "system", "content": instrucao},
                {"role": "user", "content": prompt},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.2,
            # Modelos que "pensam" gastam o teto no raciocinio; folga aqui
            # e gratis, e estourar trunca o JSON no meio.
            "max_tokens": 2000,
        }
        if self.reservas:
            corpo["models"] = [self.modelo, *self.reservas]

        ultimo_erro = None
        for tentativa in range(1, self.TENTATIVAS + 1):
            try:
                resposta = self.cliente.post(self.URL, json=corpo)
            except Exception as erro:  # noqa: BLE001 -- timeout, rede
                ultimo_erro = f"{type(erro).__name__}: {erro}"
            else:
                if resposta.status_code == 200:
                    dados = resposta.json()
                    if dados.get("error"):
                        ultimo_erro = f"erro no corpo: {str(dados['error'])[:300]}"
                    else:
                        self.ultimo_modelo = dados.get("model") or self.modelo
                        escolha = (dados.get("choices") or [{}])[0]
                        texto = (escolha.get("message") or {}).get("content")
                        return _validar_do_texto(_extrair_json(texto), schema)
                elif resposta.status_code in (408, 429, 500, 502, 503, 504):
                    ultimo_erro = f"HTTP {resposta.status_code}: {resposta.text[:300]}"
                else:
                    raise ErroDoProvedor(
                        f"chamada ao OpenRouter falhou: HTTP {resposta.status_code}: "
                        f"{resposta.text[:300]}"
                    )
            if tentativa < self.TENTATIVAS:
                self._esperar(self.ESPERA_S * tentativa)
        raise ErroDoProvedor(
            f"OpenRouter sem resposta depois de {self.TENTATIVAS} tentativas "
            f"({self.modelo}): {ultimo_erro}"
        )

    def listar_modelos(self):
        resposta = self.cliente.get("https://openrouter.ai/api/v1/models")
        return [m["id"] for m in resposta.json().get("data", []) if m["id"].endswith(":free")]

    def chamar_bruto(self, sistema, usuario, forma="sistema", schema=None,
                     temperature=0.2, max_tokens=4000, json_objeto=True) -> RespostaBruta:
        """
        Uma requisicao a UM modelo, sem o campo `models` de fallback e sem
        nova tentativa: o painel controla a cadeia e grava cada tentativa.
        (Em 24/09 o fallback do OpenRouter tentou o 2o da lista numa
        requisicao e devolveu 429 sem tentar os outros em outra.)
        """
        if forma == "sistema":
            mensagens = [{"role": "system", "content": sistema}, {"role": "user", "content": usuario}]
        else:
            mensagens = [{"role": "user", "content": f"{sistema}\n\n{usuario}"}]
        corpo = {"model": self.modelo, "messages": mensagens, "temperature": temperature,
                 "max_tokens": max_tokens}
        if json_objeto:
            corpo["response_format"] = {"type": "json_object"}
        try:
            cliente = self.cliente   # ver ProvedorGemini.chamar_bruto
        except ErroDoProvedor as erro:
            return RespostaBruta(False, erro=str(erro)[:500], tipo_erro="configuracao")
        try:
            resposta = cliente.post(self.URL, json=corpo)
        except Exception as erro:  # noqa: BLE001 -- timeout, rede
            return RespostaBruta(False, erro=f"{type(erro).__name__}: {erro}"[:500], tipo_erro="transitoria")

        status = resposta.status_code
        if status == 200:
            dados = resposta.json()
            if dados.get("error"):
                erro = dados["error"]
                codigo = erro.get("code") if isinstance(erro, dict) else None
                texto = json.dumps(erro, ensure_ascii=False)[:500]
                return RespostaBruta(False, http_status=200, erro=texto,
                                     tipo_erro=_classificar(codigo if isinstance(codigo, int) else 500, texto))
            escolha = (dados.get("choices") or [{}])[0]
            uso = dados.get("usage") or {}
            return RespostaBruta(
                True, texto=(escolha.get("message") or {}).get("content"), http_status=200,
                modelo_efetivo=dados.get("model") or self.modelo, id_geracao=dados.get("id"),
                tokens_entrada=uso.get("prompt_tokens"), tokens_saida=uso.get("completion_tokens"),
                tokens_raciocinio=(uso.get("completion_tokens_details") or {}).get("reasoning_tokens"),
            )

        texto = resposta.text[:500]
        try:
            metadados = ((resposta.json() or {}).get("error") or {}).get("metadata") or {}
        except Exception:  # noqa: BLE001
            metadados = {}
        limite = metadados.get("limit_source") or ("upstream" if "upstream" in texto.lower() else None)
        espera = resposta.headers.get("Retry-After") if getattr(resposta, "headers", None) else None
        try:
            espera = float(espera) if espera is not None else None
        except ValueError:
            espera = None
        return RespostaBruta(False, http_status=status, erro=texto, limit_source=limite,
                             tipo_erro=_classificar(status, texto), retry_after=espera)


def _classificar(codigo, texto: str) -> str:
    """Que tipo de falha e esta. Ver `RespostaBruta.tipo_erro`."""
    t = (texto or "").lower()
    if codigo == 429:
        # A cota diaria de modelos gratis da CONTA (nao do upstream) para o
        # OpenRouter ate a virada do dia; o 429 do upstream e so congestao.
        return "conta_diaria" if ("per-day" in t or "per day" in t) and "upstream" not in t else "transitoria"
    if codigo in (408, 500, 502, 503, 504) or codigo is None:
        return "transitoria"
    if codigo in (401, 402, 403):
        return "configuracao"
    if codigo == 404:
        return "configuracao" if "data policy" in t else "modelo"
    if codigo == 400:
        if "instruction" in t or "not supported" in t or "unsupported" in t:
            return "modelo"
        return "bug"
    return "transitoria"


def _extrair_json(texto):
    """
    O primeiro objeto JSON do texto.

    Mesmo pedindo "so JSON", modelos gratis as vezes embrulham a resposta
    num bloco ```json ou poem uma frase antes. Recortar do primeiro "{" ao
    ultimo "}" resolve esses casos sem aceitar resposta que nao tem JSON --
    essa continua virando erro em `_validar_do_texto`.
    """
    if not texto:
        return texto
    inicio, fim = texto.find("{"), texto.rfind("}")
    return texto[inicio : fim + 1] if inicio != -1 and fim > inicio else texto


PROVEDORES: dict[str, type[ProvedorLLM]] = {
    ProvedorGemini.nome: ProvedorGemini,
    ProvedorClaude.nome: ProvedorClaude,
    ProvedorOpenRouter.nome: ProvedorOpenRouter,
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
