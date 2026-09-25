/**
 * Relatório semanal: quanto cada estratégia rendeu em cada semana.
 *
 * A semana vai de segunda a domingo, em dias UTC (os mesmos dias do
 * `patrimonio_diario`, gravado no fechamento de cada dia UTC).
 *
 * - Fim da semana: o patrimônio do último dia fechado dela; na semana em
 *   andamento, o valor de agora (conta × preço ao vivo).
 * - Começo: o patrimônio do último dia antes da semana. Se a estratégia
 *   começou dentro da semana, o capital inicial (US$ 10.000 por moeda).
 * - Referência: só segurar as moedas que a carteira tem, em partes iguais.
 *
 * Tudo sai do banco; nenhum número é digitado à mão.
 */

import { getSupabaseClient } from "@/lib/supabase";
import { CAPITAL_POR_CONTA, COLUNAS_DA_CONTA, PARES, type Conta, paginar, precosAoVivo } from "@/lib/carteira";
import { type Carteira, lerCatalogo } from "@/lib/carteiras";

type LinhaDoDiario = { carteira: string; asset: string; dia_utc: string; patrimonio: number; preco_fechamento: number };

export type LinhaDaSemana = {
  id: string;
  nome: string;
  pct: number | null;
  usd: number | null;
  operacoes: number;
};

export type Semana = {
  inicio: string; // segunda (AAAA-MM-DD)
  fim: string; // domingo
  emAndamento: boolean;
  linhas: LinhaDaSemana[];
  referenciaPct: number | null;
};

const DIA = 86_400_000;
const inicial = PARES.length * CAPITAL_POR_CONTA;

const paraData = (ms: number) => new Date(ms).toISOString().slice(0, 10);
const ms = (dia: string) => Date.parse(`${dia}T00:00:00Z`);

/** Segunda-feira (UTC) da semana do dia. */
function segundaDe(dia: string): string {
  const d = new Date(ms(dia));
  const recuo = (d.getUTCDay() + 6) % 7; // segunda = 0
  return paraData(d.getTime() - recuo * DIA);
}

export async function carregarRelatorios() {
  const sb = getSupabaseClient();
  const [catalogo, diario, contas, ops, precos] = await Promise.all([
    lerCatalogo(sb),
    paginar<LinhaDoDiario>((de, ate) =>
      sb
        .from("patrimonio_diario")
        .select("carteira, asset, dia_utc, patrimonio, preco_fechamento")
        .order("dia_utc", { ascending: true })
        .order("carteira", { ascending: true })
        .order("asset", { ascending: true })
        .range(de, ate)
    ),
    sb.from("portfolio").select(COLUNAS_DA_CONTA),
    paginar<{ carteira: string; created_at: string }>((de, ate) =>
      sb
        .from("decisions")
        .select("carteira, created_at")
        .eq("status", "executed")
        .order("created_at", { ascending: true })
        .range(de, ate)
    ),
    precosAoVivo(PARES),
  ]);
  if (contas.error) throw new Error(`Supabase: ${contas.error.message}`);
  const linhasDeConta = (contas.data ?? []) as Conta[];

  // Patrimônio de cada conta (estratégia × moeda) por dia, e o fechamento
  // de cada moeda por dia. Por moeda, e não o total: as moedas entraram em
  // datas diferentes (BTC e ETH em 04/09; XRP, LINK, ADA e DOGE em 25/09), e
  // uma semana só conta as moedas que já existiam nela.
  const series = new Map<string, Map<string, Map<string, number>>>(); // carteira -> par -> dia -> valor
  const preco = new Map<string, number>(); // par|dia -> fechamento
  for (const l of diario) {
    const dia = String(l.dia_utc).slice(0, 10);
    const daCarteira = series.get(l.carteira) ?? new Map<string, Map<string, number>>();
    const doPar = daCarteira.get(l.asset) ?? new Map<string, number>();
    doPar.set(dia, Number(l.patrimonio));
    daCarteira.set(l.asset, doPar);
    series.set(l.carteira, daCarteira);
    preco.set(`${l.asset}|${dia}`, Number(l.preco_fechamento));
  }

  // Valor de agora de cada conta, como na página inicial.
  const agora = new Map<string, number>(); // carteira|par -> valor
  const totalAgora = new Map<string, number>();
  for (const c of catalogo) {
    let total = 0;
    for (const par of PARES) {
      const k = linhasDeConta.find((x) => x.carteira === c.id && x.asset === par);
      const p = precos.get(par);
      const qtd = k?.quantity ?? 0;
      const v = (k?.caixa ?? CAPITAL_POR_CONTA) + (qtd > 0 && p ? qtd * p : 0);
      agora.set(`${c.id}|${par}`, v);
      total += v;
    }
    totalAgora.set(c.id, total);
  }

  const hoje = paraData(Date.now());
  const semanaAtual = segundaDe(hoje);
  const ativas = catalogo.filter((c) => c.ativa_desde);
  const primeiroDia =
    [...series.values()].flatMap((m) => [...m.values()].flatMap((d) => [...d.keys()])).sort()[0] ?? hoje;
  const semanas: Semana[] = [];

  for (let seg = segundaDe(primeiroDia); seg <= semanaAtual; seg = paraData(ms(seg) + 7 * DIA)) {
    const dom = paraData(ms(seg) + 6 * DIA);
    const emAndamento = seg === semanaAtual;
    const linhas = ativas.map((c) => linhaDaSemana(c, seg, dom, emAndamento, series.get(c.id), agora, ops));
    if (linhas.every((l) => l.pct === null)) continue;
    semanas.push({ inicio: seg, fim: dom, emAndamento, linhas, referenciaPct: referencia(seg, dom, emAndamento, preco, precos) });
  }

  const desdeOInicio = ativas.map((c) => ({
    id: c.id,
    nome: c.nome,
    pct: (totalAgora.get(c.id)! / inicial - 1) * 100,
    usd: totalAgora.get(c.id)! - inicial,
  }));

  return { semanas: semanas.reverse(), desdeOInicio };
}

function linhaDaSemana(
  c: Carteira,
  seg: string,
  dom: string,
  emAndamento: boolean,
  seriesDaCarteira: Map<string, Map<string, number>> | undefined,
  agora: Map<string, number>,
  ops: { carteira: string; created_at: string }[]
): LinhaDaSemana {
  // Soma, moeda a moeda, o começo e o fim da semana:
  // - começo: o último fechamento antes da semana, ou US$ 10.000 se a moeda
  //   entrou na carteira dentro dela;
  // - fim: o último fechamento da semana, ou o valor de agora na semana em
  //   andamento.
  // Moeda sem nenhum dado na semana (ainda não existia) fica de fora.
  let inicio = 0;
  let fim = 0;
  let moedas = 0;
  for (const par of PARES) {
    const serie = seriesDaCarteira?.get(par);
    const dias = [...(serie?.keys() ?? [])].sort();
    const antes = dias.filter((d) => d < seg).at(-1);
    const dentro = dias.filter((d) => d >= seg && d <= dom).at(-1);
    const f = emAndamento ? agora.get(`${c.id}|${par}`) : dentro !== undefined ? serie!.get(dentro) : undefined;
    if (f === undefined) continue;
    inicio += antes !== undefined ? serie!.get(antes)! : CAPITAL_POR_CONTA;
    fim += f;
    moedas += 1;
  }

  const fimMs = ms(dom) + DIA;
  const operacoes = ops.filter(
    (o) => o.carteira === c.id && Date.parse(o.created_at) >= ms(seg) && Date.parse(o.created_at) < fimMs
  ).length;

  if (moedas === 0) return { id: c.id, nome: c.nome, pct: null, usd: null, operacoes };
  return { id: c.id, nome: c.nome, pct: (fim / inicio - 1) * 100, usd: fim - inicio, operacoes };
}

function referencia(
  seg: string,
  dom: string,
  emAndamento: boolean,
  preco: Map<string, number>,
  aoVivo: Map<string, number>
): number | null {
  const variacoes: number[] = [];
  for (const par of PARES) {
    const dias = [...preco.keys()].filter((k) => k.startsWith(`${par}|`)).map((k) => k.slice(par.length + 1)).sort();
    const antes = dias.filter((d) => d < seg).at(-1) ?? dias.find((d) => d >= seg && d <= dom);
    const dentro = dias.filter((d) => d >= seg && d <= dom).at(-1);
    const p0 = antes !== undefined ? preco.get(`${par}|${antes}`) : undefined;
    const p1 = emAndamento ? (aoVivo.get(par) ?? (dentro ? preco.get(`${par}|${dentro}`) : undefined)) : dentro ? preco.get(`${par}|${dentro}`) : undefined;
    // Moeda que ainda não tinha preço registrado na semana fica de fora
    // da referência (partes iguais entre as que existiam).
    if (!p0 || !p1) continue;
    variacoes.push(p1 / p0 - 1);
  }
  if (!variacoes.length) return null;
  return (variacoes.reduce((a, b) => a + b, 0) / variacoes.length) * 100;
}

const MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"];

/** "21 – 27 set" (datas puras, sem fuso: é o dia UTC do relatório). */
export function rotuloDaSemana(inicio: string, fim: string) {
  const [, m1, d1] = inicio.split("-").map(Number);
  const [, m2, d2] = fim.split("-").map(Number);
  return m1 === m2 ? `${d1} – ${d2} ${MESES[m2 - 1]}` : `${d1} ${MESES[m1 - 1]} – ${d2} ${MESES[m2 - 1]}`;
}
