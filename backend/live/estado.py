"""
Estado do forward test atravessando processos -- passo 8a.

## O problema que este modulo resolve

No backtest um processo so segura tudo: caixa, quantidade, niveis de
stop/take e a hora da ultima consulta ao cerebro vivem em memoria do
primeiro candle ao ultimo (`brain/hybrid_strategy.py`).

No cron o processo **morre a cada ciclo**. Cada coisa que a estrategia
guardava em memoria precisa sair pro banco e voltar -- e, mais
importante, cada ponto onde o processo pode morrer vira um estado
possivelmente inconsistente.

O caso que custa dinheiro: registrar a compra e morrer antes de gravar o
stop. A posicao existe e a regra 1 do Risk Engine nao tem nivel pra
comparar, entao ela nunca dispara. `portfolio_repo` ja se recusa a
degradar para "sem posicao" quando a LEITURA falha; este modulo aplica a
mesma disciplina na ESCRITA.

## Por que 8a e mais seguro que operar na testnet

Vale registrar, porque foi o que decidiu a ordem do roteiro.

Com ordem de verdade na corretora existem dois sistemas -- a corretora e
o nosso banco -- e uma janela entre eles: a ordem foi preenchida e o
processo morre antes de gravar. Fica uma posicao real que o sistema
desconhece, e reconciliar isso e trabalhoso.

No forward test **a execucao e a escrituracao sao a mesma escrita**. Nao
ha corretora: o preenchimento simulado E a linha do `portfolio`. A
posicao existe se, e somente se, a linha foi gravada. A janela nao e
pequena -- ela nao existe.

Por isso 8a vem antes de 8b, e nao porque e mais facil.

## Atomicidade

Caixa, quantidade e niveis moram na MESMA LINHA (`portfolio`), gravados
num `upsert` unico. O Postgres garante atomicidade por linha, entao ou
tudo entra ou nada entra. Em duas escritas o buraco existiria, e com o
processo morrendo a cada hora ele seria alcancado.

## Idempotencia

A chave e o candle fechado que gerou a decisao: para um par, cada candle
so pode ser decidido uma vez. Ela nao e inventada -- vem do dado.

E a restricao mora no banco (indice unico), nao numa consulta previa.
Conferir antes de inserir tem janela de corrida: duas execucoes
consultam, as duas veem que nao existe, as duas inserem. O indice unico
nao tem essa janela.

O fluxo e "reivindicar depois trabalhar": a linha de `decisions` e
inserida ANTES de decidir qualquer coisa. Se a insercao falhar por
violacao de unicidade, outra execucao ja pegou este candle -- e a
resposta certa e sair sem fazer nada.
"""

from dataclasses import dataclass
from datetime import datetime, timezone

from risk.risk_engine import EstadoDaPosicao

TABELA_PORTFOLIO = "portfolio"
TABELA_DECISOES = "decisions"

CAPITAL_INICIAL_PADRAO = 10_000.0

# Lidas por nome, nunca com `select("*")` -- mesma razao do
# `portfolio_repo`: com `*`, uma tabela sem a coluna responde com sucesso
# e sem ela, e o caixa chegaria aqui como "nao definido" em vez de virar
# erro.
COLUNAS_DA_CONTA = (
    "asset", "quantity", "caixa", "preco_entrada", "stop_loss", "take_profit",
)

# Marcas com que o PostgREST relata violacao de indice unico.
MARCAS_DE_DUPLICADA = ("23505", "duplicate key", "already exists")


class ErroDeEstado(RuntimeError):
    """Nao foi possivel determinar ou gravar o estado da conta."""


class CandleJaProcessado(RuntimeError):
    """
    Outra execucao ja reivindicou este candle.

    Nao e erro: e a idempotencia funcionando. Quem chama sai do ciclo
    em silencio, sem operar.
    """


@dataclass
class ContaSimulada:
    """
    A conta de um par no forward test: caixa, posicao e niveis.

    Espelha o que o motor de backtest guarda em memoria, pra que os dois
    caminhos possam ser comparados sem traducao pelo meio.
    """

    par: str
    caixa: float
    quantidade: float = 0.0
    preco_entrada: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None

    @property
    def posicionada(self) -> bool:
        return self.quantidade > 0

    def como_estado_de_posicao(self) -> EstadoDaPosicao:
        """Converte pro que o Risk Engine espera -- ele nao sabe de banco."""
        return EstadoDaPosicao(
            quantidade=self.quantidade,
            preco_entrada=self.preco_entrada,
            stop_loss=self.stop_loss,
            take_profit=self.take_profit,
        )

    def capital_total(self, preco_atual: float) -> float:
        return self.caixa + self.quantidade * preco_atual


def carregar_conta(
    supabase, par: str, capital_inicial: float = CAPITAL_INICIAL_PADRAO
) -> ContaSimulada:
    """
    Le a conta de um par.

    Linha ausente e resposta legitima: significa "conta nova", e devolve
    o capital inicial em caixa. Erro de leitura e outra coisa
    completamente diferente e levanta -- operar sem saber o estado e
    exatamente o que este modulo existe pra impedir.
    """
    try:
        resposta = (
            supabase.table(TABELA_PORTFOLIO)
            .select(",".join(COLUNAS_DA_CONTA))
            .eq("asset", par)
            .limit(1)
            .execute()
        )
    except Exception as erro:  # noqa: BLE001
        if _e_coluna_ausente(erro):
            raise ErroDeEstado(
                f"a tabela `{TABELA_PORTFOLIO}` ainda nao tem a coluna `caixa`. "
                f"Rode `supabase/schema.sql` no SQL Editor."
            ) from erro
        raise ErroDeEstado(f"falha ao ler a conta de {par}: {erro}") from erro

    linhas = resposta.data or []
    if not linhas:
        return ContaSimulada(par=par, caixa=capital_inicial)

    linha = linhas[0]
    caixa = linha.get("caixa")
    return ContaSimulada(
        par=par,
        # `caixa` nulo numa linha que existe = linha criada antes do passo
        # 8a (so tinha quantidade). Tratar como capital inicial seria
        # inventar dinheiro; tratar como zero seria inventar prejuizo.
        # Melhor recusar e deixar o humano decidir.
        caixa=_exigir_caixa(caixa, par),
        quantidade=float(linha.get("quantity") or 0.0),
        preco_entrada=_opcional(linha.get("preco_entrada")),
        stop_loss=_opcional(linha.get("stop_loss")),
        take_profit=_opcional(linha.get("take_profit")),
    )


def salvar_conta(supabase, conta: ContaSimulada) -> None:
    """
    Grava a conta inteira numa escrita so.

    Caixa, quantidade e niveis vao juntos de proposito: e o que garante
    que nunca exista uma posicao registrada sem o stop que a protege, nem
    uma compra registrada sem o caixa debitado.
    """
    if conta.quantidade > 0 and conta.stop_loss is None:
        # Guarda de sanidade, nao paranoia: uma posicao sem stop e
        # invisivel pra regra 1 do Risk Engine. Se isso chegar aqui, o
        # bug esta em quem chamou, e gravar tornaria o bug permanente.
        raise ErroDeEstado(
            f"recusando gravar posicao de {conta.par} sem stop_loss -- "
            f"a regra 1 do Risk Engine nao teria nivel pra comparar"
        )

    registro = {
        "asset": conta.par,
        "quantity": conta.quantidade,
        "caixa": conta.caixa,
        "preco_entrada": conta.preco_entrada,
        "stop_loss": conta.stop_loss,
        "take_profit": conta.take_profit,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        supabase.table(TABELA_PORTFOLIO).upsert(registro, on_conflict="asset").execute()
    except Exception as erro:  # noqa: BLE001
        if _e_coluna_ausente(erro):
            raise ErroDeEstado(
                f"a tabela `{TABELA_PORTFOLIO}` ainda nao tem a coluna `caixa`. "
                f"Rode `supabase/schema.sql` no SQL Editor."
            ) from erro
        raise ErroDeEstado(f"falha ao gravar a conta de {conta.par}: {erro}") from erro


def reivindicar_candle(supabase, par: str, fechamento_em: int) -> str:
    """
    Reivindica o direito de decidir sobre este candle, e devolve o id da
    linha criada.

    Insere a linha de `decisions` ANTES de qualquer decisao. Se outra
    execucao ja reivindicou o mesmo (par, candle), o indice unico do
    banco recusa e isto levanta `CandleJaProcessado`.

    Reivindicar antes e nao depois e o que fecha a janela de corrida:
    duas execucoes simultaneas nao podem as duas achar que o candle esta
    livre, porque quem decide e o banco, no momento da escrita.
    """
    registro = {
        "symbol": par,
        "candle_fechamento_em": fechamento_em,
        "status": "processando",
    }
    try:
        resposta = supabase.table(TABELA_DECISOES).insert(registro).execute()
    except Exception as erro:  # noqa: BLE001
        if _e_duplicada(erro):
            raise CandleJaProcessado(
                f"o candle {fechamento_em} de {par} ja foi reivindicado "
                f"por outra execucao"
            ) from erro
        if _e_coluna_ausente(erro):
            raise ErroDeEstado(
                f"a tabela `{TABELA_DECISOES}` ainda nao tem a coluna "
                f"`candle_fechamento_em`. Rode `supabase/schema.sql`."
            ) from erro
        raise ErroDeEstado(f"falha ao reivindicar candle de {par}: {erro}") from erro

    linhas = resposta.data or []
    if not linhas:
        raise ErroDeEstado(f"insercao de decisao para {par} nao devolveu id")
    return linhas[0]["id"]


def concluir_decisao(supabase, id_decisao: str, campos: dict) -> None:
    """Preenche a linha reivindicada com o resultado do ciclo."""
    try:
        supabase.table(TABELA_DECISOES).update(campos).eq("id", id_decisao).execute()
    except Exception as erro:  # noqa: BLE001
        raise ErroDeEstado(
            f"falha ao concluir a decisao {id_decisao}: {erro}"
        ) from erro


def ultima_consulta_ms(supabase, par: str) -> int | None:
    """
    Quando o cerebro foi consultado pela ultima vez para este par.

    E o estado que `ControleDeCadencia` guarda em memoria no backtest.
    A fonte aqui e a propria tabela `decisions`: a ultima linha com
    `llm_output` preenchido. Nao ha contador separado pra sair de
    sincronia com o historico -- o historico E o contador.

    `None` significa "nunca consultou", e `deve_consultar` trata isso
    como "pode consultar".
    """
    try:
        resposta = (
            supabase.table(TABELA_DECISOES)
            .select("candle_fechamento_em,created_at")
            .eq("symbol", par)
            .not_.is_("llm_output", "null")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
    except Exception as erro:  # noqa: BLE001
        if _e_coluna_ausente(erro):
            raise ErroDeEstado(
                f"a tabela `{TABELA_DECISOES}` ainda nao tem a coluna "
                f"`candle_fechamento_em`. Rode `supabase/schema.sql`."
            ) from erro
        raise ErroDeEstado(
            f"falha ao ler a ultima consulta de {par}: {erro}"
        ) from erro

    linhas = resposta.data or []
    if not linhas:
        return None

    fechamento = linhas[0].get("candle_fechamento_em")
    if fechamento is not None:
        return int(fechamento)

    # Linha antiga, anterior ao passo 8a: cai no `created_at`. Menos
    # preciso, mas melhor que devolver None e reconsultar o cerebro sem
    # necessidade -- o que gastaria cota.
    criada = linhas[0].get("created_at")
    if not criada:
        return None
    return int(
        datetime.fromisoformat(criada.replace("Z", "+00:00")).timestamp() * 1000
    )


def _exigir_caixa(valor, par: str) -> float:
    if valor is None:
        raise ErroDeEstado(
            f"a linha de {par} em `{TABELA_PORTFOLIO}` existe mas nao tem "
            f"`caixa`. Isso e uma linha anterior ao passo 8a. Defina o "
            f"caixa dela no banco antes de rodar o forward test -- "
            f"assumir um valor aqui inventaria dinheiro ou prejuizo."
        )
    return float(valor)


def _opcional(valor):
    """0 e None significam a mesma coisa aqui: nivel nao definido."""
    if valor is None:
        return None
    convertido = float(valor)
    return convertido if convertido > 0 else None


def _e_duplicada(erro) -> bool:
    texto = str(erro)
    return any(marca in texto for marca in MARCAS_DE_DUPLICADA)


def _e_coluna_ausente(erro) -> bool:
    """
    Mesmas duas formas que o `portfolio_repo` ja trata: `42703 / does not
    exist` quando o erro vem do Postgres, e `PGRST204 / Could not find
    the` quando vem do cache de schema do PostgREST.
    """
    texto = str(erro)
    return any(
        marca in texto
        for marca in ("42703", "does not exist", "PGRST204", "Could not find the")
    )
