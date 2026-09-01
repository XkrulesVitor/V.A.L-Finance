import Link from "next/link";
import { getSupabaseClient } from "@/lib/supabase";
import { calcularUso, type RunDeCota } from "@/lib/cota";
import { CotaDiaria } from "./CotaDiaria";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Backtests — ia-trading",
  description: "Rodadas gravadas, agrupadas por período, e o consumo da cota diária do LLM.",
};

export const revalidate = 0;

/**
 * Painel de leitura do passo 7.
 *
 * Só leitura, de propósito. A página usa a chave `anon`, que é pública no
 * navegador — qualquer coisa que ela conseguisse escrever, qualquer visitante
 * conseguiria escrever, e qualquer coisa que ela lesse seria legível por
 * qualquer um. Por isso aqui não há formulário de chave de API: trocar de
 * modelo ou conectar corretora continua sendo variável de ambiente no
 * backend. O painel mostra o que ESTÁ configurado, nunca o valor.
 */

type Metricas = {
  retorno_total_pct: number | null;
  cagr_pct: number | null;
  sharpe: number | null;
  max_drawdown_pct: number | null;
  taxa_acerto_pct: number | null;
  numero_trades: number | null;
  numero_operacoes: number | null;
  taxas_pagas: number | null;
  saldo_inicial: number | null;
  saldo_final: number | null;
};

type Params = {
  capital_inicial?: number;
  taxa_por_operacao?: number;
  modelo?: string;
  cadencia_horas?: number;
  risco_por_operacao?: number;
  exposicao_maxima_pct?: number;
  candles?: number;
  chamadas_reais?: number;
  acertos_de_cache?: number;
  provedor?: string;
  multiplicadores_por_horizonte?: Record<string, { stop: number; take: number }>;
  auditoria?: {
    consultas_ao_cerebro?: number;
    overrides_de_risco?: number;
    bloqueios_de_risco?: number;
    direcoes_do_llm?: Record<string, number>;
  };
};

type Run = {
  id: string;
  created_at: string;
  strategy_name: string;
  symbol: string;
  period_start: string;
  period_end: string;
  params: Params | null;
  metrics: Metricas | null;
  notes: string | null;
};

type Decision = { created_at: string; symbol: string; status: string };

async function carregar() {
  const supabase = getSupabaseClient();
  const [runs, decisions] = await Promise.all([
    supabase
      .from("backtest_runs")
      .select("*")
      .order("period_start", { ascending: true })
      .order("created_at", { ascending: true }),
    supabase
      .from("decisions")
      .select("created_at, symbol, status")
      .order("created_at", { ascending: false })
      .limit(1),
  ]);
  if (runs.error) console.error(runs.error);
  return {
    runs: (runs.data ?? []) as Run[],
    ultimaDecisao: (decisions.data?.[0] ?? null) as Decision | null,
  };
}

const dia = (iso: string) =>
  new Date(iso).toLocaleDateString("pt-BR", { day: "2-digit", month: "short", year: "2-digit" });

const num = (v: number | null | undefined, casas = 2, sufixo = "") =>
  v === null || v === undefined ? "—" : `${v.toFixed(casas)}${sufixo}`;

const dinheiro = (v: number | null | undefined) =>
  v === null || v === undefined
    ? "—"
    : v.toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

/** Rótulo humano — o nome técnico da estratégia não diz nada sozinho. */
function rotular(nome: string) {
  const mapa: Record<string, { nome: string; tipo: "baseline" | "ia" }> = {
    buy_and_hold: { nome: "Comprar e segurar", tipo: "baseline" },
    ema_crossover: { nome: "Cruzamento de médias", tipo: "baseline" },
    hibrida_llm_risk: { nome: "IA + risco · 1%", tipo: "ia" },
    hibrida_llm_risk_baixo: { nome: "IA + risco · 0,25%", tipo: "ia" },
  };
  return mapa[nome] ?? { nome, tipo: "ia" as const };
}

function Metrica({ rotulo, valor, dica }: { rotulo: string; valor: string; dica?: string }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-[10px] uppercase tracking-widest text-[#3d5c48]" title={dica}>
        {rotulo}
      </span>
      <span className="text-sm tabular-nums text-[#d8f5df]">{valor}</span>
    </div>
  );
}

export default async function Backtests() {
  const { runs, ultimaDecisao } = await carregar();

  // Agrupa por período: comparar rodadas de janelas diferentes é comparar
  // perguntas diferentes, então elas nunca aparecem na mesma tabela.
  const grupos = new Map<string, Run[]>();
  for (const r of runs) {
    const chave = `${r.symbol}|${r.period_start}|${r.period_end}`;
    grupos.set(chave, [...(grupos.get(chave) ?? []), r]);
  }
  const periodos = [...grupos.entries()].sort(
    (a, b) => grupos.get(b[0])!.length - grupos.get(a[0])!.length
  );

  // O modelo em uso vem do dado real da última rodada, não de config —
  // é o que de fato produziu os números abaixo.
  const ultimoModelo = [...runs].reverse().find((r) => r.params?.modelo)?.params?.modelo ?? null;

  return (
    <main className="min-h-screen bg-[#0a0e0c] text-[#d8f5df] font-mono px-6 py-10">
      <div className="max-w-5xl mx-auto">
        <nav className="flex items-center gap-4 text-xs mb-8">
          <Link href="/" className="text-[#5c9d78] hover:text-[#3ddc84] transition-colors">
            ← pipeline
          </Link>
          <span className="text-[#1c2b21]">/</span>
          <span className="text-[#3ddc84]">backtests</span>
          <span className="text-[#1c2b21]">/</span>
          <Link href="/regimes" className="text-[#5c9d78] hover:text-[#3ddc84] transition-colors">
            regimes
          </Link>
        </nav>

        <h1 className="text-xl mb-1 text-[#eafff0]">
          Backtests <span className="text-[#5c9d78]">/ passo 7</span>
        </h1>
        <p className="text-xs text-[#5c9d78] mb-8 max-w-xl leading-relaxed">
          Cada rodada gravada em <span className="text-[#8fd4a8]">backtest_runs</span>. Rodadas de
          períodos diferentes ficam em tabelas separadas — comparar janelas diferentes é comparar
          perguntas diferentes.
        </p>

        <CotaDiaria uso={calcularUso(runs as RunDeCota[])} modelo={ultimoModelo} />

        {/* ---------- o que está conectado ---------- */}
        <section className="grid gap-px bg-[#1c2b21] border border-[#1c2b21] rounded overflow-hidden sm:grid-cols-3 mb-10">
          <div className="bg-[#0d1310] px-4 py-3">
            <div className="text-[10px] uppercase tracking-widest text-[#3d5c48] mb-1">cérebro</div>
            <div className="text-sm text-[#d8f5df]">{ultimoModelo ?? "—"}</div>
            <div className="text-[10px] text-[#3d5c48] mt-1">modelo da última rodada</div>
          </div>
          <div className="bg-[#0d1310] px-4 py-3">
            <div className="text-[10px] uppercase tracking-widest text-[#3d5c48] mb-1">
              dados de mercado
            </div>
            <div className="text-sm text-[#d8f5df]">Binance · público</div>
            <div className="text-[10px] text-[#3d5c48] mt-1">histórico sem chave</div>
          </div>
          <div className="bg-[#0d1310] px-4 py-3">
            <div className="text-[10px] uppercase tracking-widest text-[#3d5c48] mb-1">
              execução de ordens
            </div>
            <div className="text-sm text-[#d8f5df]">
              {ultimaDecisao ? "Binance testnet" : "—"}
              <span className="ml-2 text-[10px] text-[#c98500]">nenhuma ordem enviada</span>
            </div>
            <div className="text-[10px] text-[#3d5c48] mt-1">
              {ultimaDecisao
                ? `último ciclo ${new Date(ultimaDecisao.created_at).toLocaleString("pt-BR")}`
                : "cron ainda não rodou"}
            </div>
          </div>
        </section>

        <p className="text-[11px] text-[#3d5c48] leading-relaxed mb-10 max-w-2xl border-l-2 border-[#1c2b21] pl-3">
          Trocar de modelo ou conectar corretora continua sendo variável de ambiente no backend
          (<span className="text-[#5c9d78]">LLM_PROVEDOR</span>,{" "}
          <span className="text-[#5c9d78]">CLAUDE_MODELO</span>,{" "}
          <span className="text-[#5c9d78]">BINANCE_API_KEY</span>). Esta página é só leitura de
          propósito: ela usa a chave pública do navegador, então um formulário de chave aqui deixaria
          o segredo visível para qualquer visitante. O painel de configuração de verdade é o passo 9.
        </p>

        {/* ---------- as rodadas ---------- */}
        {periodos.length === 0 ? (
          <p className="text-[#5c9d78] text-sm">
            Nenhuma rodada gravada ainda. Rode{" "}
            <span className="text-[#8fd4a8]">python backend/backtest/run_baseline.py</span>.
          </p>
        ) : (
          <div className="flex flex-col gap-10">
            {periodos.map(([chave, lista]) => {
              const [symbol, inicio, fim] = chave.split("|");
              const dias = Math.round(
                (new Date(fim).getTime() - new Date(inicio).getTime()) / 86400000
              );
              const ordenadas = [...lista].sort(
                (a, b) => (b.metrics?.retorno_total_pct ?? -999) - (a.metrics?.retorno_total_pct ?? -999)
              );
              const melhor = ordenadas[0]?.id;

              return (
                <section key={chave}>
                  <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 mb-3">
                    <h2 className="text-sm text-[#eafff0]">{symbol}</h2>
                    <span className="text-xs text-[#5c9d78]">
                      {dia(inicio)} → {dia(fim)}
                    </span>
                    <span className="text-[10px] text-[#3d5c48]">
                      {dias} dias · {lista[0]?.params?.candles ?? "—"} candles · taxa{" "}
                      {((lista[0]?.params?.taxa_por_operacao ?? 0) * 100).toFixed(2)}%
                    </span>
                  </div>

                  <div className="flex flex-col gap-px bg-[#1c2b21] border border-[#1c2b21] rounded overflow-hidden">
                    {ordenadas.map((r) => {
                      const m = r.metrics;
                      const { nome, tipo } = rotular(r.strategy_name);
                      const ret = m?.retorno_total_pct ?? null;
                      return (
                        <article key={r.id} className="bg-[#0d1310] px-4 py-4">
                          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 mb-3">
                            <span className="text-sm text-[#d8f5df]">{nome}</span>
                            <span
                              className={`text-[9px] uppercase tracking-widest px-1.5 py-0.5 rounded border ${
                                tipo === "ia"
                                  ? "border-[#2a4a5c] text-[#6fa8c9]"
                                  : "border-[#1c2b21] text-[#3d5c48]"
                              }`}
                            >
                              {tipo === "ia" ? "com IA" : "baseline"}
                            </span>
                            {r.id === melhor && (
                              <span className="text-[9px] uppercase tracking-widest px-1.5 py-0.5 rounded border border-[#2d5c3f] text-[#3ddc84]">
                                melhor
                              </span>
                            )}
                            <span
                              className={`ml-auto text-base tabular-nums ${
                                ret !== null && ret >= 0 ? "text-[#3ddc84]" : "text-[#e07a5f]"
                              }`}
                            >
                              {ret === null ? "—" : `${ret > 0 ? "+" : ""}${ret.toFixed(2)}%`}
                            </span>
                          </div>

                          <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-7 gap-x-4 gap-y-3">
                            <Metrica
                              rotulo="sharpe"
                              valor={num(m?.sharpe)}
                              dica="Retorno dividido pela oscilação. Negativo = balançou e ainda perdeu."
                            />
                            <Metrica
                              rotulo="drawdown"
                              valor={num(m?.max_drawdown_pct, 2, "%")}
                              dica="Maior queda do topo até o fundo — o pior momento."
                            />
                            <Metrica
                              rotulo="acerto"
                              valor={num(m?.taxa_acerto_pct, 1, "%")}
                              dica="% de operações no lucro. Nunca leia sozinha."
                            />
                            <Metrica rotulo="trades" valor={`${m?.numero_trades ?? "—"}`} />
                            <Metrica rotulo="taxas" valor={dinheiro(m?.taxas_pagas)} />
                            <Metrica rotulo="saldo final" valor={dinheiro(m?.saldo_final)} />
                            <Metrica rotulo="cagr" valor={num(m?.cagr_pct, 2, "%")} />
                          </div>

                          {(r.params?.auditoria || r.params?.risco_por_operacao) && (
                            <div className="mt-3 pt-3 border-t border-[#141f18] flex flex-wrap gap-x-5 gap-y-1 text-[10px] text-[#3d5c48]">
                              {r.params?.risco_por_operacao !== undefined && (
                                <span>
                                  risco{" "}
                                  <span className="text-[#5c9d78]">
                                    {(r.params.risco_por_operacao * 100).toFixed(2)}%
                                  </span>
                                </span>
                              )}
                              {r.params?.cadencia_horas !== undefined && (
                                <span>
                                  cadência{" "}
                                  <span className="text-[#5c9d78]">{r.params.cadencia_horas}h</span>
                                </span>
                              )}
                              {r.params?.auditoria?.consultas_ao_cerebro !== undefined && (
                                <span>
                                  consultas{" "}
                                  <span className="text-[#5c9d78]">
                                    {r.params.auditoria.consultas_ao_cerebro}
                                  </span>
                                </span>
                              )}
                              {r.params?.auditoria?.bloqueios_de_risco !== undefined && (
                                <span>
                                  bloqueios{" "}
                                  <span className="text-[#5c9d78]">
                                    {r.params.auditoria.bloqueios_de_risco}
                                  </span>
                                </span>
                              )}
                              {r.params?.auditoria?.overrides_de_risco !== undefined && (
                                <span>
                                  overrides{" "}
                                  <span className="text-[#5c9d78]">
                                    {r.params.auditoria.overrides_de_risco}
                                  </span>
                                </span>
                              )}
                              {r.params?.modelo && (
                                <span className="text-[#3d5c48]">{r.params.modelo}</span>
                              )}
                            </div>
                          )}
                        </article>
                      );
                    })}
                  </div>
                </section>
              );
            })}
          </div>
        )}

        <p className="text-[10px] text-[#2d4636] mt-12 leading-relaxed max-w-2xl">
          Todas as métricas são reconstruídas de forma independente a partir da lista bruta de
          operações antes de serem gravadas. Passe o mouse nos rótulos para ver o que cada uma mede.
        </p>
      </div>
    </main>
  );
}
