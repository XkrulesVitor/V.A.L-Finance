"""
Conferencia da camada de cache e cota do backtest hibrido.

    python backend/tests/test_run_hybrid.py

Sem rede: o analista e um duble que conta chamadas.

## Por que este arquivo existe

`run_hybrid.py` produz TODOS os numeros que a secao 11 do ARCHITECTURE.md
usa pra decidir se o projeto continua. Ate agora ele era o unico modulo
dessa importancia sem teste nenhum -- e a consequencia apareceu na
pratica: a tarefa agendada foi morta no meio de uma gravacao, deixou dois
arquivos de cache cheios de bytes nulos, e a rodada seguinte quebrou com
um `ValidationError` de JSON que nao dizia de onde vinha.

O bug foi corrigido (escrita atomica + descarte de cache ilegivel) mas
ficou sem teste. Estes testes fecham essa divida: `test_cache_corrompido_*`
e `test_escrita_e_atomica` falham na versao antiga do modulo.

O outro grupo cobre a deteccao de cota. Distinguir "cota diaria acabou"
de "muitas requisicoes por minuto" nao e detalhe: confundir os dois fez o
processo esperar 9 minutos com backoff contra um limite que so a virada
do dia resolve.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tempfile  # noqa: E402
from pathlib import Path  # noqa: E402

from backtest.run_hybrid import (  # noqa: E402
    AnalistaComCache,
    CotaDiariaEsgotada,
    SemCache,
    _e_cota_diaria,
    _e_transitorio,
    _gravar_atomico,
)
from brain.llm_analyst import TeseDeOperacao  # noqa: E402

FEATURES = {
    "rsi_14": 55.0, "atr_14": 900.0, "ema_20": 61000.0,
    "ema_50": 60000.0, "ema_200": 58000.0, "volume_relativo": 1.1,
    "retorno_24h": 0.8, "macd": {"histograma": 12.0},
}


class AnalistaDuble:
    """Conta chamadas e devolve sempre a mesma tese."""

    modelo = "modelo-de-teste"

    def __init__(self, erro: Exception | None = None):
        self.chamadas = 0
        self.erro = erro

    def analisar(self, features, simbolo, posicao_aberta=False, preco_atual=None):
        self.chamadas += 1
        if self.erro is not None:
            raise self.erro
        return TeseDeOperacao(
            direction="BUY", horizon="curto", confidence=0.7,
            reasoning="duble de teste",
        )


def _com_pasta():
    return tempfile.TemporaryDirectory()


def _analista(pasta, erro=None, **kwargs):
    duble = AnalistaDuble(erro)
    return duble, AnalistaComCache(duble, Path(pasta), **kwargs)


# ---------------------------------------------------------------- cache

def test_primeira_chamada_vai_na_api_e_grava():
    with _com_pasta() as pasta:
        duble, cache = _analista(pasta)
        cache.analisar(FEATURES, "BTCUSDT", preco_atual=61000.0)
        assert duble.chamadas == 1, "devia ter chamado a API uma vez"
        assert cache.chamadas_reais == 1
        gravados = list(Path(pasta).glob("*.json"))
        assert len(gravados) == 1, f"esperava 1 arquivo, achei {len(gravados)}"


def test_segunda_chamada_igual_usa_cache():
    with _com_pasta() as pasta:
        duble, cache = _analista(pasta)
        a = cache.analisar(FEATURES, "BTCUSDT", preco_atual=61000.0)
        b = cache.analisar(FEATURES, "BTCUSDT", preco_atual=61000.0)
        assert duble.chamadas == 1, "prompt igual nao devia gastar chamada nova"
        assert cache.acertos_de_cache == 1
        assert a.direction == b.direction


def test_preco_diferente_gera_chamada_nova():
    # O preco entra no prompt. Se duas situacoes diferentes colidissem no
    # mesmo hash, o backtest reusaria a tese errada e ninguem veria.
    with _com_pasta() as pasta:
        duble, cache = _analista(pasta)
        cache.analisar(FEATURES, "BTCUSDT", preco_atual=61000.0)
        cache.analisar(FEATURES, "BTCUSDT", preco_atual=62000.0)
        assert duble.chamadas == 2, "preco diferente devia ser chamada nova"


def test_posicao_aberta_gera_chamada_nova():
    # `posicao_aberta` entra no prompt -- e a razao de nao dar pra trocar
    # parametros de risco de graca (secao 15 do ARCHITECTURE.md).
    with _com_pasta() as pasta:
        duble, cache = _analista(pasta)
        cache.analisar(FEATURES, "BTCUSDT", posicao_aberta=False, preco_atual=61000.0)
        cache.analisar(FEATURES, "BTCUSDT", posicao_aberta=True, preco_atual=61000.0)
        assert duble.chamadas == 2, "estado da posicao devia mudar o hash"


def test_modelo_diferente_nao_reusa_resposta():
    # Trocar de provedor nao pode herdar as respostas do anterior, senao a
    # comparacao entre modelos seria contra o cache do outro.
    with _com_pasta() as pasta:
        primeiro, cache_a = _analista(pasta)
        cache_a.analisar(FEATURES, "BTCUSDT", preco_atual=61000.0)
        segundo = AnalistaDuble()
        segundo.modelo = "outro-modelo"
        cache_b = AnalistaComCache(segundo, Path(pasta))
        cache_b.analisar(FEATURES, "BTCUSDT", preco_atual=61000.0)
        assert segundo.chamadas == 1, "modelo diferente devia chamar de novo"


# ------------------------------------------------- cache corrompido (regressao)

def test_cache_corrompido_nao_derruba_a_rodada():
    # Regressao do bug real: a tarefa agendada morreu no meio de uma
    # gravacao e deixou o arquivo cheio de bytes nulos. Na versao antiga
    # isto levantava ValidationError e matava a rodada inteira.
    with _com_pasta() as pasta:
        duble, cache = _analista(pasta)
        cache.analisar(FEATURES, "BTCUSDT", preco_atual=61000.0)
        arquivo = next(Path(pasta).glob("*.json"))
        arquivo.write_bytes(b"\x00" * 300)

        tese = cache.analisar(FEATURES, "BTCUSDT", preco_atual=61000.0)
        assert tese.direction == "BUY", "devia ter refeito a chamada"
        assert duble.chamadas == 2, "arquivo ilegivel devia virar chamada nova"
        assert cache.corrompidos == 1


def test_cache_corrompido_e_reescrito_valido():
    with _com_pasta() as pasta:
        duble, cache = _analista(pasta)
        cache.analisar(FEATURES, "BTCUSDT", preco_atual=61000.0)
        arquivo = next(Path(pasta).glob("*.json"))
        arquivo.write_text("{ truncado", encoding="utf-8")

        cache.analisar(FEATURES, "BTCUSDT", preco_atual=61000.0)
        cache.analisar(FEATURES, "BTCUSDT", preco_atual=61000.0)
        # A terceira ja tem que vir do cache: se o arquivo refeito tivesse
        # ficado invalido, o contador de corrompidos passaria de 1.
        assert cache.corrompidos == 1, "o arquivo refeito devia ser legivel"
        assert duble.chamadas == 2


def test_escrita_e_atomica():
    # `write_text` direto deixa arquivo pela metade se o processo morrer.
    # `_gravar_atomico` grava num temporario e renomeia -- ou existe
    # inteiro, ou nao existe.
    with _com_pasta() as pasta:
        destino = Path(pasta) / "x.json"
        _gravar_atomico(destino, '{"direction":"BUY"}')
        assert destino.read_text(encoding="utf-8") == '{"direction":"BUY"}'
        assert not list(Path(pasta).glob("*.tmp")), "temporario devia ter sumido"


# ----------------------------------------------------------------- cota

def test_cota_diaria_para_na_hora():
    erro = RuntimeError(
        "429 RESOURCE_EXHAUSTED: quota exceeded for "
        "GenerateRequestsPerDayPerProjectPerModel-FreeTier"
    )
    with _com_pasta() as pasta:
        duble, cache = _analista(pasta, erro=erro, tentativas=8)
        try:
            cache.analisar(FEATURES, "BTCUSDT", preco_atual=61000.0)
        except CotaDiariaEsgotada:
            pass
        else:
            raise AssertionError("devia ter levantado CotaDiariaEsgotada")
        assert duble.chamadas == 1, (
            f"cota diaria nao se resolve com reenvio; chamou {duble.chamadas}x"
        )


def test_limite_por_minuto_e_diferente_de_cota_diaria():
    assert _e_cota_diaria(RuntimeError("PerDayPerProject quota exceeded"))
    assert not _e_cota_diaria(RuntimeError("429 too many requests per minute"))


def test_indisponibilidade_e_transitoria():
    assert _e_transitorio(RuntimeError("503 UNAVAILABLE: overloaded"))
    assert _e_transitorio(RuntimeError("429 rate limit"))
    assert not _e_transitorio(RuntimeError("400 invalid argument"))


def test_erro_definitivo_sobe_sem_reenvio():
    with _com_pasta() as pasta:
        duble, cache = _analista(pasta, erro=ValueError("400 chave invalida"))
        try:
            cache.analisar(FEATURES, "BTCUSDT", preco_atual=61000.0)
        except ValueError:
            pass
        else:
            raise AssertionError("erro definitivo devia subir")
        assert duble.chamadas == 1, "nao devia reenviar erro definitivo"


# ------------------------------------------------------------ modo offline

def test_somente_cache_nao_toca_na_api():
    with _com_pasta() as pasta:
        duble, cache = _analista(pasta, somente_cache=True)
        try:
            cache.analisar(FEATURES, "BTCUSDT", preco_atual=61000.0)
        except SemCache:
            pass
        else:
            raise AssertionError("devia ter levantado SemCache")
        assert duble.chamadas == 0, "modo offline nao pode gastar cota"


def test_somente_cache_le_o_que_existe():
    with _com_pasta() as pasta:
        duble, cache = _analista(pasta)
        cache.analisar(FEATURES, "BTCUSDT", preco_atual=61000.0)
        _, offline = _analista(pasta, somente_cache=True)
        offline.analista.modelo = duble.modelo
        tese = offline.analisar(FEATURES, "BTCUSDT", preco_atual=61000.0)
        assert tese.direction == "BUY"
        assert offline.analista.chamadas == 0


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
        except Exception as erro:  # noqa: BLE001
            # Um teste que estoura com KeyError/TypeError e falha igual --
            # e capturar so AssertionError fazia o arquivo inteiro morrer
            # ali, escondendo o resultado de todos os testes seguintes.
            falhas.append(nome)
            print(f"  ERRO  {nome}: {type(erro).__name__}: {erro}")
    print(f"\n{len(testes) - len(falhas)}/{len(testes)} passaram")
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(_rodar_tudo())
