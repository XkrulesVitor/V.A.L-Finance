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
 * - Referência: só segurar BTC e ETH, meio a meio, no mesmo período.
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

  // Patrimônio total (BTC + ETH) por estratégia e dia; preço de fechamento por moeda e dia.
  const porDia = new Map<string, Map<string, number>>(); // carteira -> dia -> total
  const partes = new Map<string, number>(); // carteira|dia -> quantas moedas somadas
  const preco = new Map<string, number>(); // par|dia -> fechamento
  for (const l of diario) {
    const dia = String(l.dia_utc).slice(0, 10);
    const m = porDia.get(l.carteira) ?? new Map<string, number>();
    m.set(dia, (m.get(dia) ?? 0) + Number(l.patrimonio));
    porDia.set(l.carteira, m);
    partes.set(`${l.carteira}|${dia}`, (partes.get(`${l.carteira}|${dia}`) ?? 0) + 1);
    preco.set(`${l.asset}|${dia}`, Number(l.preco_fechamento));
  }
  // Dia com uma moeda só não é um total completo: fica de fora.
  for (const [cart, m] of porDia) for (const dia of [...m.keys()]) if ((partes.get(`${cart}|${dia}`) ?? 0) < PARES.length) m.delete(dia);

  // Valor de agora, como na página inicial.
  const agora = new Map<string, number>();
  for (const c of catalogo) {
    let total = 0;
    for (const par of PARES) {
      const k = linhasDeConta.find((x) => x.carteira === c.id && x.asset === par);
      const p = precos.get(par);
      const qtd = k?.quantity ?? 0;
      total += (k?.caixa ?? CAPITAL_POR_CONTA) + (qtd > 0 && p ? qtd * p : 0);
    }
    agora.set(c.id, total);
  }

  const hoje = paraData(Date.now());
  const semanaAtual = segundaDe(hoje);
  const ativas = catalogo.filter((c) => c.ativa_desde);
  const primeiroDia = [...porDia.values()].flatMap((m) => [...m.keys()]).sort()[0] ?? hoje;
  const semanas: Semana[] = [];

  for (let seg = segundaDe(primeiroDia); seg <= semanaAtual; seg = paraData(ms(seg) + 7 * DIA)) {
    const dom = paraData(ms(seg) + 6 * DIA);
    const emAndamento = seg === semanaAtual;
    const linhas = ativas.map((c) => linhaDaSemana(c, seg, dom, emAndamento, porDia.get(c.id), agora.get(c.id)!, ops));
    if (linhas.every((l) => l.pct === null)) continue;
    semanas.push({ inicio: seg, fim: dom, emAndamento, linhas, referenciaPct: referencia(seg, dom, emAndamento, preco, precos) });
  }

  const desdeOInicio = ativas.map((c) => ({
    id: c.id,
    nome: c.nome,
    pct: (agora.get(c.id)! / inicial - 1) * 100,
    usd: agora.get(c.id)! - inicial,
  }));

  return { semanas: semanas.reverse(), desdeOInicio };
}

function linhaDaSemana(
  c: Carteira,
  seg: string,
  dom: string,
  emAndamento: boolean,
  dias: Map<string, number> | undefined,
  valorAgora: number,
  ops: { carteira: string; created_at: string }[]
): LinhaDaSemana {
  const todos = [...(dias?.keys() ?? [])].sort();
  const antes = todos.filter((d) => d < seg).at(-1);
  const dentro = todos.filter((d) => d >= seg && d <= dom).at(-1);
  const comecou = c.ativa_desde ? paraData(Date.parse(c.ativa_desde)) : null;

  const fim = emAndamento ? valorAgora : dentro !== undefined ? dias!.get(dentro)! : null;
  // Antes da semana, o último fechamento; se começou nela, o capital inicial.
  const comecouNaSemana = comecou !== null && comecou >= seg && comecou <= dom;
  const comecoDaSerie = todos[0] !== undefined && todos[0] >= seg && todos[0] <= dom;
  const inicio = antes !== undefined ? dias!.get(antes)! : comecouNaSemana || comecoDaSerie ? inicial : null;

  const fimMs = ms(dom) + DIA;
  const operacoes = ops.filter(
    (o) => o.carteira === c.id && Date.parse(o.created_at) >= ms(seg) && Date.parse(o.created_at) < fimMs
  ).length;

  // Sem dado na semana (ou antes dela) não há resultado. A data de D0 do
  // catálogo não entra aqui: a Tendência tem histórico desde 04/09, antes
  // da troca de regra de 22/09, e a semana dela conta pelo patrimônio.
  if (fim === null || inicio === null) {
    return { id: c.id, nome: c.nome, pct: null, usd: null, operacoes };
  }
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
    if (!p0 || !p1) return null;
    variacoes.push(p1 / p0 - 1);
  }
  return (variacoes.reduce((a, b) => a + b, 0) / variacoes.length) * 100;
}

const MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"];

/** "21 – 27 set" (datas puras, sem fuso: é o dia UTC do relatório). */
export function rotuloDaSemana(inicio: string, fim: string) {
  const [, m1, d1] = inicio.split("-").map(Number);
  const [, m2, d2] = fim.split("-").map(Number);
  return m1 === m2 ? `${d1} – ${d2} ${MESES[m2 - 1]}` : `${d1} ${MESES[m1 - 1]} – ${d2} ${MESES[m2 - 1]}`;
}
