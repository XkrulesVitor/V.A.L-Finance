"""
Conferencia do ciclo do forward test -- passo 8a.

    python backend/tests/test_ciclo_ao_vivo.py

Sem rede: Supabase, Binance e analista sao dubles.

## O teste que mais importa deste arquivo

`test_preenchimento_bate_com_o_motor_de_backtest`. O passo 8a existe pra
comparar o resultado ao vivo com os numeros da secao 11, e essa
comparacao so vale se a unica diferenca for o dado. Se a aritmetica de
preenchimento divergir do motor -- outra taxa, outro dimensionamento --
a comparacao vira ruido e ninguem percebe olhando o resultado.

## Os outros grupos

- **ordem das etapas**: o stop tem que ser conferido antes da cadencia e
  sem tocar nas features. Inverter faria o rompimento ser descoberto com
  ate 6h de atraso, e gastaria cota de LLM pra decidir uma saida que ja
  estava decidida.
- **falha do cerebro**: nao pode desproteger a posicao nem derrubar o
  ciclo.
- **idempotencia**: candle ja reivindicado sai sem operar.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.engine import BUY, HOLD, NO_TRADE, SELL, TAXA_PADRAO  # noqa: E402
from live.ciclo import rodar_ciclo  # noqa: E402
from live.execucao import comprar, vender  # noqa: E402
from live.estado import ContaSimulada  # noqa: E402
from risk.risk_engine import ParametrosDeRisco  # noqa: E402

import time  # noqa: E402

UMA_HORA = 60 * 60 * 1000

# Copiado de `supabase/schema.sql`. O duble recusa qualquer coluna fora
# desta lista, pra que um campo inventado quebre aqui e nao so contra o
# banco de verdade.
COLUNAS_REAIS = {
    "decisions": {
        "id", "created_at", "symbol", "market_snapshot", "features",
        "llm_output", "risk_result", "order_result", "status", "outcome",
        "candle_fechamento_em",
    },
    "portfolio": {
        "asset", "quantity", "caixa", "updated_at",
        "preco_entrada", "stop_loss", "take_profit",
    },
}


def _candles(n=400, preco=80000.0):
    """
    Serie sintetica com um candle em curso no fim.

    Ancorada no relogio de agora, e nao num timestamp fixo, porque
    `somente_fechados` compara `fechamento_em` com o instante atual --
    com data fixa o candle "em andamento" envelhece e passa a contar como
    fechado, e o teste para de testar o que diz testar.
    """
    agora_ms = int(time.time() * 1000)
    # o ultimo candle abriu ha menos de uma hora: ainda esta aberto
    abertura_do_atual = agora_ms - UMA_HORA // 2
    saida = []
    for i in range(n):
        abertura_em = abertura_do_atual - (n - 1 - i) * UMA_HORA
        saida.append({
            "abertura_em": abertura_em,
            "abertura": preco, "maxima": preco * 1.005,
            "minima": preco * 0.995, "fechamento": preco,
            "volume": 100.0,
            "fechamento_em": abertura_em + UMA_HORA - 1,
        })
    return saida


class TeseDuble:
    def __init__(self, direction="BUY", horizon="curto", confidence=0.8):
        self.direction = direction
        self.horizon = horizon
        self.confidence = confidence
        self.reasoning = "duble"

    def model_dump(self):
        return {"direction": self.direction, "horizon": self.horizon,
                "confidence": self.confidence, "reasoning": self.reasoning}


class AnalistaDuble:
    def __init__(self, tese=None, erro=None):
        self.tese = tese or TeseDuble()
        self.erro = erro
        self.chamadas = 0
        self.features_recebidas = None

    def analisar(self, features, simbolo, posicao_aberta=False, preco_atual=None):
        self.chamadas += 1
        self.features_recebidas = features
        if self.erro:
            raise self.erro
        return self.tese


class BinanceDuble:
    def __init__(self, candles=None, preco=80000.0):
        self._candles = candles if candles is not None else _candles()
        self._preco = preco

    def buscar_candles(self, simbolo, intervalo="1h", limite=100):
        return self._candles

    def buscar_preco(self, simbolo):
        return self._preco


class ConsultaDuble:
    def __init__(self, tabela, banco):
        self.tabela = tabela
        self.banco = banco
        self._op = "select"
        self._registro = None

    def select(self, *_):
        self._op = "select"
        return self

    def insert(self, r):
        self._op, self._registro = "insert", r
        return self

    def upsert(self, r, on_conflict=None):
        self._op, self._registro = "upsert", r
        return self

    def update(self, r):
        self._op, self._registro = "update", r
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
        if self._op == "select":
            return type("R", (), {"data": self.banco.linhas.get(self.tabela, [])})()
        if self._op == "insert" and self.banco.candle_duplicado:
            raise RuntimeError("23505 duplicate key")
        # O duble conhece o schema REAL. Sem isto ele aceitava qualquer
        # chave, e um campo inexistente so aparecia contra o Supabase de
        # verdade -- foi assim que `caixa_antes` passou pelos testes e
        # quebrou na integracao com PGRST204.
        desconhecidas = set(self._registro or {}) - COLUNAS_REAIS[self.tabela]
        if desconhecidas:
            raise RuntimeError(
                f"PGRST204 Could not find the {sorted(desconhecidas)!r} "
                f"column of '{self.tabela}' in the schema cache"
            )
        self.banco.escritas.append((self.tabela, self._op, self._registro))
        if self._op == "insert":
            return type("R", (), {"data": [{"id": "dec-1", **self._registro}]})()
        return type("R", (), {"data": [self._registro]})()


class SupabaseDuble:
    def __init__(self, portfolio=None, decisions=None, candle_duplicado=False):
        self.linhas = {"portfolio": portfolio or [], "decisions": decisions or []}
        self.candle_duplicado = candle_duplicado
        self.escritas = []

    def table(self, nome):
        return ConsultaDuble(nome, self)

    def gravou_em(self, tabela):
        return [e for e in self.escritas if e[0] == tabela]

    def ultima_decisao(self):
        d = [e for e in self.escritas if e[0] == "decisions" and e[1] == "update"]
        return d[-1][2] if d else None


def _posicionada(caixa=0.0, qtd=0.125, entrada=80000.0, stop=78000.0, alvo=84000.0):
    return [{"asset": "BTCUSDT", "quantity": qtd, "caixa": caixa,
             "preco_entrada": entrada, "stop_loss": stop, "take_profit": alvo}]


# ------------------------------------------------- paridade com o motor

def test_preenchimento_bate_com_o_motor_de_backtest():
    # O teste central do arquivo. Reproduz a aritmetica do motor
    # (backtest/engine.py, ramos BUY e SELL) e exige o mesmo numero.
    caixa_inicial, preco_entrada, preco_saida = 10_000.0, 80_000.0, 84_000.0

    # --- como o motor faz ---
    taxa_c = caixa_inicial * TAXA_PADRAO
    qtd_motor = (caixa_inicial - taxa_c) / preco_entrada
    bruto = qtd_motor * preco_saida
    caixa_motor = bruto - bruto * TAXA_PADRAO

    # --- como o ciclo ao vivo faz ---
    conta = ContaSimulada(par="BTCUSDT", caixa=caixa_inicial)
    conta, _ = comprar(conta, preco_entrada, 78000.0, 84000.0)
    assert abs(conta.quantidade - qtd_motor) < 1e-12, (
        f"quantidade divergiu: ao vivo {conta.quantidade}, motor {qtd_motor}"
    )
    conta, _ = vender(conta, preco_saida, "teste")
    assert abs(conta.caixa - caixa_motor) < 1e-9, (
        f"caixa divergiu: ao vivo {conta.caixa}, motor {caixa_motor}"
    )


def test_resultado_da_operacao_bate_com_o_motor():
    # Regressao. O resultado gravado ignorava a taxa de compra, e a Carteira
    # mostrou realizado de -33,12 com patrimonio em -90,82 e nada aberto:
    # a diferenca era a soma das 6 taxas de entrada. O motor usa como custo
    # o caixa inteiro gasto na entrada (engine.py: custo_da_entrada = caixa).
    caixa_inicial, p_entrada, p_saida = 10_000.0, 80_000.0, 76_000.0
    qtd = (caixa_inicial - caixa_inicial * TAXA_PADRAO) / p_entrada
    bruto = qtd * p_saida
    resultado_motor = (bruto - bruto * TAXA_PADRAO) - caixa_inicial

    conta = ContaSimulada(par="BTCUSDT", caixa=caixa_inicial)
    conta, _ = comprar(conta, p_entrada, 70_000.0, 90_000.0)
    conta, ordem = vender(conta, p_saida, "teste")
    assert abs(ordem["resultado"] - resultado_motor) < 1e-6, (
        f"resultado ao vivo {ordem['resultado']:.4f} != motor {resultado_motor:.4f}"
    )
    assert abs(ordem["resultado"] - (conta.caixa - caixa_inicial)) < 1e-6, (
        "resultado tem que ser exatamente o que o caixa andou"
    )
    assert abs(ordem["resultado_pct"] - resultado_motor / caixa_inicial * 100) < 1e-9, (
        "percentual tem que ser liquido de taxas, como o resultado"
    )


def test_compra_usa_todo_o_caixa():
    # O motor entra com o caixa inteiro; usar `tamanho_posicao` do Risk
    # Engine aqui produziria uma curva de capital incomparavel.
    conta = ContaSimulada(par="BTCUSDT", caixa=10_000.0)
    conta, _ = comprar(conta, 80_000.0, 78_000.0, 84_000.0)
    assert conta.caixa == 0.0


def test_compra_sem_stop_e_recusada():
    conta = ContaSimulada(par="BTCUSDT", caixa=10_000.0)
    try:
        comprar(conta, 80_000.0, None, 84_000.0)
    except ValueError as erro:
        assert "stop" in str(erro).lower()
    else:
        raise AssertionError("comprar sem stop tinha que ser recusado")


def test_compra_dobrada_e_recusada():
    conta = ContaSimulada(par="BTCUSDT", caixa=100.0, quantidade=0.1, stop_loss=78000.0)
    try:
        comprar(conta, 80_000.0, 78_000.0, 84_000.0)
    except ValueError as erro:
        assert "posicionada" in str(erro)
    else:
        raise AssertionError("comprar posicionado tinha que ser recusado")


# --------------------------------------------------- ordem das etapas

def test_stop_rompido_vende_sem_consultar_o_cerebro():
    # Etapa 1 antes da etapa 2: com o stop rompido, a saida e decidida
    # sem gastar chamada de LLM.
    banco = SupabaseDuble(portfolio=_posicionada(stop=79_000.0))
    analista = AnalistaDuble()
    r = rodar_ciclo(banco, BinanceDuble(preco=78_000.0), analista, "BTCUSDT")
    assert r.acao == SELL, f"esperava SELL, veio {r.acao}"
    assert analista.chamadas == 0, "nao podia ter consultado o cerebro"
    assert "stop" in r.detalhe


def test_alvo_atingido_vende_sem_consultar():
    banco = SupabaseDuble(portfolio=_posicionada(alvo=83_000.0))
    analista = AnalistaDuble()
    r = rodar_ciclo(banco, BinanceDuble(preco=84_000.0), analista, "BTCUSDT")
    assert r.acao == SELL
    assert analista.chamadas == 0
    assert "alvo" in r.detalhe


def test_saida_por_stop_zera_a_posicao_e_devolve_caixa():
    banco = SupabaseDuble(portfolio=_posicionada(stop=79_000.0))
    rodar_ciclo(banco, BinanceDuble(preco=78_000.0), AnalistaDuble(), "BTCUSDT")
    _, _, registro = banco.gravou_em("portfolio")[-1]
    assert registro["quantity"] == 0.0
    assert registro["caixa"] > 0
    assert registro["stop_loss"] is None


def test_fora_da_cadencia_nao_consulta():
    # Consulta recente -> ainda nao e hora. O timestamp e derivado dos
    # proprios candles, e nao fixo: com data fixa o teste passaria a
    # medir o calendario em vez da cadencia.
    candles = _candles()
    ultimo_fechado = candles[-2]["fechamento_em"]
    banco = SupabaseDuble(decisions=[{
        "candle_fechamento_em": ultimo_fechado - UMA_HORA,  # 1h atras, cadencia e 6h
        "created_at": "2026-09-04T03:00:00+00:00",
    }])
    analista = AnalistaDuble()
    r = rodar_ciclo(banco, BinanceDuble(candles=candles), analista, "BTCUSDT")
    assert analista.chamadas == 0
    assert r.acao == NO_TRADE
    assert "cadencia" in r.detalhe


def test_dentro_da_cadencia_consulta_e_compra():
    banco = SupabaseDuble()
    analista = AnalistaDuble(TeseDuble(direction=BUY))
    r = rodar_ciclo(banco, BinanceDuble(), analista, "BTCUSDT")
    assert analista.chamadas == 1
    assert r.acao == BUY, f"esperava BUY, veio {r.acao} ({r.detalhe})"
    _, _, registro = banco.gravou_em("portfolio")[-1]
    assert registro["quantity"] > 0
    assert registro["stop_loss"] is not None, "comprou sem stop"


def test_features_so_sao_calculadas_quando_consulta():
    # A etapa 1 nao pode tocar em features -- e a parte cara.
    banco = SupabaseDuble(portfolio=_posicionada(stop=79_000.0))
    analista = AnalistaDuble()
    rodar_ciclo(banco, BinanceDuble(preco=78_000.0), analista, "BTCUSDT")
    assert analista.features_recebidas is None


# --------------------------- varredura de fechamentos nao vistos

def test_stop_rompido_em_candle_passado_e_pego():
    # O caso que motivou a varredura. O agendamento do GitHub e melhor
    # esforco -- medido: 25 execucoes em 80h. Se o stop romper num
    # fechamento que o processo nao chegou a ver, conferir so o preco do
    # momento perde a saida inteira.
    candles = _candles()
    candles[-4]["fechamento"] = 70_000.0          # rompeu num candle antigo
    banco = SupabaseDuble(
        portfolio=_posicionada(stop=78_000.0),
        # ja processamos ate bem antes do candle que rompeu
        decisions=[{"candle_fechamento_em": candles[-10]["fechamento_em"],
                    "created_at": "2026-09-07T00:00:00+00:00"}],
    )
    # preco AGORA esta acima do stop: so ele nao acusaria nada
    r = rodar_ciclo(banco, BinanceDuble(candles=candles, preco=80_000.0),
                    AnalistaDuble(), "BTCUSDT")
    assert r.acao == SELL, f"esperava SELL do candle passado, veio {r.acao}"


def test_saida_usa_o_preco_do_candle_e_nao_o_de_agora():
    # Sair ao preco atual registraria um resultado que nem o backtest nem
    # uma ordem stop de verdade produziriam.
    candles = _candles()
    candles[-4]["fechamento"] = 70_000.0
    banco = SupabaseDuble(
        portfolio=_posicionada(stop=78_000.0),
        decisions=[{"candle_fechamento_em": candles[-10]["fechamento_em"],
                    "created_at": "2026-09-07T00:00:00+00:00"}],
    )
    rodar_ciclo(banco, BinanceDuble(candles=candles, preco=80_000.0),
                AnalistaDuble(), "BTCUSDT")
    ordem = banco.ultima_decisao()["order_result"]
    assert ordem["preco"] == 70_000.0, (
        f"devia sair no fechamento do candle (70.000), saiu em {ordem['preco']}"
    )


def test_candle_ja_processado_nao_e_reavaliado():
    # Um rompimento ANTERIOR a ultima decisao ja foi julgado. Reavaliar
    # faria o sistema vender por um evento que ele proprio ja analisou.
    candles = _candles()
    candles[-20]["fechamento"] = 70_000.0         # rompeu, mas ja foi visto
    banco = SupabaseDuble(
        portfolio=_posicionada(stop=78_000.0),
        decisions=[{"candle_fechamento_em": candles[-10]["fechamento_em"],
                    "created_at": "2026-09-07T00:00:00+00:00"}],
    )
    r = rodar_ciclo(banco, BinanceDuble(candles=candles, preco=80_000.0),
                    AnalistaDuble(), "BTCUSDT")
    assert r.acao != SELL, "nao podia vender por candle ja processado"


def test_sem_historico_confere_o_preco_do_momento():
    # Primeiro ciclo do par: nao ha "ultimo processado", entao o
    # comportamento antigo (conferir o agora) tem que continuar valendo.
    banco = SupabaseDuble(portfolio=_posicionada(stop=79_000.0))
    r = rodar_ciclo(banco, BinanceDuble(preco=78_000.0), AnalistaDuble(), "BTCUSDT")
    assert r.acao == SELL


def test_varredura_ignora_o_candle_em_andamento():
    # O candle aberto ainda pode mudar. Agir sobre ele e look-ahead ao
    # contrario -- decidir com dado que ainda nao aconteceu.
    candles = _candles()
    candles[-1]["fechamento"] = 70_000.0          # o EM CURSO "rompeu"
    banco = SupabaseDuble(
        portfolio=_posicionada(stop=78_000.0),
        decisions=[{"candle_fechamento_em": candles[-10]["fechamento_em"],
                    "created_at": "2026-09-07T00:00:00+00:00"}],
    )
    r = rodar_ciclo(banco, BinanceDuble(candles=candles, preco=80_000.0),
                    AnalistaDuble(), "BTCUSDT")
    assert r.acao != SELL, "candle em andamento nao pode disparar saida"


def test_primeiro_rompimento_ganha():
    # Dois candles romperam. O correto e sair no PRIMEIRO -- e onde uma
    # ordem stop de verdade teria disparado.
    candles = _candles()
    candles[-6]["fechamento"] = 77_000.0
    candles[-3]["fechamento"] = 60_000.0
    banco = SupabaseDuble(
        portfolio=_posicionada(stop=78_000.0),
        decisions=[{"candle_fechamento_em": candles[-10]["fechamento_em"],
                    "created_at": "2026-09-07T00:00:00+00:00"}],
    )
    rodar_ciclo(banco, BinanceDuble(candles=candles, preco=80_000.0),
                AnalistaDuble(), "BTCUSDT")
    assert banco.ultima_decisao()["order_result"]["preco"] == 77_000.0


# ------------------------------------------------------ falha do cerebro

def test_falha_do_cerebro_nao_derruba_o_ciclo():
    banco = SupabaseDuble()
    analista = AnalistaDuble(erro=RuntimeError("503 UNAVAILABLE"))
    r = rodar_ciclo(banco, BinanceDuble(), analista, "BTCUSDT")
    assert r.acao == "ERRO_CEREBRO"
    assert banco.ultima_decisao()["status"] == "brain_error"


def test_falha_do_cerebro_nao_mexe_na_posicao():
    # O ponto: falhar na etapa 2 nao pode alterar a carteira. A posicao
    # segue protegida pelo stop, que a etapa 1 confere no proximo ciclo.
    banco = SupabaseDuble(portfolio=_posicionada(stop=70_000.0))
    analista = AnalistaDuble(erro=RuntimeError("timeout"))
    rodar_ciclo(banco, BinanceDuble(preco=80_000.0), analista, "BTCUSDT")
    assert banco.gravou_em("portfolio") == [], "nao podia ter mexido na carteira"


# --------------------------------------------------------- idempotencia

def test_candle_ja_processado_sai_sem_operar():
    banco = SupabaseDuble(candle_duplicado=True)
    analista = AnalistaDuble()
    r = rodar_ciclo(banco, BinanceDuble(), analista, "BTCUSDT")
    assert r.acao == "JA_PROCESSADO"
    assert analista.chamadas == 0
    assert banco.gravou_em("portfolio") == []


def test_reivindica_antes_de_consultar_o_cerebro():
    banco = SupabaseDuble()
    rodar_ciclo(banco, BinanceDuble(), AnalistaDuble(), "BTCUSDT")
    primeira = banco.escritas[0]
    assert primeira[0] == "decisions" and primeira[1] == "insert", (
        f"a primeira escrita tinha que ser a reivindicacao, foi {primeira[:2]}"
    )


# -------------------------------------------------------------- deslize

def test_deslize_e_registrado():
    # A execucao ao vivo nao acontece na abertura do candle, como no
    # backtest. A diferenca fica medida em vez de escondida.
    banco = SupabaseDuble()
    rodar_ciclo(banco, BinanceDuble(preco=80_400.0), AnalistaDuble(), "BTCUSDT")
    snapshot = banco.ultima_decisao()["market_snapshot"]
    assert snapshot["preco_de_referencia"] is not None
    assert abs(snapshot["deslize_pct"] - 0.5) < 0.01, snapshot["deslize_pct"]


def test_candle_em_andamento_e_descartado():
    banco = SupabaseDuble()
    rodar_ciclo(banco, BinanceDuble(), AnalistaDuble(), "BTCUSDT")
    snapshot = banco.ultima_decisao()["market_snapshot"]
    assert snapshot["candles_em_andamento_descartados"] == 1


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
