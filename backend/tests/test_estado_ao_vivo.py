"""
Conferencia do estado do forward test -- passo 8a.

    python backend/tests/test_estado_ao_vivo.py

Sem rede: o cliente do Supabase e um duble que registra as chamadas e
pode ser mandado falhar.

## O que estes testes protegem

`live/estado.py` e a resposta ao risco numero 1 do passo 8a: no backtest
um processo segura tudo em memoria, no cron ele morre a cada ciclo. Os
casos abaixo sao os pontos onde essa transicao pode dar errado, e cada um
deles custa dinheiro de um jeito diferente:

- ler errado e achar que nao ha posicao -> compra dobrada, e o stop da
  posicao real deixa de ser checado;
- gravar pela metade -> posicao sem stop, invisivel pra regra 1;
- rodar duas vezes o mesmo ciclo -> compra dobrada.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from live.estado import (  # noqa: E402
    CAPITAL_INICIAL_PADRAO,
    CandleJaProcessado,
    ContaSimulada,
    ErroDeEstado,
    carregar_conta,
    reivindicar_candle,
    salvar_conta,
    ultima_consulta_ms,
)


class RespostaDuble:
    def __init__(self, data):
        self.data = data


class ConsultaDuble:
    """Encadeia como o cliente do Supabase e devolve o que foi combinado."""

    def __init__(self, tabela, banco):
        self.tabela = tabela
        self.banco = banco
        self._registro = None

    def select(self, colunas):
        self._colunas = colunas
        if self.banco.erro_de_leitura:
            raise RuntimeError(self.banco.erro_de_leitura)
        return self

    def insert(self, registro):
        self._registro = registro
        self._operacao = "insert"
        return self

    def upsert(self, registro, on_conflict=None):
        self._registro = registro
        self._operacao = "upsert"
        return self

    def update(self, campos):
        self._registro = campos
        self._operacao = "update"
        return self

    def eq(self, *_):
        return self

    def neq(self, *_):
        return self

    def limit(self, *_):
        return self

    def order(self, *_, **__):
        return self

    @property
    def not_(self):
        return self

    def is_(self, *_):
        return self

    def execute(self):
        op = getattr(self, "_operacao", "select")
        if op == "select":
            return RespostaDuble(self.banco.linhas.get(self.tabela, []))
        if self.banco.erro_de_escrita:
            raise RuntimeError(self.banco.erro_de_escrita)
        self.banco.escritas.append((self.tabela, op, self._registro))
        if op == "insert":
            return RespostaDuble([{"id": "id-da-linha", **self._registro}])
        return RespostaDuble([self._registro])


class SupabaseDuble:
    def __init__(self, linhas=None, erro_de_leitura=None, erro_de_escrita=None):
        self.linhas = linhas or {}
        self.erro_de_leitura = erro_de_leitura
        self.erro_de_escrita = erro_de_escrita
        self.escritas = []

    def table(self, nome):
        return ConsultaDuble(nome, self)


# ------------------------------------------------------------- leitura

def test_conta_nova_comeca_com_capital_inicial():
    conta = carregar_conta(SupabaseDuble(), "BTCUSDT")
    assert conta.caixa == CAPITAL_INICIAL_PADRAO
    assert conta.quantidade == 0.0
    assert not conta.posicionada


def test_conta_existente_volta_inteira():
    banco = SupabaseDuble({"portfolio": [{
        "asset": "BTCUSDT", "quantity": 0.05, "caixa": 5000.0,
        "preco_entrada": 80000.0, "stop_loss": 78000.0, "take_profit": 84000.0,
    }]})
    conta = carregar_conta(banco, "BTCUSDT")
    assert conta.quantidade == 0.05
    assert conta.caixa == 5000.0
    assert conta.stop_loss == 78000.0
    assert conta.posicionada


def test_falha_de_leitura_nao_vira_conta_vazia():
    # O erro mais perigoso do modulo. Se a leitura falhar e devolvermos
    # uma conta zerada, o sistema compra de novo E para de checar o stop
    # da posicao que existe de verdade.
    banco = SupabaseDuble(erro_de_leitura="conexao caiu")
    try:
        carregar_conta(banco, "BTCUSDT")
    except ErroDeEstado:
        pass
    else:
        raise AssertionError("falha de leitura tinha que levantar, nao degradar")


def test_linha_antiga_sem_caixa_e_recusada():
    # Linha criada antes do passo 8a. Assumir capital inicial inventaria
    # dinheiro; assumir zero inventaria prejuizo. As duas corromperiam a
    # comparacao com o backtest.
    banco = SupabaseDuble({"portfolio": [{
        "asset": "BTCUSDT", "quantity": 0.0, "caixa": None,
        "preco_entrada": None, "stop_loss": None, "take_profit": None,
    }]})
    try:
        carregar_conta(banco, "BTCUSDT")
    except ErroDeEstado as erro:
        assert "caixa" in str(erro)
    else:
        raise AssertionError("linha sem caixa tinha que ser recusada")


def test_coluna_ausente_diz_para_rodar_o_schema():
    banco = SupabaseDuble(erro_de_leitura="42703 column caixa does not exist")
    try:
        carregar_conta(banco, "BTCUSDT")
    except ErroDeEstado as erro:
        assert "schema.sql" in str(erro)
    else:
        raise AssertionError("devia ter apontado o schema.sql")


# -------------------------------------------------------------- escrita

def test_conta_e_gravada_numa_escrita_so():
    # O ponto central: caixa, quantidade e niveis na MESMA escrita. Em
    # duas, uma falha entre elas deixaria posicao sem stop.
    banco = SupabaseDuble()
    conta = ContaSimulada(
        par="BTCUSDT", caixa=100.0, quantidade=0.05,
        preco_entrada=80000.0, stop_loss=78000.0, take_profit=84000.0,
    )
    salvar_conta(banco, conta)
    assert len(banco.escritas) == 1, f"esperava 1 escrita, houve {len(banco.escritas)}"
    _, _, registro = banco.escritas[0]
    for campo in ("quantity", "caixa", "stop_loss", "take_profit", "preco_entrada"):
        assert campo in registro, f"{campo} ficou de fora da escrita atomica"


def test_recusa_gravar_posicao_sem_stop():
    # Guarda de sanidade: uma posicao sem stop e invisivel pra regra 1 do
    # Risk Engine. Gravar tornaria o bug permanente.
    banco = SupabaseDuble()
    conta = ContaSimulada(par="BTCUSDT", caixa=100.0, quantidade=0.05, stop_loss=None)
    try:
        salvar_conta(banco, conta)
    except ErroDeEstado as erro:
        assert "stop_loss" in str(erro)
    else:
        raise AssertionError("posicao sem stop tinha que ser recusada")
    assert banco.escritas == [], "nao podia ter gravado nada"


def test_posicao_zerada_pode_ficar_sem_stop():
    # Sem posicao nao ha o que proteger -- a guarda nao pode atrapalhar
    # o fechamento normal de uma operacao.
    banco = SupabaseDuble()
    salvar_conta(banco, ContaSimulada(par="BTCUSDT", caixa=10500.0, quantidade=0.0))
    assert len(banco.escritas) == 1


# --------------------------------------------------------- idempotencia

def test_candle_novo_e_reivindicado():
    banco = SupabaseDuble()
    id_decisao = reivindicar_candle(banco, "BTCUSDT", 1788490799999)
    assert id_decisao == "id-da-linha"
    _, operacao, registro = banco.escritas[0]
    assert operacao == "insert"
    assert registro["candle_fechamento_em"] == 1788490799999
    assert registro["status"] == "processando"


def test_candle_repetido_levanta_ja_processado():
    # O indice unico do banco recusa. Isso NAO e erro -- e a idempotencia
    # funcionando, e quem chama sai do ciclo sem operar.
    banco = SupabaseDuble(erro_de_escrita='23505 duplicate key value violates unique constraint')
    try:
        reivindicar_candle(banco, "BTCUSDT", 1788490799999)
    except CandleJaProcessado:
        pass
    else:
        raise AssertionError("candle repetido tinha que levantar CandleJaProcessado")


def test_candle_repetido_nao_vira_erro_generico():
    # Se caisse em ErroDeEstado, o ciclo trataria uma execucao duplicada
    # como falha de infraestrutura -- e provavelmente tentaria de novo.
    banco = SupabaseDuble(erro_de_escrita="23505 duplicate key")
    try:
        reivindicar_candle(banco, "BTCUSDT", 123)
    except CandleJaProcessado:
        pass
    except ErroDeEstado:
        raise AssertionError("duplicada nao pode virar ErroDeEstado")


def test_reivindicacao_acontece_antes_de_qualquer_decisao():
    # "Reivindicar e depois trabalhar": a linha entra no banco antes de
    # decidir. Se fosse depois, duas execucoes simultaneas poderiam as
    # duas decidir antes de qualquer uma gravar.
    banco = SupabaseDuble()
    reivindicar_candle(banco, "BTCUSDT", 999)
    tabela, _, registro = banco.escritas[0]
    assert tabela == "decisions"
    assert registro.get("llm_output") is None, "nao pode ter tese ainda"
    assert registro.get("risk_result") is None, "nao pode ter decisao ainda"


# ------------------------------------------------------------- cadencia

def test_sem_consulta_anterior_devolve_none():
    assert ultima_consulta_ms(SupabaseDuble(), "BTCUSDT") is None


def test_ultima_consulta_vem_do_candle():
    banco = SupabaseDuble({"decisions": [
        {"candle_fechamento_em": 1788490799999, "created_at": "2026-09-04T03:00:00+00:00"},
    ]})
    assert ultima_consulta_ms(banco, "BTCUSDT") == 1788490799999


def test_linha_antiga_cai_no_created_at():
    # Linhas anteriores ao passo 8a nao tem o candle. Devolver None faria
    # o cerebro ser reconsultado sem necessidade, gastando cota.
    banco = SupabaseDuble({"decisions": [
        {"candle_fechamento_em": None, "created_at": "2026-09-04T03:00:00+00:00"},
    ]})
    valor = ultima_consulta_ms(banco, "BTCUSDT")
    assert valor is not None and valor > 0


def test_cadencia_sem_a_coluna_aponta_o_schema():
    # Conferido contra o Supabase real: sem a coluna, o PostgREST devolve
    # 42703. Cair na mensagem generica esconderia que basta rodar o schema.
    banco = SupabaseDuble(
        erro_de_leitura="42703 column decisions.candle_fechamento_em does not exist"
    )
    try:
        ultima_consulta_ms(banco, "BTCUSDT")
    except ErroDeEstado as erro:
        assert "schema.sql" in str(erro)
    else:
        raise AssertionError("devia ter apontado o schema.sql")


# ------------------------------------------------------------- conversao

def test_conta_vira_estado_para_o_risk_engine():
    conta = ContaSimulada(
        par="BTCUSDT", caixa=100.0, quantidade=0.05,
        preco_entrada=80000.0, stop_loss=78000.0, take_profit=84000.0,
    )
    posicao = conta.como_estado_de_posicao()
    assert posicao.aberta
    assert posicao.stop_loss == 78000.0
    assert posicao.preco_entrada == 80000.0


def test_capital_total_soma_caixa_e_posicao():
    conta = ContaSimulada(par="BTCUSDT", caixa=5000.0, quantidade=0.05)
    assert conta.capital_total(80000.0) == 5000.0 + 0.05 * 80000.0


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
