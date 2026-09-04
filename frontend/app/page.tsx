import Link from "next/link";
import type { Metadata } from "next";
import { Diagnostico } from "@/app/Diagnostico";
import { getSupabaseClient, variaveisFaltando } from "@/lib/supabase";

export const metadata: Metadata = {
  title: "Pipeline — V.A.L Finance",
  description: "Último ciclo de coleta e indicadores de cada ativo.",
};

export const revalidate = 0;

/**
 * Status honesto do pipeline.
 *
 * A versão anterior desta página dizia "pipeline ativo / passo 1 — esqueleto"
 * de forma estática, independente do que estivesse acontecendo. Isso é pior
 * que não mostrar nada: um painel que afirma estar vivo sem checar nada
 * ensina a não confiar nele. Aqui todo estado vem do dado — se o cron parou
 * de rodar, a página diz que parou.
 */

type Features = {
  rsi_14: number | null;
  atr_14: number | null;
  ema_20: number | null;
  ema_50: number | null;
  ema_200: number | null;
  volume_relativo: number | null;
  retorno_24h: number | null;
  macd: { histograma: number | null } | null;
};

type Decision = {
  id: string;
  created_at: string;
  symbol: string;
  market_snapshot: {
    preco_atual: number;
    candles_em_andamento_descartados?: number;
  } | null;
  features: Features | null;
  llm_output: unknown | null;
  risk_result: unknown | null;
  status: string;
};

async function carregar() {
  const supabase = getSupabaseClient();
  const [ultimas, total] = await Promise.all([
    supabase
      .from("decisions")
      .select("*")
      .order("created_at", { ascending: false })
      .limit(30),
    supabase.from("decisions").select("id", { count: "exact", head: true }),
  ]);
  if (ultimas.error) throw new Error(`Supabase: ${ultimas.error.message}`);
  return {
    decisions: (ultimas.data ?? []) as Decision[],
    total: total.count ?? 0,
  };
}

const n = (v: number | null | undefined, casas = 2) =>
  v === null || v === undefined ? "—" : v.toFixed(casas);

const preco = (v: number | null | undefined) =>
  v === null || v === undefined
    ? "—"
    : v.toLocaleString("pt-BR", { maximumFractionDigits: 2 });

/** Tendência lida das três médias — o dado que o cérebro recebe. */
function tendencia(f: Features | null) {
  if (!f?.ema_20 || !f.ema_50 || !f.ema_200) return { txt: "—", cor: "text-[#3d5c48]" };
  if (f.ema_20 > f.ema_50 && f.ema_50 > f.ema_200)
    return { txt: "alta alinhada", cor: "text-[#3ddc84]" };
  if (f.ema_20 < f.ema_50 && f.ema_50 < f.ema_200)
    return { txt: "baixa alinhada", cor: "text-[#e07a5f]" };
  return { txt: "sem alinhamento", cor: "text-[#eda100]" };
}

function corDoRsi(rsi: number | null | undefined) {
  if (rsi === null || rsi === undefined) return "text-[#3d5c48]";
  if (rsi < 30) return "text-[#3ddc84]";
  if (rsi > 70) return "text-[#e07a5f]";
  return "text-[#d8f5df]";
}

const PASSOS = [
  { n: 1, nome: "Repositório e esqueleto", estado: "ok" },
  { n: 2, nome: "Feature Engine", estado: "ok" },
  { n: 3, nome: "Motor de backtest", estado: "ok" },
  { n: 4, nome: "Baseline", estado: "ok" },
  { n: 5, nome: "Cérebro (LLM)", estado: "ok" },
  { n: 6, nome: "Risk Engine", estado: "ok" },
  { n: 7, nome: "Backtest da híbrida", estado: "ok" },
  { n: 8, nome: "Paper trading (testnet)", estado: "pendente" },
  { n: 9, nome: "Dashboard completo", estado: "pendente" },
] as const;

export default async function Home() {
  // Sem as variáveis, consultar o Supabase estoura com uma mensagem
  // que não ajuda. Melhor dizer o que falta.
  const faltando = variaveisFaltando();
  if (faltando.length) return <Diagnostico faltando={faltando} />;

  let dados;
  try {
    dados = await carregar();
  } catch (e) {
    // O servidor sabe o que falhou. Mostrar é mais útil que esconder atrás
    // de um digest que ninguém consegue traduzir.
    return <Diagnostico erro={e instanceof Error ? e.message : String(e)} />;
  }
  const { decisions, total } = dados;

  // Um ciclo por símbolo: a lista vem ordenada por data, então o primeiro
  // de cada símbolo é o mais recente.
  const porSimbolo = new Map<string, Decision>();
  for (const d of decisions) if (!porSimbolo.has(d.symbol)) porSimbolo.set(d.symbol, d);
  const recentes = [...porSimbolo.values()];

  const ultimo = decisions[0];
  const minutos = ultimo
    ? Math.round((Date.now() - new Date(ultimo.created_at).getTime()) / 60000)
    : null;

  // O cron roda de hora em hora, aos 5 min (render.yaml). Passar de 75 min
  // significa que uma execução foi pulada — dizer "ativo" nesse caso seria
  // mentira útil para ninguém. O limiar acompanha o cron: se a cadência lá
  // mudar, este número muda junto, senão a página passa a mentir sozinha.
  const vivo = minutos !== null && minutos < 75;
  const jaOperou = decisions.some((d) => d.risk_result !== null);

  return (
    <main className="min-h-screen bg-[#0a0e0c] text-[#d8f5df] font-mono px-6 py-10">
      <div className="max-w-4xl mx-auto">
        <div className="flex items-center gap-2 mb-1">
          <span
            className={`h-2 w-2 rounded-full ${
              vivo ? "bg-[#3ddc84] animate-pulse" : ultimo ? "bg-[#eda100]" : "bg-[#3d5c48]"
            }`}
          />
          <span className="text-xs uppercase tracking-widest text-[#5c9d78]">
            {vivo
              ? "pipeline ativo"
              : ultimo
                ? `sem gravar há ${minutos} min`
                : "nunca rodou"}
          </span>
        </div>

        <h1 className="text-xl mb-2 text-[#eafff0]">
          V.A.L Finance <span className="text-[#5c9d78]">/ coleta e indicadores</span>
        </h1>

        <p className="text-xs text-[#5c9d78] mb-6 max-w-2xl leading-relaxed">
          O cron busca candles, descarta o que ainda não fechou, calcula os indicadores e grava.
          <span className="text-[#eda100]">
            {" "}
            Ainda não decide nada e nunca enviou ordem
          </span>{" "}
          — nem em testnet. A decisão automática entra no passo 8.
        </p>

        <nav className="mb-8">
          <Link
            href="/backtests"
            className="text-xs text-[#5c9d78] hover:text-[#3ddc84] transition-colors"
          >
            ver backtests e cota →
          </Link>
          <span className="text-[#1c2b21] mx-3">·</span>
          <Link
            href="/regimes"
            className="text-xs text-[#5c9d78] hover:text-[#3ddc84] transition-colors"
          >
            estudo de regimes →
          </Link>
        </nav>

        {/* ---------- roteiro ---------- */}
        <section className="mb-8">
          <div className="text-[10px] uppercase tracking-widest text-[#3d5c48] mb-2">roteiro</div>
          <div className="flex flex-wrap gap-1.5">
            {PASSOS.map((p) => (
              <span
                key={p.n}
                title={p.nome}
                className={`text-[10px] px-2 py-1 rounded border ${
                  p.estado === "ok"
                    ? "border-[#1e3d2a] text-[#3ddc84] bg-[#0e1a13]"
                    : p.estado === "parcial"
                      ? "border-[#3d3115] text-[#eda100] bg-[#181307]"
                      : "border-[#1c2b21] text-[#3d5c48]"
                }`}
              >
                {p.n}. {p.nome}
                {p.estado === "parcial" && " ⚠"}
              </span>
            ))}
          </div>
        </section>

        {/* ---------- último ciclo por símbolo ---------- */}
        {recentes.length === 0 ? (
          <p className="text-[#5c9d78] text-sm">
            Nenhum registro ainda. Rode{" "}
            <span className="text-[#8fd4a8]">python backend/main.py</span> pra gerar o primeiro.
          </p>
        ) : (
          <>
            <div className="text-[10px] uppercase tracking-widest text-[#3d5c48] mb-2">
              último ciclo por ativo
            </div>
            <div className="flex flex-col gap-px bg-[#1c2b21] border border-[#1c2b21] rounded overflow-hidden">
              {recentes.map((d) => {
                const f = d.features;
                const t = tendencia(f);
                const ret = f?.retorno_24h;
                return (
                  <article key={d.id} className="bg-[#0d1310] px-4 py-4">
                    <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 mb-3">
                      <span className="text-sm text-[#eafff0]">{d.symbol}</span>
                      <span className="text-sm tabular-nums text-[#d8f5df]">
                        {preco(d.market_snapshot?.preco_atual)}
                      </span>
                      {ret !== null && ret !== undefined && (
                        <span
                          className={`text-xs tabular-nums ${
                            ret >= 0 ? "text-[#3ddc84]" : "text-[#e07a5f]"
                          }`}
                        >
                          {ret > 0 ? "+" : ""}
                          {n(ret)}% 24h
                        </span>
                      )}
                      <span className="ml-auto text-[10px] text-[#3d5c48]">
                        {new Date(d.created_at).toLocaleString("pt-BR")}
                      </span>
                    </div>

                    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-x-4 gap-y-3">
                      <div className="flex flex-col gap-0.5">
                        <span
                          className="text-[10px] uppercase tracking-widest text-[#3d5c48]"
                          title="Força das altas contra as quedas, 0 a 100. Abaixo de 30 é sobrevendido, acima de 70 sobrecomprado."
                        >
                          rsi 14
                        </span>
                        <span className={`text-sm tabular-nums ${corDoRsi(f?.rsi_14)}`}>
                          {n(f?.rsi_14, 1)}
                        </span>
                      </div>
                      <div className="flex flex-col gap-0.5">
                        <span
                          className="text-[10px] uppercase tracking-widest text-[#3d5c48]"
                          title="Quanto o ativo costuma andar por candle, em unidade de preço. É daqui que sai o stop-loss."
                        >
                          atr 14
                        </span>
                        <span className="text-sm tabular-nums text-[#d8f5df]">
                          {preco(f?.atr_14)}
                        </span>
                      </div>
                      <div className="flex flex-col gap-0.5">
                        <span
                          className="text-[10px] uppercase tracking-widest text-[#3d5c48]"
                          title="Ordem das médias de 20, 50 e 200 períodos."
                        >
                          tendência
                        </span>
                        <span className={`text-sm ${t.cor}`}>{t.txt}</span>
                      </div>
                      <div className="flex flex-col gap-0.5">
                        <span
                          className="text-[10px] uppercase tracking-widest text-[#3d5c48]"
                          title="Volume do candle atual contra a média dos 20 anteriores. 1,0 é normal."
                        >
                          volume rel.
                        </span>
                        <span className="text-sm tabular-nums text-[#d8f5df]">
                          {n(f?.volume_relativo)}×
                        </span>
                      </div>
                      <div className="flex flex-col gap-0.5">
                        <span className="text-[10px] uppercase tracking-widest text-[#3d5c48]">
                          status
                        </span>
                        <span className="text-sm text-[#5c9d78]">{d.status}</span>
                      </div>
                    </div>

                    {d.market_snapshot?.candles_em_andamento_descartados ? (
                      <div className="mt-3 pt-3 border-t border-[#141f18] text-[10px] text-[#3d5c48]">
                        {d.market_snapshot.candles_em_andamento_descartados} candle em andamento
                        descartado antes de calcular — o volume parcial dele distorceria o volume
                        relativo.
                      </div>
                    ) : null}
                  </article>
                );
              })}
            </div>
          </>
        )}

        <div className="mt-6 flex flex-wrap gap-x-6 gap-y-1 text-[10px] text-[#3d5c48]">
          <span>
            <span className="tabular-nums text-[#5c9d78]">{total}</span> ciclos gravados
          </span>
          <span>
            ordens enviadas:{" "}
            <span className={jaOperou ? "text-[#5c9d78]" : "text-[#eda100]"}>
              {jaOperou ? "sim" : "nenhuma"}
            </span>
          </span>
          <span>cron de hora em hora · cérebro a cada 6h (quando ligado)</span>
        </div>
      </div>
    </main>
  );
}
