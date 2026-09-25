/**
 * Dados de UMA carteira: contas, operações, posições e curva.
 *
 * Tudo aqui deriva do banco (`portfolio`, `decisions`, `patrimonio_diario`)
 * e do preço público da Binance. Nenhum número é escrito à mão.
 *
 * Desde setembro/2026 são seis carteiras (T1…G3), cada uma com uma conta
 * de US$ 10.000 por ativo. Toda consulta a `portfolio` e `decisions` leva
 * `.eq("carteira", id)`: sem isso, a conta de uma carteira seria somada à
 * de outra sem erro nenhum.
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
import type { Resumo } from "@/lib/rotulos";
import { resumirLeitura } from "@/lib/rotulos";

export const CAPITAL_POR_CONTA = 10_000;
/** Taxa por lado, a mesma de `backend/live/execucao.py`. */
export const TAXA = 0.001;
// Três grandes e três menores, na ordem em que aparecem no site.
export const PARES = ["BTCUSDT", "ETHUSDT", "XRPUSDT", "LINKUSDT", "ADAUSDT", "DOGEUSDT"];

/**
 * Instante em que a T1 trocou a estratégia híbrida (LLM decidia) pela regra
 * de tendência (LLM só explica). As contas não foram zeradas: o histórico
 * da T1 antes disto é da estratégia antiga.
 */
export const ERA_DAS_REGRAS = "2026-09-22T14:47:47Z";
export const PRAZOS = [10, 20, 30, 50, 70, 100] as const;
export const ENTRA_COM = 4;
export const SAI_COM = 2;

type Cliente = ReturnType<typeof getSupabaseClient>;

/** O que a régua das Réguas (T1, G1) viu no último dia fechado. */
export type Leitura = {
  votos: number | null;
  dia: string | null;
  prazos: Record<string, { media: number; acima: boolean }>;
  /**
   * `false` depois de uma saída, até fechar um dia novo: a regra não entra
   * nem com votos suficientes. Ausente em leituras antigas.
   */
  podeEntrar: boolean | null;
  em: string;
};

/** Uma decisão que virou ordem (status `executed`). */
export type Decisao = {
  id: string;
  created_at: string;
  symbol: string;
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
    explicacao?: string | null;
    /** Fechamento de 1h que cruzou o stop/meta (ms, termina em ...999). */
    gatilho_em?: number | null;
    preco_entrada?: number | null;
    alvo_pct?: number | null;
  } | null;
};

export type Conta = {
  carteira: string;
  asset: string;
  quantity: number;
  caixa: number | null;
  preco_entrada: number | null;
  stop_loss: number | null;
  take_profit: number | null;
  alvo_pct: number | null;
  armado: boolean | null;
  entrada_em: number | null;
  ultima_saida_motivo: string | null;
};

export const COLUNAS_DA_CONTA =
  "carteira, asset, quantity, caixa, preco_entrada, stop_loss, take_profit, alvo_pct, armado, entrada_em, ultima_saida_motivo";

/** A última decisão concluída de uma carteira × par: o que a regra viu. */
export type UltimaLeitura = {
  created_at: string;
  features: Record<string, unknown> | null;
  preco: number | null;
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
  explicacao: string | null;
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
  /** Só nas Réguas (T1, G1): os seis prazos. */
  tendencia: Leitura | null;
  /** A leitura da regra em uma linha, para as outras carteiras. */
  resumo: Resumo | null;
  /** G1 e G3: a carteira tem meta de lucro. */
  comMeta: boolean;
  /**
   * G1 e G3: `false` depois de vender na meta, até o sinal recuar e voltar.
   * `null` nas outras carteiras e antes do primeiro ciclo.
   */
  armada: boolean | null;
  /** A frase do LLM sobre a compra, quando houver. */
  explicacao: string | null;
};

/* ------------------------------------------------------------- leituras */

/*
 * O PostgREST do Supabase devolve no máximo 1000 linhas por consulta (Max
 * rows, padrão do projeto). Uma consulta crescente sem paginação passaria
 * a devolver as 1000 linhas MAIS ANTIGAS: a página congelaria no passado
 * sem erro nenhum. Então toda leitura que cresce com o tempo é paginada
 * até vir uma página incompleta.
 */
const PAGINA = 1000;

type Pagina<T> = PromiseLike<{ data: T[] | null; error: { message: string } | null }>;

export async function paginar<T>(pedir: (de: number, ate: number) => unknown): Promise<T[]> {
  const saida: T[] = [];
  for (let de = 0; ; de += PAGINA) {
    const { data, error } = await (pedir(de, de + PAGINA - 1) as Pagina<T>);
    if (error) throw new Error(`Supabase: ${error.message}`);
    saida.push(...(data ?? []));
    if (!data || data.length < PAGINA) return saida;
  }
}

/** Só as ordens executadas da carteira, com as colunas que a página usa. */
function executadas(sb: Cliente, carteira: string) {
  return paginar<Decisao>((de, ate) =>
    sb
      .from("decisions")
      .select("id, created_at, symbol, order_result")
      .eq("carteira", carteira)
      .eq("status", "executed")
      .order("created_at", { ascending: true })
      .order("id", { ascending: true }) // desempate estável entre páginas
      .range(de, ate)
  );
}

export type LinhaDiaria = { asset: string; dia_utc: string; patrimonio: number; posicionada?: boolean };

/** Patrimônio de cada conta no fechamento de cada dia UTC. */
function diarioDa(sb: Cliente, carteira: string) {
  return paginar<LinhaDiaria>((de, ate) =>
    sb
      .from("patrimonio_diario")
      .select("asset, dia_utc, patrimonio")
      .eq("carteira", carteira)
      .order("dia_utc", { ascending: true })
      .order("asset", { ascending: true })
      .range(de, ate)
  );
}

type CicloDaCurva = {
  created_at: string;
  symbol: string;
  preco: number | null;
  conta: { caixa: number; quantidade: number } | null;
};

/**
 * Os ciclos da carteira, só com o preço e a conta de cada um — o que a
 * curva por ciclos precisa. `ate` corta no instante em que a curva diária
 * assume, e isso deixa a leitura de tamanho fixo.
 */
function ciclosDaCurva(sb: Cliente, carteira: string, ate?: string) {
  return paginar<CicloDaCurva>((de, fim) => {
    let q = sb
      .from("decisions")
      .select("created_at, symbol, preco:market_snapshot->preco_atual, conta:market_snapshot->conta")
      .eq("carteira", carteira)
      .not("candle_fechamento_em", "is", null);
    if (ate) q = q.lt("created_at", ate);
    return q.order("created_at", { ascending: true }).order("id", { ascending: true }).range(de, fim);
  });
}

export async function ultimaLeitura(sb: Cliente, carteira: string, par: string): Promise<UltimaLeitura | null> {
  const { data, error } = await sb
    .from("decisions")
    .select("created_at, features, preco:market_snapshot->preco_atual")
    .eq("carteira", carteira)
    .eq("symbol", par)
    .not("candle_fechamento_em", "is", null)
    .neq("status", "processando")
    .order("created_at", { ascending: false })
    .limit(1);
  if (error) throw new Error(`Supabase: ${error.message}`);
  return ((data ?? [])[0] as UltimaLeitura | undefined) ?? null;
}

/** A leitura das Réguas, quando a linha é das Réguas (votos é um número). */
export function leituraDasReguas(u: UltimaLeitura | null): Leitura | null {
  const f = u?.features;
  if (!f || typeof f.votos !== "number") return null;
  return {
    votos: f.votos,
    dia: typeof f.dia === "string" ? f.dia : null,
    prazos: (f.prazos as Leitura["prazos"]) ?? {},
    podeEntrar: typeof f.pode_entrar === "boolean" ? f.pode_entrar : null,
    em: u!.created_at,
  };
}

/**
 * Tudo o que a página de uma carteira mostra.
 *
 * A curva prefere `patrimonio_diario` (uma linha por conta por dia). Os
 * ciclos só entram para o trecho ANTERIOR à primeira linha diária — a
 * história da T1 desde 04/09 — e, enquanto houver menos de dois dias
 * gravados, como a curva inteira.
 */
export async function carregarCarteira(carteira: string) {
  const sb = getSupabaseClient();
  const [contas, ordens, diario, ...ultimas] = await Promise.all([
    sb.from("portfolio").select(COLUNAS_DA_CONTA).eq("carteira", carteira),
    executadas(sb, carteira),
    diarioDa(sb, carteira),
    ...PARES.map((p) => ultimaLeitura(sb, carteira, p)),
  ]);
  if (contas.error) throw new Error(`Supabase: ${contas.error.message}`);

  const dias = [...new Set(diario.map((d) => d.dia_utc))];
  const ciclos =
    dias.length >= 2
      ? await ciclosDaCurva(sb, carteira, fimDoDia(dias[0]))
      : await ciclosDaCurva(sb, carteira);

  const leituras = new Map<string, UltimaLeitura | null>(PARES.map((p, i) => [p, ultimas[i]]));
  return {
    contas: (contas.data ?? []) as Conta[],
    ordens,
    diario,
    ciclos,
    leituras,
  };
}

/* ------------------------------------------------------------- preço */

/**
 * Preço ao vivo pelo endpoint público da Binance.
 *
 * O último ciclo pode ter horas de atraso (o agendamento do GitHub roda,
 * em média, a cada 3–4 h), e uma área de investimento que mostra o valor
 * de horas atrás engana. `data-api.binance.vision` é o mesmo endpoint que
 * o backend usa: sem credencial e sem bloqueio geográfico para os EUA, onde
 * as funções da Vercel rodam.
 *
 * Guardado por 5 minutos, o mesmo `revalidate` das páginas: um `no-store`
 * aqui tornaria a página dinâmica, e cada visita voltaria a consultar o
 * Supabase — exatamente o tráfego que a seção 11.3 da especificação corta.
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
    const resp = await fetch(url, { next: { revalidate: 300 }, signal: AbortSignal.timeout(3500) });
    if (!resp.ok) return saida;
    const dados = (await resp.json()) as { symbol: string; price: string }[];
    for (const d of dados) saida.set(d.symbol, Number(d.price));
  } catch {
    // sem preço ao vivo: a página usa o do último ciclo e avisa
  }
  return saida;
}

/* ------------------------------------------------------------- montagem */

/** Pares de BUY → SELL, na ordem em que aconteceram, por ativo. */
export function montarOperacoes(ordens: Decisao[]): Operacao[] {
  const abertas = new Map<string, Decisao>();
  const saida: Operacao[] = [];
  for (const c of ordens) {
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
      // Sem a linha da compra (perdida numa falha entre gravar a conta e
      // concluir a decisão), o preço de entrada vem da própria venda.
      const precoEntrada = b?.preco ?? o.preco_entrada ?? 0;
      const receita =
        o.caixa_depois ?? (o.quantidade ? o.preco * o.quantidade - (o.taxa ?? 0) : null);
      const resultado = custo !== null && receita !== null ? receita - custo : (o.resultado ?? 0);
      saida.push({
        par: c.symbol,
        entradaEm: ent?.created_at ?? c.created_at,
        // Saída por stop/meta aconteceu no fechamento que cruzou o nível,
        // não na hora do ciclo que a percebeu (até ~6 h depois).
        saidaEm: o.gatilho_em != null ? new Date(o.gatilho_em + 1).toISOString() : c.created_at,
        precoEntrada,
        precoSaida: o.preco,
        resultado,
        resultadoPct: custo ? (resultado / custo) * 100 : (o.resultado_pct ?? 0),
        motivo: o.motivo ?? "",
        explicacao: o.explicacao ?? null,
      });
    }
  }
  return saida.reverse();
}

/** Estado de cada ativo da carteira, marcado a mercado pelo preço dado. */
export function montarPosicoes(
  pares: string[],
  contas: Conta[],
  ordens: Decisao[],
  preco: Map<string, number>,
  leituras: Map<string, UltimaLeitura | null> = new Map(),
  { comMeta = false, iniciada = true }: { comMeta?: boolean; iniciada?: boolean } = {}
): Posicao[] {
  return pares.map((par) => {
    const conta = contas.find((c) => c.asset === par);
    const p = preco.get(par) ?? null;
    const quantidade = conta?.quantity ?? 0;
    const caixa = conta?.caixa ?? CAPITAL_POR_CONTA;
    const aberta = quantidade > 0;

    let custo: number | null = null;
    let abertaEm: string | null = null;
    let explicacao: string | null = null;
    if (aberta) {
      // A última operação do par, e não a última COMPRA: se a linha da compra
      // atual se perdeu (falha entre gravar a conta e concluir a decisão), a
      // última compra encontrada seria a anterior, já vendida, e o custo sairia
      // errado. Só vale como compra desta posição se for BUY ao preço de
      // entrada que a conta guarda; senão, cai no preço de entrada da conta.
      const compra = [...ordens].reverse().find((c) => c.symbol === par && c.order_result);
      const candidata = compra?.order_result;
      const bate =
        candidata?.lado === "BUY" &&
        (!conta?.preco_entrada ||
          Math.abs(candidata.preco - conta.preco_entrada) <= 1e-9 * conta.preco_entrada);
      const o = bate ? candidata : null;
      if (o) {
        custo = o.preco * (o.quantidade ?? quantidade) + (o.taxa ?? 0);
        abertaEm = compra!.created_at;
        explicacao = o.explicacao ?? null;
      } else if (conta?.preco_entrada) {
        custo = custoDaEntrada(conta.preco_entrada, quantidade);
      }
    }

    const valor = aberta && p !== null ? quantidade * p : 0;
    const emAberto = aberta && custo !== null && p !== null ? valor - custo : null;
    const leitura = leituras.get(par) ?? null;

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
      tendencia: leituraDasReguas(leitura),
      resumo: resumirLeitura(leitura?.features, aberta),
      comMeta,
      // Carteira que ainda não rodou não está armada nem desarmada: só espera.
      armada: comMeta && (conta || iniciada) ? (conta?.armado ?? true) : null,
      explicacao,
    };
  });
}

/**
 * O que saiu do caixa para abrir a posição. A compra usa o caixa inteiro
 * (`live/execucao.py`): quantidade = caixa × (1 − taxa) / preço, então o
 * caixa gasto é quantidade × preço / (1 − taxa). Exato, sem a linha da compra.
 */
export function custoDaEntrada(precoEntrada: number, quantidade: number) {
  return (precoEntrada * quantidade) / (1 - TAXA);
}

export type PontoCurva = { t: string; equity: number };

/** Patrimônio total por ciclo, somando as contas de cada par. */
function curvaPorCiclos(ciclos: CicloDaCurva[], pares: string[]): PontoCurva[] {
  const ultimo = new Map<string, number>(pares.map((p) => [p, CAPITAL_POR_CONTA]));
  const saida: PontoCurva[] = [];
  for (const c of ciclos) {
    if (c.preco == null || !c.conta) continue;
    ultimo.set(c.symbol, (c.conta.caixa ?? 0) + (c.conta.quantidade ?? 0) * c.preco);
    let total = 0;
    for (const p of pares) total += ultimo.get(p) ?? CAPITAL_POR_CONTA;
    saida.push({ t: c.created_at, equity: total });
  }
  return saida;
}

/** Um ponto por dia UTC: o último de cada dia. */
function umPorDia(pontos: PontoCurva[]): PontoCurva[] {
  const porDia = new Map<string, PontoCurva>();
  for (const p of pontos) porDia.set(new Date(p.t).toISOString().slice(0, 10), p);
  return [...porDia.values()];
}

const DIA_MS = 86_400_000;

/** Fim do dia UTC `aaaa-mm-dd`, como instante ISO (início do dia seguinte). */
export function fimDoDia(dia: string) {
  return new Date(Date.parse(`${dia.slice(0, 10)}T00:00:00Z`) + DIA_MS).toISOString();
}

/** Patrimônio total por dia, somando as contas; conta sem linha repete a anterior. */
export function curvaDiaria(linhas: LinhaDiaria[], pares: string[]): PontoCurva[] {
  const porDia = new Map<string, Map<string, number>>();
  for (const l of linhas) {
    const dia = l.dia_utc.slice(0, 10);
    if (!porDia.has(dia)) porDia.set(dia, new Map());
    porDia.get(dia)!.set(l.asset, Number(l.patrimonio));
  }
  const ultimo = new Map<string, number>(pares.map((p) => [p, CAPITAL_POR_CONTA]));
  return [...porDia.keys()].sort().map((dia) => {
    for (const [par, v] of porDia.get(dia)!) ultimo.set(par, v);
    let total = 0;
    for (const p of pares) total += ultimo.get(p) ?? CAPITAL_POR_CONTA;
    // o fechamento do dia UTC, que é o instante que a linha avalia
    return { t: `${dia}T23:59:59Z`, equity: total };
  });
}

/**
 * A curva da página da carteira: o histórico por ciclos até a primeira
 * linha diária (reduzido a um ponto por dia, para a escala do tempo não
 * mudar no meio do gráfico) e, dali em diante, `patrimonio_diario`.
 * Com menos de dois dias gravados, a curva por ciclos inteira.
 */
export function montarCurva(ciclos: CicloDaCurva[], diario: LinhaDiaria[], pares: string[]): PontoCurva[] {
  const diaria = curvaDiaria(diario, pares);
  if (diaria.length < 2) return curvaPorCiclos(ciclos, pares);
  const primeiroDia = diaria[0].t.slice(0, 10);
  const antes = umPorDia(curvaPorCiclos(ciclos, pares)).filter(
    (p) => new Date(p.t).toISOString().slice(0, 10) < primeiroDia
  );
  return [...antes, ...diaria];
}

/** Último preço gravado por par — o recurso quando não há preço ao vivo. */
export function precosDasLeituras(leituras: Map<string, UltimaLeitura | null>): Map<string, number> {
  const m = new Map<string, number>();
  for (const [par, u] of leituras) if (typeof u?.preco === "number") m.set(par, u.preco);
  return m;
}

export const usd = (v: number, casas = 2) =>
  v.toLocaleString("pt-BR", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: casas,
    maximumFractionDigits: casas,
  });

/** Preço de uma moeda: mais casas quando ela vale pouco (DOGE, ADA). */
export const preco = (v: number) => usd(v, v < 1 ? 4 : v < 100 ? 3 : 2);

export const sinal = (v: number) => (v > 0 ? "+" : v < 0 ? "−" : "");
