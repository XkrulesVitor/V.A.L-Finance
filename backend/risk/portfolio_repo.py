"""
Casca fina entre o Supabase e o Risk Engine.

O `risk_engine.avaliar_risco()` e uma funcao pura: recebe o estado da
posicao como parametro e nao sabe que existe banco. Este modulo e o
unico lugar que traduz linha da tabela `portfolio` em `EstadoDaPosicao`
e de volta -- mesmo padrao do `run_baseline.py`, onde a persistencia
mora na borda e o miolo continua testavel sem rede.

## Falhar nao e o mesmo que estar sem posicao

Este e o ponto que o modulo existe pra proteger. Se a leitura do banco
falhar, a tentacao de "degradar" devolvendo `EstadoDaPosicao()` vazio e
justamente o erro perigoso: com posicao aberta no mundo real e "sem
posicao" na memoria, o sistema compraria de novo, dobraria exposicao, e
-- pior -- pararia de checar o stop-loss daquela posicao, porque a
regra 1 do Risk Engine so roda quando ha posicao conhecida.

Entao a falha e alta e barulhenta: levanta `ErroDePortfolio`. Quem
chama trata como "nao sei o estado, logo nao opero neste ciclo", nunca
como "estou de fora". Perder um ciclo custa uma oportunidade; agir com
o estado errado custa dinheiro.

## Sobre a coluna `asset`

Guarda o par (`BTCUSDT`), e nao a moeda (`BTC`). Preco de entrada, stop
e alvo sao propriedades da operacao naquele par -- a mesma quantidade de
BTC comprada contra USDT ou contra outra moeda teria niveis diferentes.
Usar o par tambem alinha a chave com a coluna `symbol` de `decisions`.
"""

from datetime import datetime, timezone

from risk.risk_engine import EstadoDaPosicao

TABELA = "portfolio"
COLUNAS_DE_RISCO = ("preco_entrada", "stop_loss", "take_profit")
# Lidas por nome, nunca com `select("*")`. A diferenca nao e estetica: com
# `*`, uma tabela sem as colunas de risco responde com sucesso e sem elas,
# e a posicao chega aqui parecendo "sem stop definido". Uma posicao com
# stop lida como se nao tivesse e o pior resultado possivel neste modulo --
# a regra 1 do Risk Engine simplesmente nunca dispararia. Pedindo as
# colunas pelo nome, a ausencia vira erro.
COLUNAS_LIDAS = ("asset", "quantity", "updated_at", *COLUNAS_DE_RISCO)


class ErroDePortfolio(RuntimeError):
    """Nao foi possivel determinar o estado da posicao."""


def buscar_posicao(supabase, par: str) -> EstadoDaPosicao:
    """
    Le a posicao atual de um par.

    Ausencia de linha e resposta legitima: significa "sem posicao", e
    devolve `EstadoDaPosicao()` vazio. Erro de leitura e outra coisa
    completamente diferente, e levanta.
    """
    try:
        resposta = (
            supabase.table(TABELA)
            .select(",".join(COLUNAS_LIDAS))
            .eq("asset", par)
            .limit(1)
            .execute()
        )
    except Exception as erro:  # noqa: BLE001
        if _e_coluna_ausente(erro):
            raise ErroDePortfolio(
                f"a tabela `{TABELA}` ainda nao tem as colunas de risco "
                f"{COLUNAS_DE_RISCO}. Rode `supabase/schema.sql` no SQL Editor."
            ) from erro
        raise ErroDePortfolio(f"falha ao ler a posicao de {par}: {erro}") from erro

    linhas = resposta.data or []
    if not linhas:
        return EstadoDaPosicao()

    linha = linhas[0]
    return EstadoDaPosicao(
        quantidade=float(linha.get("quantity") or 0.0),
        preco_entrada=_opcional(linha.get("preco_entrada")),
        stop_loss=_opcional(linha.get("stop_loss")),
        take_profit=_opcional(linha.get("take_profit")),
    )


def salvar_posicao(supabase, par: str, posicao: EstadoDaPosicao) -> None:
    """
    Grava o estado da posicao, incluindo os niveis de risco.

    Os niveis sao gravados JUNTO com a quantidade, na mesma escrita, de
    proposito: uma posicao registrada sem stop e uma posicao que a regra
    1 nao consegue proteger. Se fossem duas escritas, uma falha entre
    elas deixaria exatamente esse buraco aberto.
    """
    registro = {
        "asset": par,
        "quantity": posicao.quantidade,
        "preco_entrada": posicao.preco_entrada,
        "stop_loss": posicao.stop_loss,
        "take_profit": posicao.take_profit,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        supabase.table(TABELA).upsert(registro, on_conflict="asset").execute()
    except Exception as erro:  # noqa: BLE001
        if _e_coluna_ausente(erro):
            raise ErroDePortfolio(
                f"a tabela `{TABELA}` ainda nao tem as colunas de risco "
                f"{COLUNAS_DE_RISCO}. Rode `supabase/schema.sql` no SQL Editor."
            ) from erro
        raise ErroDePortfolio(f"falha ao gravar a posicao de {par}: {erro}") from erro


def colunas_de_risco_existem(supabase) -> bool:
    """
    Checagem barata pra quem quiser avisar cedo, antes de rodar um ciclo
    inteiro e descobrir no fim que nao da pra gravar o stop.
    """
    try:
        supabase.table(TABELA).select(",".join(COLUNAS_DE_RISCO)).limit(1).execute()
        return True
    except Exception:  # noqa: BLE001
        return False


def _opcional(valor):
    """0 e None significam a mesma coisa aqui: nivel nao definido."""
    if valor is None:
        return None
    convertido = float(valor)
    return convertido if convertido > 0 else None


def _e_coluna_ausente(erro) -> bool:
    """
    O PostgREST relata coluna ausente de duas formas diferentes, e as
    duas aparecem na pratica: `42703 / does not exist` quando o erro vem
    do Postgres (leitura), e `PGRST204 / Could not find the ... column`
    quando vem do cache de schema do proprio PostgREST (escrita).
    Reconhecer so uma delas deixa metade dos casos cair na mensagem
    generica, sem a dica de rodar o schema.sql.
    """
    texto = str(erro)
    return any(
        marca in texto
        for marca in ("42703", "does not exist", "PGRST204", "Could not find the")
    )
