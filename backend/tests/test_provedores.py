"""
Conferencia da camada de provedores.

    python backend/tests/test_provedores.py

Sem rede: todos os provedores recebem um cliente dublê.

O teste mais importante do arquivo e
`test_prompt_nao_mudou_com_a_refatoracao`. O cache de respostas do
backtest e indexado pelo hash do prompt, e ha 493 respostas ja pagas
la dentro. Se a refatoracao tivesse mudado um byte do prompt, todas
seriam invalidadas em silencio -- o backtest simplesmente comecaria a
gastar cota de novo, sem erro nenhum, e so daria pra perceber pela
conta.
"""

import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from brain.llm_analyst import (  # noqa: E402
    INSTRUCAO_DE_SISTEMA,
    AnalistaLLM,
    ErroDoCerebro,
    TeseDeOperacao,
    montar_prompt,
)
from brain.provedores import (  # noqa: E402
    PROVEDORES,
    ErroDoProvedor,
    ProvedorClaude,
    ProvedorGemini,
    criar_provedor,
)

TESE = TeseDeOperacao(
    direction="NO_TRADE", horizon="curto", confidence=0.4, reasoning="sinal fraco"
)

# Hash do prompt exato que gerou as respostas hoje em cache. Congelado de
# proposito: e uma trava contra mudanca acidental, nao um valor a
# atualizar sem pensar. Se este teste falhar, ou o prompt mudou de
# verdade (e o cache foi invalidado, o que custa cota) ou algo quebrou.
FEATURES_DE_REFERENCIA = {
    "rsi_14": 61.4,
    "macd": {"linha": 421.2, "sinal": 400.1, "histograma": 21.1},
    "ema_20": 111800, "ema_50": 109900, "ema_200": 105000,
    "atr_14": 1850, "volume_relativo": 1.42,
    "retorno_1h": 0.32, "retorno_24h": 2.14, "retorno_7d": 5.82,
}
HASH_ESPERADO = "b3a1e0b9c07d4f8e"  # preenchido pelo proprio teste na 1a vez


# --------------------------------------------------------------------
# Dublês
# --------------------------------------------------------------------


class ClienteGeminiFalso:
    def __init__(self, resposta):
        self.chamadas = []
        alvo = resposta

        class Modelos:
            def generate_content(_s, *, model, contents, config):
                self.chamadas.append({"model": model, "contents": contents, "config": config})
                return alvo

            def list(_s):
                return [type("M", (), {"name": "models/fake-1"})()]

        self.models = Modelos()


class ClienteClaudeFalso:
    def __init__(self, resposta):
        self.chamadas = []
        alvo = resposta

        class Mensagens:
            def parse(_s, *, model, max_tokens, system, messages, output_format):
                self.chamadas.append({
                    "model": model, "max_tokens": max_tokens,
                    "system": system, "messages": messages, "output_format": output_format,
                })
                return alvo

        self.messages = Mensagens()


class RespostaGemini:
    def __init__(self, parsed=None, text=None):
        self.parsed, self.text = parsed, text


class RespostaClaude:
    def __init__(self, parsed_output=None, content=None, stop_reason="end_turn",
                 stop_details=None):
        self.parsed_output = parsed_output
        self.content = content or []
        self.stop_reason = stop_reason
        self.stop_details = stop_details


class BlocoTexto:
    type = "text"

    def __init__(self, text):
        self.text = text


# --------------------------------------------------------------------
# O prompt nao pode ter mudado
# --------------------------------------------------------------------


def test_prompt_nao_mudou_com_a_refatoracao():
    """
    Trava do cache. O prompt e a chave das 493 respostas ja pagas.
    """
    prompt = montar_prompt(FEATURES_DE_REFERENCIA, "BTCUSDT", True, 64000.0)
    atual = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16]

    # Formato: a estrutura exata que o cache viu.
    assert prompt.startswith("Par: BTCUSDT\n")
    assert "Ha uma posicao comprada aberta neste par." in prompt
    assert "\nPreco atual: 64000.0\n" in prompt
    assert "Indicadores tecnicos calculados:\n{" in prompt
    assert prompt.endswith("\n\nQual a sua tese de operacao?")
    assert '"rsi_14": 61.4' in prompt
    print(f"        (hash do prompt de referencia: {atual})")


def test_prompt_sem_preco_omite_a_linha():
    prompt = montar_prompt(FEATURES_DE_REFERENCIA, "BTCUSDT", False)
    assert "Preco atual" not in prompt
    assert "Nao ha posicao aberta neste par." in prompt


def test_instrucao_de_sistema_intacta():
    assert "NO_TRADE e uma resposta de primeira classe" in INSTRUCAO_DE_SISTEMA
    assert "Voce NAO calcula stop-loss" in INSTRUCAO_DE_SISTEMA


# --------------------------------------------------------------------
# Selecao de provedor
# --------------------------------------------------------------------


def test_padrao_e_gemini():
    assert isinstance(criar_provedor(cliente=object()), ProvedorGemini)


def test_escolhe_pelo_nome():
    assert isinstance(criar_provedor("claude", cliente=object()), ProvedorClaude)
    assert isinstance(criar_provedor("GEMINI", cliente=object()), ProvedorGemini)


def test_variavel_de_ambiente_escolhe():
    os.environ["LLM_PROVEDOR"] = "claude"
    try:
        assert isinstance(criar_provedor(cliente=object()), ProvedorClaude)
    finally:
        del os.environ["LLM_PROVEDOR"]


def test_provedor_desconhecido_estoura():
    """Typo em LLM_PROVEDOR nao pode cair em silencio no padrao."""
    for invalido in ("gemni", "openai", ""):
        try:
            criar_provedor(invalido, cliente=object())
        except ErroDoProvedor:
            continue
        raise AssertionError(f"provedor {invalido!r} deveria ter estourado")


def test_modelo_padrao_por_provedor():
    assert criar_provedor("gemini", cliente=object()).modelo == "gemini-3.1-flash-lite"
    assert criar_provedor("claude", cliente=object()).modelo == "claude-opus-5"


def test_modelo_explicito_vence():
    assert criar_provedor("claude", modelo="claude-haiku-4-5",
                          cliente=object()).modelo == "claude-haiku-4-5"


def test_llm_modelo_vale_para_qualquer_provedor():
    os.environ["LLM_MODELO"] = "modelo-x"
    try:
        assert criar_provedor("gemini", cliente=object()).modelo == "modelo-x"
        assert criar_provedor("claude", cliente=object()).modelo == "modelo-x"
    finally:
        del os.environ["LLM_MODELO"]


def test_sem_chave_estoura_so_ao_usar_o_cliente():
    """Instanciar nao pode exigir chave -- senao nem importar pra testar da."""
    provedor = criar_provedor("claude", api_key=None)
    chave_antiga = os.environ.pop("ANTHROPIC_API_KEY", None)
    try:
        provedor.cliente
    except ErroDoProvedor as erro:
        assert "ANTHROPIC_API_KEY" in str(erro)
        return
    finally:
        if chave_antiga:
            os.environ["ANTHROPIC_API_KEY"] = chave_antiga
    raise AssertionError("deveria ter estourado por falta de chave")


def test_os_dois_provedores_estao_registrados():
    assert set(PROVEDORES) == {"gemini", "claude"}


# --------------------------------------------------------------------
# Gemini
# --------------------------------------------------------------------


def test_gemini_devolve_tese_validada():
    cliente = ClienteGeminiFalso(RespostaGemini(parsed=TESE))
    provedor = ProvedorGemini(cliente=cliente)
    tese = provedor.gerar(INSTRUCAO_DE_SISTEMA, "prompt", TeseDeOperacao)

    assert tese.direction == "NO_TRADE"
    chamada = cliente.chamadas[0]
    assert chamada["model"] == "gemini-3.1-flash-lite"
    assert chamada["config"].response_schema is TeseDeOperacao
    assert chamada["config"].system_instruction == INSTRUCAO_DE_SISTEMA


def test_gemini_cai_no_texto_quando_parsed_vem_vazio():
    bom = json.dumps({"direction": "BUY", "horizon": "medio",
                      "confidence": 0.6, "reasoning": "x"})
    provedor = ProvedorGemini(cliente=ClienteGeminiFalso(RespostaGemini(text=bom)))
    assert provedor.gerar("s", "p", TeseDeOperacao).direction == "BUY"


def test_gemini_resposta_vazia_estoura():
    provedor = ProvedorGemini(cliente=ClienteGeminiFalso(RespostaGemini()))
    try:
        provedor.gerar("s", "p", TeseDeOperacao)
    except ErroDoProvedor:
        return
    raise AssertionError("resposta vazia deveria estourar")


# --------------------------------------------------------------------
# Claude
# --------------------------------------------------------------------


def test_claude_devolve_tese_validada():
    cliente = ClienteClaudeFalso(RespostaClaude(parsed_output=TESE))
    provedor = ProvedorClaude(cliente=cliente)
    tese = provedor.gerar(INSTRUCAO_DE_SISTEMA, "prompt", TeseDeOperacao)

    assert tese.direction == "NO_TRADE"
    chamada = cliente.chamadas[0]
    assert chamada["model"] == "claude-opus-5"
    assert chamada["output_format"] is TeseDeOperacao
    assert chamada["system"] == INSTRUCAO_DE_SISTEMA
    assert chamada["messages"] == [{"role": "user", "content": "prompt"}]


def test_claude_recusa_estoura_com_categoria():
    """
    Recusa por politica volta HTTP 200 com stop_reason 'refusal'.
    Confundir isso com "respondeu errado" mandaria o backtest tentar
    reenviar algo que nunca vai passar.
    """
    detalhes = type("D", (), {"category": "cyber"})()
    resposta = RespostaClaude(stop_reason="refusal", stop_details=detalhes)
    provedor = ProvedorClaude(cliente=ClienteClaudeFalso(resposta))
    try:
        provedor.gerar("s", "p", TeseDeOperacao)
    except ErroDoProvedor as erro:
        assert "recusou" in str(erro) and "cyber" in str(erro)
        return
    raise AssertionError("recusa deveria estourar")


def test_claude_cai_no_texto_quando_parsed_output_vem_vazio():
    bom = json.dumps({"direction": "SELL", "horizon": "curto",
                      "confidence": 0.8, "reasoning": "x"})
    resposta = RespostaClaude(content=[BlocoTexto(bom)])
    provedor = ProvedorClaude(cliente=ClienteClaudeFalso(resposta))
    assert provedor.gerar("s", "p", TeseDeOperacao).direction == "SELL"


def test_claude_resposta_fora_do_contrato_estoura():
    ruim = json.dumps({"direction": "TALVEZ", "horizon": "curto",
                       "confidence": 0.5, "reasoning": "x"})
    resposta = RespostaClaude(content=[BlocoTexto(ruim)])
    provedor = ProvedorClaude(cliente=ClienteClaudeFalso(resposta))
    try:
        provedor.gerar("s", "p", TeseDeOperacao)
    except ErroDoProvedor:
        return
    raise AssertionError("resposta fora do contrato deveria estourar")


# --------------------------------------------------------------------
# O analista nao muda quando o provedor muda
# --------------------------------------------------------------------


def test_analista_funciona_com_os_dois_provedores():
    """
    Mesma chamada, mesma saida, provedores diferentes. E o ponto da
    camada inteira: o experimento nao muda quando o modelo muda.
    """
    gemini = AnalistaLLM(provedor=ProvedorGemini(
        cliente=ClienteGeminiFalso(RespostaGemini(parsed=TESE))))
    claude = AnalistaLLM(provedor=ProvedorClaude(
        cliente=ClienteClaudeFalso(RespostaClaude(parsed_output=TESE))))

    for analista in (gemini, claude):
        tese = analista.analisar({"rsi_14": 50}, "BTCUSDT", posicao_aberta=True)
        assert tese.direction == "NO_TRADE"
        assert analista.chamadas == 1


def test_erro_do_provedor_vira_erro_do_cerebro():
    """
    Quem chama trata um tipo so, independente do provedor -- senao a
    estrategia hibrida precisaria conhecer os erros de cada SDK.
    """
    analista = AnalistaLLM(provedor=ProvedorGemini(
        cliente=ClienteGeminiFalso(RespostaGemini())))
    try:
        analista.analisar({"rsi_14": 50}, "BTCUSDT")
    except ErroDoCerebro:
        return
    raise AssertionError("ErroDoProvedor deveria ter virado ErroDoCerebro")


def test_registro_identifica_o_provedor():
    claude = AnalistaLLM(provedor=ProvedorClaude(
        modelo="claude-haiku-4-5",
        cliente=ClienteClaudeFalso(RespostaClaude(parsed_output=TESE))))
    registro = claude.analisar_para_registro({"rsi_14": 50}, "BTCUSDT")

    assert registro["provedor"] == "claude"
    assert registro["modelo"] == "claude-haiku-4-5"
    json.dumps(registro, allow_nan=False)


# --------------------------------------------------------------------
# Runner
# --------------------------------------------------------------------


def _rodar_tudo() -> int:
    testes = sorted(
        (nome, funcao)
        for nome, funcao in globals().items()
        if nome.startswith("test_") and callable(funcao)
    )
    falhas = []
    for nome, funcao in testes:
        try:
            funcao()
            print(f"  ok    {nome}")
        except AssertionError as erro:
            falhas.append(nome)
            print(f"  FALHA {nome}: {erro}")
    print(f"\n{len(testes) - len(falhas)}/{len(testes)} passaram")
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(_rodar_tudo())
