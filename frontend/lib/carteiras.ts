/**
 * As seis carteiras lado a lado: catálogo, Conselho de IAs e a visão da
 * página inicial.
 *
 * O catálogo vem da tabela `carteiras`, que o backend sincroniza a partir
 * de `backend/live/carteiras.py` a cada execução. Nomes e descrições não
 * são repetidos aqui: o que o site mostra é o que o robô usa.
 *
 * ## Consultas enxutas (PRE_REGISTRO_6_CARTEIRAS.md, seção 11.3)
 *
 * A página inicial NÃO lê `decisions` inteira: com 12 contas e ~6 ciclos
 * por dia, isso chegaria a dezenas de MB por visita no fim do primeiro ano.
 * Ela lê `portfolio` (no máximo 12 linhas), `patrimonio_diario` dos
 * últimos 90 dias, o último veredito do Conselho e a última decisão de
 * cada carteira × par (`limit 1`).
 */

import { getSupabaseClient } from "@/lib/supabase";
import {
  CAPITAL_POR_CONTA,
  COLUNAS_DA_CONTA,
  PARES,
  type Conta,
  type LinhaDiaria,
  type PontoCurva,
  type UltimaLeitura,
  curvaDiaria,
  custoDaEntrada,
  paginar,
  precosAoVivo,
  ultimaLeitura,
} from "@/lib/carteira";
import { type Resumo, resumirLeitura } from "@/lib/rotulos";

type Cliente = ReturnType<typeof getSupabaseClient>;

export const IDS = ["T1", "T2", "T3", "G1", "G2", "G3"] as const;
export type IdCarteira = (typeof IDS)[number];
export const ehIdDeCarteira = (s: string): s is IdCarteira => (IDS as readonly string[]).includes(s);

/** Carteiras com meta de lucro (alvo fixo de 3×ATR) e rearme. */
export const COM_META = new Set<string>(["G1", "G3"]);
/** Carteiras que decidem pelo veredito do Conselho de IAs. */
export const COM_CONSELHO = new Set<string>(["T3", "G3"]);

export type Carteira = {
  id: string;
  nome: string;
  descricao_leiga: string;
  familia: string;
  ativa_desde: string | null;
  ativa: boolean;
  ordem: number;
};

export const FAMILIAS = [
  {
    id: "tendencia",
    titulo: "Seguem tendência",
    texto: "Compram quando a alta aparece e seguram enquanto ela durar.",
    aviso: null,
  },
  {
    id: "stop_gain",
    titulo: "Stop gain",
    texto: "Vendem no lucro, sem esperar a alta acabar.",
    aviso: "Vender no lucro sobe a taxa de acerto mesmo sem ganhar mais dinheiro.",
  },
] as const;

export const ROTULO_DA_FAMILIA: Record<string, string> = {
  tendencia: "segue tendência",
  stop_gain: "stop gain",
};

/**
 * Histórias que não começam no D0 da carteira. A T1 começou em 04/09 com a
 * estratégia híbrida (o LLM decidia) e trocou para a regra de tendência em
 * 22/09 sem zerar as contas: o resultado dela desde o início inclui as duas.
 */
export const NOTA_DO_HISTORICO: Record<string, string> = {
  T1: "inclui 04–21/09 com a estratégia anterior",
};

/**
 * A primeira leitura de resultado é 3 meses depois do D0 (seção 13.4). Até
 * lá, a tela diz que não há leitura — a diferença entre carteiras é quase
 * toda sorte.
 */
export function primeiraLeitura(ativaDesde: string): Date {
  const d = new Date(ativaDesde);
  d.setUTCMonth(d.getUTCMonth() + 3);
  return d;
}

export async function lerCatalogo(sb: Cliente): Promise<Carteira[]> {
  const { data, error } = await sb
    .from("carteiras")
    .select("id, nome, descricao_leiga, familia, ativa_desde, ativa, ordem")
    .order("ordem", { ascending: true });
  if (error) throw new Error(`Supabase: ${error.message}`);
  const linhas = (data ?? []) as Carteira[];
  // A tabela é preenchida pelo backend a cada ciclo. Se ainda estiver vazia
  // (ou faltar alguma linha), a página não pode sumir com carteiras que já
  // operam: completa com os ids conhecidos, sem nome nem D0.
  const faltam = IDS.filter((id) => !linhas.some((l) => l.id === id)).map(
    (id, i): Carteira => ({
      id,
      nome: id,
      descricao_leiga: "",
      familia: id.startsWith("T") ? "tendencia" : "stop_gain",
      ativa_desde: null,
      ativa: false,
      ordem: 100 + i,
    })
  );
  return [...linhas, ...faltam];
}

/* ------------------------------------------------------------- Conselho */

export type VotoDaIA = {
  id: string;
  vaga: string;
  trend_call: string | null;
  resumo_pt: string | null;
  modelo: string | null;
};

export type Veredito = {
  id: string;
  dia_utc: string;
  simbolo: string;
  veredito: string;
  soma: number | null;
  validos: number;
  votos: Record<string, string | null>;
  congelado_em: string;
  /** Os votos válidos daquele dia, com a frase de cada IA. */
  detalhes: VotoDaIA[];
};

/**
 * O último veredito congelado de cada ativo, com os votos válidos do mesmo
 * dia. É o mesmo para T3 e G3 — uma linha de `painel_veredito`, dois usos.
 * Falhar aqui não derruba a página: sem ele, o cartão só diz que não há
 * veredito.
 */
export async function lerConselho(sb: Cliente): Promise<Map<string, Veredito>> {
  const saida = new Map<string, Veredito>();
  try {
    const { data, error } = await sb
      .from("painel_veredito")
      .select("id, dia_utc, simbolo, veredito, soma, validos, votos, votos_ids, congelado_em")
      .order("dia_utc", { ascending: false })
      .limit(PARES.length * 3);
    if (error || !data) return saida;

    type Linha = Omit<Veredito, "detalhes"> & { votos_ids: Record<string, string | null> | null };
    const ultimos: Linha[] = [];
    for (const v of data as Linha[]) {
      if (!ultimos.some((u) => u.simbolo === v.simbolo)) ultimos.push(v);
    }

    const ids = ultimos.flatMap((v) => Object.values(v.votos_ids ?? {}).filter((x): x is string => Boolean(x)));
    let votos: (VotoDaIA & { dia_utc: string; simbolo: string })[] = [];
    if (ids.length) {
      const r = await sb
        .from("painel_votos")
        .select("id, vaga, dia_utc, simbolo, trend_call, resumo_pt, modelo:modelo_efetivo")
        .in("id", ids)
        .eq("json_valido", true);
      if (!r.error) votos = (r.data ?? []) as typeof votos;
    }

    for (const v of ultimos) {
      const { votos_ids, ...resto } = v;
      const meus = new Set(Object.values(votos_ids ?? {}));
      saida.set(v.simbolo, {
        ...resto,
        detalhes: votos.filter((x) => meus.has(x.id) && x.dia_utc === v.dia_utc && x.simbolo === v.simbolo),
      });
    }
  } catch {
    // sem Conselho: o cartão diz que ainda não há veredito
  }
  return saida;
}

/* ------------------------------------------------------------- visão geral */

export type AtivoNoCartao = {
  par: string;
  comprada: boolean;
  valor: number;
  emAbertoPct: number | null;
  meta: number | null;
  metaPct: number | null;
  armada: boolean | null;
  leitura: Resumo | null;
};

export type CartaoDeCarteira = {
  carteira: Carteira;
  patrimonio: number;
  inicial: number;
  operou: boolean;
  ativos: AtivoNoCartao[];
  curva: PontoCurva[];
};

/**
 * Uma carteira no cartão da página inicial. Conta sem linha em `portfolio`
 * é conta que ainda não operou: US$ 10.000 em caixa.
 */
function montarCartao(
  carteira: Carteira,
  contas: Conta[],
  precos: Map<string, number>,
  leituras: Map<string, UltimaLeitura | null>,
  diario: LinhaDoDiario[]
): CartaoDeCarteira {
  const minhas = contas.filter((c) => c.carteira === carteira.id);
  const comMeta = COM_META.has(carteira.id);

  const ativos = PARES.map((par): AtivoNoCartao => {
    const conta = minhas.find((c) => c.asset === par);
    const qtd = conta?.quantity ?? 0;
    const caixa = conta?.caixa ?? CAPITAL_POR_CONTA;
    const preco = precos.get(par) ?? conta?.preco_entrada ?? null;
    const comprada = qtd > 0;
    const valorPosicao = comprada && preco !== null ? qtd * preco : 0;
    const custo = comprada && conta?.preco_entrada ? custoDaEntrada(conta.preco_entrada, qtd) : null;
    return {
      par,
      comprada,
      valor: caixa + valorPosicao,
      emAbertoPct: custo && comprada && preco !== null ? (valorPosicao / custo - 1) * 100 : null,
      meta: comMeta && comprada ? (conta?.take_profit ?? null) : null,
      metaPct:
        comMeta && comprada
          ? (conta?.alvo_pct ??
            (conta?.take_profit && conta.preco_entrada ? (conta.take_profit / conta.preco_entrada - 1) * 100 : null))
          : null,
      armada: comMeta ? (conta?.armado ?? true) : null,
      leitura: resumirLeitura(leituras.get(`${carteira.id}:${par}`)?.features, comprada),
    };
  });

  const patrimonio = ativos.reduce((s, a) => s + a.valor, 0);
  const curva = curvaDiaria(
    diario.filter((d) => d.carteira === carteira.id),
    PARES
  );
  // O último ponto é o valor de agora (o mesmo número ao lado da curva);
  // sem isso, a curva terminava no fechamento de ontem e podia ter outra cor.
  if (curva.length) curva.push({ t: new Date().toISOString(), equity: patrimonio });
  return {
    carteira,
    patrimonio,
    inicial: PARES.length * CAPITAL_POR_CONTA,
    operou: minhas.length > 0,
    ativos,
    curva,
  };
}

type LinhaDoDiario = LinhaDiaria & { carteira: string };

const DIAS_NA_MINICURVA = 90;

export async function carregarVisao() {
  const sb = getSupabaseClient();
  const desde = new Date(Date.now() - DIAS_NA_MINICURVA * 86_400_000).toISOString().slice(0, 10);

  const [catalogo, contas, diario, conselho, aoVivo] = await Promise.all([
    lerCatalogo(sb),
    sb.from("portfolio").select(COLUNAS_DA_CONTA),
    // A minicurva é enfeite útil, não dado essencial: sem ela o cartão segue.
    paginar<LinhaDoDiario>((de, ate) =>
      sb
        .from("patrimonio_diario")
        .select("carteira, asset, dia_utc, patrimonio")
        .gte("dia_utc", desde)
        .order("dia_utc", { ascending: true })
        .order("carteira", { ascending: true })
        .order("asset", { ascending: true })
        .range(de, ate)
    ).catch(() => [] as LinhaDoDiario[]),
    lerConselho(sb),
    precosAoVivo(PARES),
  ]);
  if (contas.error) throw new Error(`Supabase: ${contas.error.message}`);
  const linhas = (contas.data ?? []) as Conta[];

  // A última decisão só de quem já rodou: carteira sem D0 não tem nenhuma.
  const comHistorico = catalogo.filter((c) => c.ativa_desde || linhas.some((k) => k.carteira === c.id));
  const pares = await Promise.all(
    comHistorico.flatMap((c) =>
      PARES.map(async (par) => [`${c.id}:${par}`, await ultimaLeitura(sb, c.id, par)] as const)
    )
  );
  const leituras = new Map<string, UltimaLeitura | null>(pares);

  // Sem preço ao vivo, o do último ciclo de qualquer carteira.
  const precos = new Map(aoVivo);
  for (const par of PARES) {
    if (precos.has(par)) continue;
    const recente = [...leituras.entries()]
      .filter(([k, u]) => k.endsWith(`:${par}`) && typeof u?.preco === "number")
      .map(([, u]) => u!)
      .sort((a, b) => b.created_at.localeCompare(a.created_at))[0];
    if (recente?.preco != null) precos.set(par, recente.preco);
  }

  return {
    cartoes: catalogo.map((c) => montarCartao(c, linhas, precos, leituras, diario)),
    conselho,
    precos,
    aoVivo: PARES.every((p) => aoVivo.has(p)),
  };
}
