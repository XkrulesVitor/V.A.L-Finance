/**
 * Dados da página Motor: o fluxo de decisões, de todas as carteiras ou de
 * uma só (`/motor?carteira=G1`).
 *
 * Nada aqui lê `decisions` inteira. O fluxo mostra as decisões mais
 * recentes (`limit`), o total vem de uma contagem sem linhas (`head`), e o
 * deslize lê só a coluna que usa das ordens executadas.
 */

import { getSupabaseClient } from "@/lib/supabase";
import { ERA_DAS_REGRAS, PARES, type UltimaLeitura, paginar, ultimaLeitura } from "@/lib/carteira";
import { lerCatalogo } from "@/lib/carteiras";
import { etiquetaDaEspera, leituraCurta } from "@/lib/rotulos";

/** Uma linha do fluxo, já sem `features` (a leitura vem resumida). */
export type LinhaDoFluxo = {
  id: string;
  created_at: string;
  carteira: string;
  symbol: string;
  status: string;
  /** Linha da estratégia antiga da T1, em que o LLM decidia. */
  hibrida: boolean;
  leitura: { texto: string; titulo: string } | null;
  /** Trava da regra que explica um NO_TRADE: desarmada, travada, sem quórum… */
  etiqueta: string | null;
  preco: number | null;
  llm_output: { direction: string; horizon: string; confidence: number; reasoning: string } | null;
  risk_result: {
    acao_final: string;
    aprovado?: boolean;
    override_do_llm?: boolean;
    motivo: string;
    direcao_do_llm?: string | null;
  } | null;
  order_result: {
    lado: string;
    preco: number;
    resultado_pct?: number | null;
    explicacao?: string | null;
    motivo?: string | null;
  } | null;
};

type Bruta = Omit<LinhaDoFluxo, "hibrida" | "leitura" | "etiqueta"> & {
  features: Record<string, unknown> | null;
};

const ERA_MS = Date.parse(ERA_DAS_REGRAS);

export async function carregarMotor(filtro: string | null) {
  const sb = getSupabaseClient();
  const limite = filtro ? 60 : 120;

  const decisoes = (colunas: string, opcoes?: { count: "exact"; head: true }) => {
    const q = sb.from("decisions").select(colunas, opcoes).not("candle_fechamento_em", "is", null);
    return filtro ? q.eq("carteira", filtro) : q;
  };

  const [catalogo, recentes, total, primeira, deslizes, coleta, contas, ...ultimas] = await Promise.all([
    lerCatalogo(sb),
    decisoes(
      "id, created_at, carteira, symbol, status, features, preco:market_snapshot->preco_atual, llm_output, risk_result, order_result"
    )
      .order("created_at", { ascending: false })
      .order("id", { ascending: false })
      .limit(limite),
    decisoes("id", { count: "exact", head: true }),
    decisoes("created_at").order("created_at", { ascending: true }).limit(1),
    paginar<{ deslize: number | null }>((de, ate) => {
      const q = sb
        .from("decisions")
        .select("deslize:order_result->referencia_backtest->deslize_pct")
        .eq("status", "executed");
      return (filtro ? q.eq("carteira", filtro) : q)
        .order("created_at", { ascending: true })
        .order("id", { ascending: true })
        .range(de, ate);
    }),
    sb
      .from("decisions")
      .select("created_at")
      .is("candle_fechamento_em", null)
      .order("created_at", { ascending: false })
      .limit(1),
    (filtro
      ? sb.from("portfolio").select("carteira, asset, quantity").eq("carteira", filtro)
      : sb.from("portfolio").select("carteira, asset, quantity")),
    ...(filtro ? PARES.map((p) => ultimaLeitura(sb, filtro, p)) : []),
  ]);

  if (recentes.error) throw new Error(`Supabase: ${recentes.error.message}`);
  if (contas.error) throw new Error(`Supabase: ${contas.error.message}`);

  const fluxo: LinhaDoFluxo[] = ((recentes.data ?? []) as unknown as Bruta[]).map(({ features, ...c }) => {
    const hibrida = c.carteira === "T1" && Date.parse(c.created_at) < ERA_MS;
    return {
      ...c,
      hibrida,
      leitura: hibrida ? null : leituraCurta(features),
      etiqueta: hibrida ? null : etiquetaDaEspera(c.risk_result?.motivo),
    };
  });

  const valores = deslizes.map((d) => d.deslize).filter((v): v is number => typeof v === "number");

  return {
    catalogo,
    fluxo,
    total: total.count ?? null,
    primeira: ((primeira.data ?? [])[0] as unknown as { created_at: string } | undefined)?.created_at ?? null,
    deslize: valores.length ? valores.reduce((a, b) => a + b, 0) / valores.length : null,
    operacoesMedidas: valores.length,
    ultimaColeta: ((coleta.data ?? [])[0] as { created_at: string } | undefined)?.created_at ?? null,
    contas: (contas.data ?? []) as { carteira: string; asset: string; quantity: number }[],
    leituras: new Map<string, UltimaLeitura | null>(filtro ? PARES.map((p, i) => [p, ultimas[i]]) : []),
  };
}
