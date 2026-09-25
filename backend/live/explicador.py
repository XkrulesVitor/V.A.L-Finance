"""
O LLM que so explica -- a partir de 2026-09-22.

Ate aqui o LLM decidia: lia indicadores e devolvia uma tese de compra ou
venda. Os estudos de setembro/2026 (ARCHITECTURE.md, secao "Votacao
entre estrategias e tendencia diaria") nao acharam evidencia de que ele
acrescente vantagem sobre uma regra -- e os backtests dele estao
contaminados por memorizacao do periodo anterior ao corte do modelo.
Entao a decisao virou deterministica (`estrategia/tendencia_diaria.py`)
e o LLM ficou com o que ele faz bem: traduzir o que aconteceu em uma
frase que qualquer pessoa entende.

## Nunca bloqueia

A explicacao e pedida DEPOIS que a operacao ja foi executada e gravada.
Se o provedor cair, a operacao nao muda -- so fica sem frase. Por isso
`explicar` nunca levanta excecao: devolve o texto ou o motivo da falha.

## Nem trava

"Nao bloquear" nao e so capturar excecao: uma chamada que nunca volta
tambem bloqueia. A explicacao roda dentro do ciclo de um par, e o par
seguinte so e conferido depois dela; sem limite, uma conexao pendurada com
o provedor segurava o outro par ate o job ser morto (15 min). Por isso o
provedor do explicador e criado com `TIMEOUT_S` curto.

## Custo e lugar no job

So e chamado quando ha operacao, e fora do caminho critico: as operacoes
sao gravadas com `explicacao_pendente` e `explicar_pendentes` preenche as
frases no fim do job, com teto de 12 por dia (a cota gratuita do Gemini e
de 500 por dia; o painel usa outra parte dela). As que nao couberem ficam
para os ciclos seguintes; depois de 3 falhas, a operacao fica sem frase.
"""

import json

from pydantic import BaseModel, Field

TIMEOUT_S = 30.0

INSTRUCAO = (
    "Voce explica operacoes de uma carteira simulada de criptomoedas para "
    "uma pessoa leiga, em portugues do Brasil. Uma ou duas frases curtas. "
    "A decisao ja foi tomada por uma regra fixa: voce nao opina sobre ela, "
    "nao faz previsao de preco e nao recomenda nada. Diga o que a regra viu "
    "e o que fez, usando so os dados recebidos. Sem jargao: em vez de "
    "\"media movel\", diga \"a media dos ultimos N dias\"."
)


class Explicacao(BaseModel):
    texto: str = Field(description="uma ou duas frases, sem previsao e sem recomendacao")


class Explicador:
    def __init__(self, provedor=None):
        self._provedor = provedor

    @property
    def provedor(self):
        # Criado sob demanda: um ciclo sem operacao nao precisa de chave.
        if self._provedor is None:
            from brain.provedores import criar_provedor
            # Gemini EXPLICITO: `criar_provedor()` sem nome segue LLM_PROVEDOR,
            # e o provedor "claude" e pago. O projeto e gratuito.
            self._provedor = criar_provedor("gemini", timeout_s=TIMEOUT_S)
        return self._provedor

    def explicar(self, fatos: dict) -> tuple[str | None, str | None]:
        """(texto, erro). Exatamente um dos dois e None."""
        try:
            prompt = "Operacao executada:\n" + json.dumps(fatos, ensure_ascii=False, indent=1)
            resposta = self.provedor.gerar(INSTRUCAO, prompt, Explicacao)
            texto = (resposta.texto or "").strip()
            return (texto[:500], None) if texto else (None, "resposta vazia")
        except Exception as erro:  # noqa: BLE001 -- explicar nunca derruba o ciclo
            return None, f"{type(erro).__name__}: {erro}"[:300]


TETO_POR_DIA = 12
TENTATIVAS_POR_OPERACAO = 3


def fatos_da_operacao(carteira, linha: dict) -> dict:
    """O que o LLM recebe: a regra DA CARTEIRA que operou e o que ela viu."""
    ordem = linha.get("order_result") or {}
    f = linha.get("features") or {}
    fatos = {
        "carteira": carteira.nome,
        "ativo": linha["symbol"].replace("USDT", ""),
        "operacao": "compra" if ordem.get("lado") == "BUY" else "venda",
        "preco": round(float(ordem.get("preco") or 0), 4),
        "motivo": ordem.get("motivo"),
        "regra": carteira.descricao_regra,
    }
    if carteira.regra == "reguas":
        fatos["prazos_em_alta"] = f.get("votos")
        fatos["prazos"] = {f"{n} dias": ("acima" if p.get("acima") else "abaixo")
                           for n, p in (f.get("prazos") or {}).items()}
    elif carteira.regra == "tartarugas":
        fatos.update({k: f.get(k) for k in ("maxima_55d", "minima_20d", "n_pct")})
    elif carteira.regra == "rsi2":
        fatos.update({k: f.get(k) for k in ("rsi2", "sma200", "sma5")})
    elif carteira.regra == "painel":
        fatos.update({"votos_das_ias": f.get("votos"), "soma": f.get("soma")})
    if ordem.get("alvo_pct") is not None:
        fatos["meta_de_lucro_pct"] = round(float(ordem["alvo_pct"]), 1)
    if ordem.get("resultado_pct") is not None:
        fatos["resultado_da_operacao_pct"] = round(float(ordem["resultado_pct"]), 2)
    return fatos


def explicar_pendentes(supabase, explicador, catalogo: dict, agora, tem_prazo) -> int:
    """
    Fase de explicacoes do job: operacoes com `explicacao_pendente`, as mais
    antigas primeiro, enquanto `tem_prazo()` e o teto do dia deixarem.
    Devolve quantas frases foram pedidas. Nunca levanta.
    """
    inicio_do_dia = agora.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    try:
        feitas = supabase.table("decisions").select("id").eq("status", "executed")             .gte("order_result->>explicado_em", inicio_do_dia).execute().data or []
        pendentes = supabase.table("decisions").select("id,carteira,symbol,order_result,features")             .eq("status", "executed").eq("order_result->>explicacao_pendente", "true")             .order("created_at").limit(20).execute().data or []
    except Exception:  # noqa: BLE001
        return 0
    pedidas = 0
    for linha in pendentes:
        ordem = linha.get("order_result") or {}
        if not ordem.get("explicacao_pendente") or linha.get("carteira") not in catalogo:
            continue
        if len(feitas) + pedidas >= TETO_POR_DIA or not tem_prazo():
            break
        texto, erro = explicador.explicar(fatos_da_operacao(catalogo[linha["carteira"]], linha))
        pedidas += 1
        tentativas = int(ordem.get("explicacao_tentativas") or 0) + 1
        novo = {**ordem, "explicacao": texto, "explicacao_tentativas": tentativas,
                "explicado_em": agora.isoformat(),
                "explicacao_pendente": texto is None and tentativas < TENTATIVAS_POR_OPERACAO}
        if erro:
            novo["explicacao_erro"] = erro
        try:
            supabase.table("decisions").update({"order_result": novo}).eq("id", linha["id"]).execute()
        except Exception:  # noqa: BLE001 -- perder a frase e aceitavel
            pass
    return pedidas
