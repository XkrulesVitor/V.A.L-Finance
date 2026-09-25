"""
As seis carteiras do forward test -- a partir de setembro/2026.

Um lugar so define quem existe, o nome que o leigo ve, a frase da regra
(usada pelo explicador) e os parametros. O ciclo (`live/ciclo_carteira.py`)
le daqui; o site le a tabela `carteiras`, que e sincronizada a partir
daqui a cada execucao (`sincronizar_catalogo`).

    T1 Reguas            tendencia   ja no ar desde 22/09/2026
    T2 Tartarugas        tendencia   Turtle Trading, Sistema 2
    T3 Conselho de IAs   tendencia   painel de 3 IAs gratuitas
    G1 Reguas com meta   stop gain   entrada da T1 + alvo de 3 ATR
    G2 Repique           curto prazo RSI(2) de Connors
    G3 Conselho com meta stop gain   entrada da T3 + alvo de 3 ATR

A especificacao completa e o pre-registro estao em
`backend/backtest/PRE_REGISTRO_6_CARTEIRAS.md`.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone

from estrategia import alvo, rsi2, tartarugas
from estrategia import tendencia_diaria as reguas


@dataclass(frozen=True)
class Carteira:
    id: str
    nome: str
    familia: str            # 'tendencia' ou 'stop_gain'
    regra: str              # 'reguas', 'tartarugas', 'rsi2' ou 'painel'
    com_alvo: bool
    descricao_leiga: str
    descricao_regra: str
    regra_versao: str
    ordem: int
    ativa_desde: str | None = None
    parametros: dict = field(default_factory=dict)

    @property
    def usa_painel(self) -> bool:
        return self.regra == "painel"


_ALVO = {"alvo_em_atr": alvo.ALVO_EM_ATR, "atr_n": alvo.ATR_N}
_STOP = {"stop_catastrofe": reguas.STOP_CATASTROFE}
_REGUAS = {"lookbacks": list(reguas.LOOKBACKS), "entra_com": reguas.ENTRA_COM, "sai_com": reguas.SAI_COM}
_PAINEL = {"painel": "painel-v1", "agregacao": "painel-agg-v1", "entra_com_soma": 2, "sai_com_soma": -1, "quorum": 2}

CARTEIRAS: tuple[Carteira, ...] = (
    Carteira(
        "T1", "Réguas", "tendencia", "reguas", False,
        "Compara o preço com a média de 6 períodos (10 a 100 dias). Compra quando 4 ou mais "
        "mostram alta e vende quando só 2 ou menos mostram.",
        "compra quando o preco fecha o dia acima da media em pelo menos 4 de 6 prazos (10, 20, "
        "30, 50, 70 e 100 dias); vende quando isso cai para 2 ou menos; vende tambem se o preco "
        "cair 20% abaixo da entrada",
        "reguas-v1", 1, "2026-09-22T14:47:47+00:00", {**_REGUAS, **_STOP},
    ),
    Carteira(
        "T2", "Tartarugas", "tendencia", "tartarugas", False,
        "A estratégia de tendência mais famosa do mercado (Turtle Trading). Compra quando o preço "
        "bate o maior valor dos últimos 55 dias e vende quando cai ao menor dos últimos 20.",
        "compra quando o preco fecha acima do maior fechamento dos 55 dias anteriores; vende "
        "quando fecha abaixo do menor dos 20 dias anteriores; o stop fica a 2 vezes a oscilacao "
        "diaria abaixo da compra (no maximo 20%)",
        "tartarugas-s2-v1", 2, None,
        {"entrada_dias": tartarugas.ENTRADA_DIAS, "saida_dias": tartarugas.SAIDA_DIAS,
         "n_dias": tartarugas.N_DIAS, "stop_em_n": tartarugas.STOP_EM_N, "piso": tartarugas.PISO_DO_STOP},
    ),
    Carteira(
        "T3", "Conselho de IAs", "tendencia", "painel", False,
        "Três IAs gratuitas de empresas diferentes olham os números do dia e dizem se a tendência "
        "é de alta, de lado ou de baixa. Compra quando a maioria vê alta e nenhuma vê baixa.",
        "tres IAs votam uma vez por dia se a tendencia das proximas semanas e de alta, de lado ou "
        "de baixa; compra quando a soma dos votos chega a +2 (duas altas e nenhuma baixa); vende "
        "quando a soma fica em -1 ou menos; vende tambem se o preco cair 20% abaixo da entrada",
        "painel-t-v1", 3, None, {**_PAINEL, **_STOP},
    ),
    Carteira(
        "G1", "Réguas com meta", "stop_gain", "reguas", True,
        "Compra como as Réguas, mas vende quando o lucro chega a uma meta (cerca de +9% no BTC e "
        "+12% no ETH hoje). Depois espera o preço recuar e a alta voltar para comprar de novo.",
        "compra como as Reguas (4 de 6 prazos em alta); vende quando o lucro atinge a meta de 3 "
        "vezes a oscilacao diaria, quando a tendencia vira ou se cair 20%; depois da meta, so "
        "recompra quando o preco recuar e a alta voltar",
        "reguas-alvo-v1", 4, None, {**_REGUAS, **_STOP, **_ALVO, "rearme": "votos<=3 depois votos>=4"},
    ),
    Carteira(
        "G2", "Repique", "stop_gain", "rsi2", False,
        "Estratégia famosa de curto prazo (RSI 2 de Connors): com o mercado em alta longa, compra "
        "depois de dois dias de queda forte e vende no primeiro repique.",
        "so opera acima da media de 200 dias; compra quando o RSI de 2 dias fica abaixo de 10 "
        "(queda forte e curta) e vende quando o preco fecha acima da media de 5 dias (o repique); "
        "vende tambem se cair 20%",
        "rsi2-connors-v1", 5, None,
        {"sma_filtro": rsi2.SMA_FILTRO, "rsi_n": rsi2.RSI_N, "rsi_entra": rsi2.RSI_ENTRA,
         "sma_saida": rsi2.SMA_SAIDA, **_STOP},
    ),
    Carteira(
        "G3", "Conselho com meta", "stop_gain", "painel", True,
        "Compra como o Conselho de IAs, mas vende quando o lucro chega à mesma meta das Réguas "
        "com meta. Depois só recompra quando o conselho deixar de ver alta e voltar a ver.",
        "compra quando o conselho de tres IAs soma +2; vende na meta de 3 vezes a oscilacao "
        "diaria, quando o conselho soma -1 ou menos, ou se cair 20%; depois da meta, so recompra "
        "quando o conselho deixar de ver alta e voltar a ver",
        "painel-alvo-v1", 6, None, {**_PAINEL, **_STOP, **_ALVO},
    ),
)

POR_ID = {c.id: c for c in CARTEIRAS}


def sincronizar_catalogo(supabase, ativas: list[str] | None = None, agora: datetime | None = None) -> None:
    """
    Grava o catalogo em `carteiras`. `ativas` sao as carteiras que o ciclo
    ao vivo esta rodando agora: so elas ficam `ativa` e ganham `ativa_desde`
    -- preenchido uma vez, na primeira execucao em que a carteira rodou. A
    T1 guarda a data da troca para a regra de tendencia (22/09/2026).
    """
    agora = agora or datetime.now(timezone.utc)
    ativas = set(ativas or [])
    existentes = {
        linha["id"]: linha
        for linha in (supabase.table("carteiras").select("id,ativa_desde").execute().data or [])
    }
    linhas = []
    for c in CARTEIRAS:
        desde = (existentes.get(c.id) or {}).get("ativa_desde") or c.ativa_desde
        if desde is None and c.id in ativas:
            desde = agora.isoformat()
        linhas.append({
            "id": c.id, "nome": c.nome, "descricao_leiga": c.descricao_leiga,
            "descricao_regra": c.descricao_regra, "familia": c.familia,
            "regra_versao": c.regra_versao, "parametros": c.parametros,
            "ativa_desde": desde, "ativa": desde is not None, "ordem": c.ordem,
        })
    supabase.table("carteiras").upsert(linhas, on_conflict="id").execute()
