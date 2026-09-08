import Link from "next/link";
import type { Metadata } from "next";
import { ArrowUpRight } from "@phosphor-icons/react/dist/ssr";
import { Diagnostico } from "@/app/Diagnostico";
import { getSupabaseClient, variaveisFaltando } from "@/lib/supabase";
import { Cabecalho } from "@/app/_componentes/Cabecalho";
import { CurvaDeCapital, type Ponto } from "@/app/_componentes/CurvaDeCapital";
import { FluxoDeDecisoes } from "@/app/_componentes/FluxoDeDecisoes";
import { diaMes } from "@/lib/tempo";

export const metadata: Metadata = {
  title: "Operação",
  description:
    "Estado ao vivo do forward test: capital, posições e as decisões que o sistema tomou.",
};

export const revalidate = 0;

/*
 * Superfície de operação.
 *
 * A página existe para responder uma pergunta em um olhar: o sistema está
 * vivo e quanto ele está fazendo. Tudo aqui vem do banco — não há um único
 * número escrito à mão. Se o cron parar, a página diz que parou.
 */

const CAPITAL_POR_CONTA = 10_000;

type Decisao = {
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
  order_result: { lado: string; preco: number; resultado_pct?: number | null } | null;
};

type Posicao = {
  asset: string;
  quantity: number;
  caixa: number | null;
  preco_entrada: number | null;
  stop_loss: number | null;
  take_profit: number | null;
};

async function carregar() {
  const sb = getSupabaseClient();
  const [ciclos, carteira, coleta] = await Promise.all([
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

  return {
    ciclos: (ciclos.data ?? []) as Decisao[],
    carteira: (carteira.data ?? []) as Posicao[],
    ultimaColeta: coleta.data?.[0]?.created_at ?? null,
  };
}

/** Capital total por instante, somando as contas de cada par. */
function montarCurva(ciclos: Decisao[], pares: string[]): Ponto[] {
  const ultimo = new Map<string, number>(pares.map((p) => [p, CAPITAL_POR_CONTA]));
  const saida: Ponto[] = [];

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

const moeda = (v: number) =>
  v.toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export default async function Operacao() {
  const faltando = variaveisFaltando();
  if (faltando.length) return <Diagnostico faltando={faltando} />;

  let dados;
  try {
    dados = await carregar();
  } catch (e) {
    return <Diagnostico erro={e instanceof Error ? e.message : String(e)} />;
  }
  const { ciclos, carteira, ultimaColeta } = dados;

  const pares = [...new Set(ciclos.map((c) => c.symbol))].sort();
  const curva = montarCurva(ciclos, pares);
  const inicial = pares.length * CAPITAL_POR_CONTA;

  // O capital atual sai da carteira gravada, não do último ponto da curva:
  // a carteira é a verdade, a curva é a leitura dela ao longo do tempo.
  const precoDe = new Map<string, number>();
  for (const c of ciclos) if (c.market_snapshot) precoDe.set(c.symbol, c.market_snapshot.preco_atual);

  const atual = pares.reduce((soma, par) => {
    const p = carteira.find((x) => x.asset === par);
    if (!p) return soma + CAPITAL_POR_CONTA;
    return soma + (p.caixa ?? 0) + (p.quantity ?? 0) * (precoDe.get(par) ?? 0);
  }, 0);

  const delta = atual - inicial;
  const deltaPct = (atual / inicial - 1) * 100;
  const positivo = delta >= 0;

  const ultimoCiclo = ciclos[ciclos.length - 1];
  const minutosDesde = ultimoCiclo
    ? Math.round((Date.now() - new Date(ultimoCiclo.created_at).getTime()) / 60000)
    : null;
  // O agendamento do GitHub é melhor-esforço (medido: 3,3 h de intervalo
  // médio). Um limiar de 1 h chamaria de "parado" um sistema saudável.
  const vivo = minutosDesde !== null && minutosDesde < 420;

  const operacoes = ciclos.filter((c) => c.order_result);
  const fechadas = operacoes.filter((c) => c.order_result?.resultado_pct != null);
  const inicio = ciclos[0]?.created_at;

  return (
    <>
      <Cabecalho atual="/" />

      <main className="mx-auto max-w-[1240px] px-5 pb-28 sm:px-8">
        {/* ---------------------------------------------------- estado ---- */}
        <section className="grid grid-cols-1 gap-10 pt-14 pb-16 lg:grid-cols-12 lg:gap-14 lg:pt-20">
          <div className="lg:col-span-5">
            <div className="flex items-center gap-2 text-[12px] text-vale-tinta-3">
              <Pulso vivo={vivo} />
              <span className="num">
                {vivo ? "operando" : `sem ciclo há ${minutosDesde} min`}
              </span>
              <span className="text-vale-fio-forte">/</span>
              <span className="num">{ciclos.length} ciclos</span>
              {inicio && (
                <>
                  <span className="text-vale-fio-forte">/</span>
                  <span className="num">
                    desde{" "}
                    {diaMes(inicio)}
                  </span>
                </>
              )}
            </div>

            <h1 className="num mt-5 text-[clamp(2.75rem,7vw,4.25rem)] leading-[0.95] tracking-[-0.045em] text-vale-tinta">
              {moeda(atual)}
            </h1>

            <div className="mt-3 flex items-baseline gap-3">
              <span
                className={`num text-[19px] ${positivo ? "text-vale-alta" : "text-vale-baixa"}`}
              >
                {positivo ? "+" : ""}
                {moeda(delta)}
              </span>
              <span
                className={`num text-[14px] ${positivo ? "text-vale-alta" : "text-vale-baixa"}`}
              >
                {positivo ? "+" : ""}
                {deltaPct.toFixed(2)}%
              </span>
              <span className="text-[13px] text-vale-tinta-3">
                de {moeda(inicial)}
              </span>
            </div>

            <p className="mt-6 max-w-[46ch] text-[14.5px] leading-relaxed text-vale-tinta-2">
              Execução simulada ao preço real de mercado. O cérebro propõe, o motor
              de risco decide, e nenhuma ordem sai para corretora.
            </p>
          </div>

          <div className="lg:col-span-7">
            <CurvaDeCapital pontos={curva} inicial={inicial} altura={230} />
          </div>
        </section>

        {/* ---------------------------------------------------- contas ---- */}
        <section className="grid grid-cols-1 gap-px border border-vale-fio bg-vale-fio sm:grid-cols-2">
          {pares.map((par) => (
            <Conta
              key={par}
              par={par}
              posicao={carteira.find((x) => x.asset === par)}
              preco={precoDe.get(par)}
            />
          ))}
        </section>

        <section className="mt-px grid grid-cols-2 gap-px border border-t-0 border-vale-fio bg-vale-fio lg:grid-cols-4">
          <Medida rotulo="operações" valor={String(operacoes.length)} nota={`${fechadas.length} fechada${fechadas.length === 1 ? "" : "s"}`} />
          <Medida
            rotulo="consultas ao cérebro"
            valor={String(ciclos.filter((c) => c.llm_output).length)}
            nota="cadência de 6 h"
          />
          <Medida
            rotulo="vetos do risco"
            valor={String(ciclos.filter((c) => c.risk_result?.aprovado === false).length)}
            nota="entradas barradas"
          />
          <Medida
            rotulo="coleta"
            valor={ultimaColeta ? `${Math.round((Date.now() - new Date(ultimaColeta).getTime()) / 60000)} min` : "—"}
            nota="desde a última gravação"
          />
        </section>

        {/* --------------------------------------------------- decisões ---- */}
        <section className="mt-20">
          <div className="mb-6 flex items-baseline justify-between gap-4">
            <h2 className="text-[19px] font-medium tracking-[-0.02em]">
              O que o sistema decidiu
            </h2>
            <span className="num text-[12px] text-vale-tinta-3">
              mais recentes primeiro
            </span>
          </div>
          <FluxoDeDecisoes ciclos={[...ciclos].reverse().slice(0, 40)} />
        </section>

        {/* ----------------------------------------------------- saídas ---- */}
        <section className="mt-20 grid grid-cols-1 gap-px border border-vale-fio bg-vale-fio sm:grid-cols-2">
          <Saida
            href="/backtests"
            titulo="Evidência"
            texto="Cinco ativos replicados. Drawdown melhor que comprar-e-segurar em 5 de 5."
          />
          <Saida
            href="/regimes"
            titulo="Regimes"
            texto="320 backtests em 64 janelas. Por que um seletor de regime não vale a pena."
          />
        </section>
      </main>
    </>
  );
}

/* -------------------------------------------------------------- peças ---- */

function Pulso({ vivo }: { vivo: boolean }) {
  return (
    <span className="relative flex h-1.5 w-1.5">
      {vivo && (
        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-vale-alta opacity-60" />
      )}
      <span
        className={`relative inline-flex h-1.5 w-1.5 rounded-full ${
          vivo ? "bg-vale-alta" : "bg-vale-tinta-3"
        }`}
      />
    </span>
  );
}

function Conta({
  par,
  posicao,
  preco,
}: {
  par: string;
  posicao?: Posicao;
  preco?: number;
}) {
  const posicionada = (posicao?.quantity ?? 0) > 0;
  const entrada = posicao?.preco_entrada ?? null;
  const stop = posicao?.stop_loss ?? null;
  const aberto = posicionada && entrada && preco ? (preco / entrada - 1) * 100 : null;

  return (
    <div className="bg-vale-superficie p-6">
      <div className="flex items-center justify-between">
        <span className="num text-[15px] tracking-[-0.01em] text-vale-tinta">{par}</span>
        <span
          className={`num rounded-sm px-2 py-0.5 text-[10.5px] uppercase tracking-[0.08em] ${
            posicionada
              ? "bg-vale-alta/10 text-vale-alta"
              : "bg-vale-elevado text-vale-tinta-3"
          }`}
        >
          {posicionada ? "posicionada" : "de fora"}
        </span>
      </div>

      <div className="num mt-5 text-[26px] tracking-[-0.03em] text-vale-tinta">
        {preco ? moeda(preco) : "—"}
      </div>

      {posicionada ? (
        <div className="mt-5 grid grid-cols-3 gap-4">
          <Campo rotulo="entrada" valor={entrada ? moeda(entrada) : "—"} />
          <Campo rotulo="stop" valor={stop ? moeda(stop) : "—"} destaque="baixa" />
          <Campo
            rotulo="aberto"
            valor={aberto != null ? `${aberto >= 0 ? "+" : ""}${aberto.toFixed(2)}%` : "—"}
            destaque={aberto != null && aberto >= 0 ? "alta" : "baixa"}
          />
        </div>
      ) : (
        <div className="mt-5 grid grid-cols-3 gap-4">
          <Campo
            rotulo="caixa"
            valor={posicao?.caixa != null ? moeda(posicao.caixa) : moeda(CAPITAL_POR_CONTA)}
          />
          <Campo rotulo="stop" valor="—" />
          <Campo rotulo="aberto" valor="—" />
        </div>
      )}
    </div>
  );
}

function Campo({
  rotulo,
  valor,
  destaque,
}: {
  rotulo: string;
  valor: string;
  destaque?: "alta" | "baixa";
}) {
  const cor =
    destaque === "alta"
      ? "text-vale-alta"
      : destaque === "baixa"
        ? "text-vale-baixa"
        : "text-vale-tinta-2";
  return (
    <div>
      <div className="text-[10.5px] uppercase tracking-[0.1em] text-vale-tinta-3">
        {rotulo}
      </div>
      <div className={`num mt-1 text-[13.5px] ${cor}`}>{valor}</div>
    </div>
  );
}

function Medida({
  rotulo,
  valor,
  nota,
}: {
  rotulo: string;
  valor: string;
  nota: string;
}) {
  return (
    <div className="bg-vale-superficie px-6 py-5">
      <div className="text-[10.5px] uppercase tracking-[0.1em] text-vale-tinta-3">
        {rotulo}
      </div>
      <div className="num mt-2 text-[22px] tracking-[-0.03em] text-vale-tinta">
        {valor}
      </div>
      <div className="mt-0.5 text-[11.5px] text-vale-tinta-3">{nota}</div>
    </div>
  );
}

function Saida({
  href,
  titulo,
  texto,
}: {
  href: string;
  titulo: string;
  texto: string;
}) {
  return (
    <Link
      href={href}
      className="group bg-vale-superficie p-7 transition-colors hover:bg-vale-elevado"
    >
      <div className="flex items-center justify-between">
        <span className="text-[17px] font-medium tracking-[-0.02em] text-vale-tinta">
          {titulo}
        </span>
        <ArrowUpRight
          size={17}
          weight="bold"
          className="text-vale-tinta-3 transition-transform duration-300 group-hover:-translate-y-0.5 group-hover:translate-x-0.5 group-hover:text-vale-tinta"
        />
      </div>
      <p className="mt-2 max-w-[42ch] text-[13.5px] leading-relaxed text-vale-tinta-2">
        {texto}
      </p>
    </Link>
  );
}
