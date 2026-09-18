/**
 * Dados da carteira do forward test, compartilhados pela página Carteira
 * e pela página Motor.
 *
 * Tudo aqui deriva do banco (tabelas `decisions` e `portfolio`) e do preço
 * público da Binance. Nenhum número é escrito à mão.
 *
 * ## A conta fecha
 *
 * patrimônio − capital inicial = realizado + em aberto, exatamente:
 *
 * - o caixa de cada conta já é o capital inicial mais o resultado de
 *   todas as operações fechadas;
 * - o valor de uma posição aberta menos o que custou para abrir (preço ×
 *   quantidade + taxa de entrada) é o resultado em aberto.
 *
 * A página mostra as três parcelas; se elas não somassem, seria bug.
 */

import { getSupabaseClient } from "@/lib/supabase";

export const CAPITAL_POR_CONTA = 10_000;

export type Decisao = {
  id: string;
  created_at: string;
  symbol: string;
  status: string;
  candle_fechamento_em: number | null;
  market_snapshot: {
    preco_atual: number;
    conta?: { caixa: number; quantidade: number };
    deslize_pct?: number | null;
  } | null;
  llm_output: { direction: string; horizon: string; confidence: number; reasoning: string } | null;
  risk_result: {
    acao_final: string;
    aprovado: boolean;
    override_do_llm: boolean;
    motivo: string;
    direcao_do_llm?: string | null;
  } | null;
  order_result: {
    lado: string;
    preco: number;
    quantidade?: number;
    taxa?: number;
    stop_loss?: number | null;
    take_profit?: number | null;
    caixa_depois?: number | null;
    resultado?: number | null;
    resultado_pct?: number | null;
    motivo?: string | null;
  } | null;
};

export type Conta = {
  asset: string;
  quantity: number;
  caixa: number | null;
  preco_entrada: number | null;
  stop_loss: number | null;
  take_profit: number | null;
};

export type Operacao = {
  par: string;
  entradaEm: string;
  saidaEm: string;
  precoEntrada: number;
  precoSaida: number;
  resultado: number;
  resultadoPct: number;
  motivo: string;
};

export type Posicao = {
  par: string;
  aberta: boolean;
  preco: number | null;
  caixa: number;
  quantidade: number;
  valor: number;
  precoEntrada: number | null;
  custo: number | null;
  emAberto: number | null;
  emAbertoPct: number | null;
  stop: number | null;
  alvo: number | null;
  abertaEm: string | null;
};

export async function carregar() {
  const sb = getSupabaseClient();
  const [ciclos, contas, coleta] = await Promise.all([
    sb
      .from("decisions")
      .select(
        "id, created_at, symbol, status, candle_fechamento_em, market_snapshot, llm_output, risk_result, order_result"
      )
      .not("candle_fechamento_em", "is", null)
      .order("created_at", { ascending: true }),
    sb.from("portfolio").select("asset, quantity, caixa, preco_entrada, stop_loss, take_profit"),
    sb
      .from("decisions")
      .select("created_at")
      .is("candle_fechamento_em", null)
      .order("created_at", { ascending: false })
      .limit(1),
  ]);

  if (ciclos.error) throw new Error(`Supabase: ${ciclos.error.message}`);
  if (contas.error) throw new Error(`Supabase: ${contas.error.message}`);

  return {
    ciclos: (ciclos.data ?? []) as Decisao[],
    contas: (contas.data ?? []) as Conta[],
    ultimaColeta: (coleta.data?.[0]?.created_at as string | undefined) ?? null,
  };
}

/**
 * Preço ao vivo pelo endpoint público da Binance.
 *
 * O último ciclo pode ter horas de atraso (o agendamento do GitHub roda,
 * em média, a cada 3–4 h), e uma área de investimento que mostra o valor
 * de horas atrás engana. `data-api.binance.vision` é o mesmo endpoint que
 * o backend usa: sem credencial e sem bloqueio geográfico para os EUA, onde
 * as funções da Vercel rodam.
 *
 * Se falhar, devolve vazio e a página cai no preço do último ciclo —
 * dizendo que caiu.
 */
export async function precosAoVivo(pares: string[]): Promise<Map<string, number>> {
  const saida = new Map<string, number>();
  if (!pares.length) return saida;
  try {
    const url =
      "https://data-api.binance.vision/api/v3/ticker/price?symbols=" +
      encodeURIComponent(JSON.stringify(pares));
    const resp = await fetch(url, { cache: "no-store", signal: AbortSignal.timeout(3500) });
    if (!resp.ok) return saida;
    const dados = (await resp.json()) as { symbol: string; price: string }[];
    for (const d of dados) saida.set(d.symbol, Number(d.price));
  } catch {
    // sem preço ao vivo: a página usa o do último ciclo e avisa
  }
  return saida;
}

/** Pares de BUY → SELL, na ordem em que aconteceram, por ativo. */
export function montarOperacoes(ciclos: Decisao[]): Operacao[] {
  const abertas = new Map<string, Decisao>();
  const saida: Operacao[] = [];
  for (const c of ciclos) {
    const o = c.order_result;
    if (!o) continue;
    if (o.lado === "BUY") {
      abertas.set(c.symbol, c);
    } else if (o.lado === "SELL") {
      const ent = abertas.get(c.symbol);
      abertas.delete(c.symbol);
      // Resultado pelo FLUXO DE CAIXA, e nao pelo `resultado` gravado. As
      // operacoes ate 18/09 foram gravadas ignorando a taxa de compra (bug
      // corrigido em live/execucao.py), e este calculo vale para as antigas e
      // as novas: custo = o que saiu do caixa na compra; receita = o que
      // voltou na venda, ja liquido da taxa de saida.
      const b = ent?.order_result;
      const custo = b ? b.preco * (b.quantidade ?? 0) + (b.taxa ?? 0) : null;
      const receita =
        o.caixa_depois ?? (o.quantidade ? o.preco * o.quantidade - (o.taxa ?? 0) : null);
      const resultado = custo !== null && receita !== null ? receita - custo : (o.resultado ?? 0);
      saida.push({
        par: c.symbol,
        entradaEm: ent?.created_at ?? c.created_at,
        saidaEm: c.created_at,
        precoEntrada: b?.preco ?? 0,
        precoSaida: o.preco,
        resultado,
        resultadoPct: custo ? (resultado / custo) * 100 : (o.resultado_pct ?? 0),
        motivo: o.motivo ?? "",
      });
    }
  }
  return saida.reverse();
}

/** Estado de cada ativo negociado, marcado a mercado pelo preço dado. */
export function montarPosicoes(
  pares: string[],
  contas: Conta[],
  ciclos: Decisao[],
  preco: Map<string, number>
): Posicao[] {
  return pares.map((par) => {
    const conta = contas.find((c) => c.asset === par);
    const p = preco.get(par) ?? null;
    const quantidade = conta?.quantity ?? 0;
    const caixa = conta?.caixa ?? CAPITAL_POR_CONTA;
    const aberta = quantidade > 0;

    let custo: number | null = null;
    let abertaEm: string | null = null;
    if (aberta) {
      const compra = [...ciclos]
        .reverse()
        .find((c) => c.symbol === par && c.order_result?.lado === "BUY");
      const o = compra?.order_result;
      if (o) {
        custo = o.preco * (o.quantidade ?? quantidade) + (o.taxa ?? 0);
        abertaEm = compra!.created_at;
      } else if (conta?.preco_entrada) {
        custo = conta.preco_entrada * quantidade;
      }
    }

    const valor = aberta && p !== null ? quantidade * p : 0;
    const emAberto = aberta && custo !== null && p !== null ? valor - custo : null;

    return {
      par,
      aberta,
      preco: p,
      caixa,
      quantidade,
      valor,
      precoEntrada: conta?.preco_entrada ?? null,
      custo,
      emAberto,
      emAbertoPct: emAberto !== null && custo ? (emAberto / custo) * 100 : null,
      stop: conta?.stop_loss ?? null,
      alvo: conta?.take_profit ?? null,
      abertaEm,
    };
  });
}

export type PontoCurva = { t: string; equity: number };

/** Patrimônio total por ciclo, somando as contas de cada par. */
export function montarCurva(ciclos: Decisao[], pares: string[]): PontoCurva[] {
  const ultimo = new Map<string, number>(pares.map((p) => [p, CAPITAL_POR_CONTA]));
  const saida: PontoCurva[] = [];
  for (const c of ciclos) {
    const ms = c.market_snapshot;
    const conta = ms?.conta;
    if (!ms || !conta) continue;
    ultimo.set(c.symbol, (conta.caixa ?? 0) + (conta.quantidade ?? 0) * ms.preco_atual);
    let total = 0;
    for (const p of pares) total += ultimo.get(p) ?? CAPITAL_POR_CONTA;
    saida.push({ t: c.created_at, equity: total });
  }
  return saida;
}

/** Último preço gravado por par — o recurso quando não há preço ao vivo. */
export function precosDoUltimoCiclo(ciclos: Decisao[]): Map<string, number> {
  const m = new Map<string, number>();
  for (const c of ciclos) if (c.market_snapshot) m.set(c.symbol, c.market_snapshot.preco_atual);
  return m;
}

export const usd = (v: number, casas = 2) =>
  v.toLocaleString("pt-BR", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: casas,
    maximumFractionDigits: casas,
  });

export const sinal = (v: number) => (v > 0 ? "+" : v < 0 ? "−" : "");
