import type { Metadata } from "next";
import { Diagnostico } from "@/app/Diagnostico";
import { getSupabaseClient, variaveisFaltando } from "@/lib/supabase";
import { Cabecalho } from "@/app/_componentes/Cabecalho";
import { CotaDiaria } from "./CotaDiaria";
import { calcularUso, type RunDeCota } from "@/lib/cota";
import { dataCurta } from "@/lib/tempo";

export const metadata: Metadata = {
  title: "Evidência",
  description:
    "Backtests da estratégia híbrida contra as baselines, ativo por ativo, com métricas auditadas.",
};

export const revalidate = 0;

/*
 * A evidência.
 *
 * Só leitura, de propósito. A página usa a chave `anon`, pública no
 * navegador — qualquer coisa que ela conseguisse escrever, qualquer visitante
 * conseguiria escrever. Por isso não há formulário de chave aqui: trocar de
 * modelo continua sendo variável de ambiente no backend. A página mostra o
 * que ESTÁ configurado, nunca o valor.
 */

type Metricas = {
  retorno_total_pct: number | null;
  cagr_pct: number | null;
  sharpe: number | null;
  max_drawdown_pct: number | null;
  taxa_acerto_pct: number | null;
  numero_trades: number | null;
  saldo_final: number | null;
};

type Params = {
  modelo?: string;
  provedor?: string;
  chamadas_reais?: number;
  auditoria?: {
    overrides_de_risco?: number;
    bloqueios_de_risco?: number;
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
};

const ROTULO: Record<string, { nome: string; ia: boolean }> = {
  buy_and_hold: { nome: "Comprar e segurar", ia: false },
  ema_crossover: { nome: "Cruzamento de médias", ia: false },
  hibrida_llm_risk: { nome: "IA + risco", ia: true },
  hibrida_llm_risk_baixo: { nome: "IA + risco · 0,25%", ia: true },
};

async function carregar() {
  const sb = getSupabaseClient();
  const { data, error } = await sb
    .from("backtest_runs")
    .select("id, created_at, strategy_name, symbol, period_start, period_end, params, metrics")
    .order("created_at", { ascending: true });
  if (error) throw new Error(`Supabase: ${error.message}`);
  return (data ?? []) as Run[];
}

const pct = (v: number | null | undefined) =>
  v == null ? "—" : `${v >= 0 ? "+" : ""}${v.toFixed(2)}%`;
const dec = (v: number | null | undefined, c = 2) => (v == null ? "—" : v.toFixed(c));

export default async function Evidencia() {
  const faltando = variaveisFaltando();
  if (faltando.length) return <Diagnostico faltando={faltando} />;

  let runs: Run[];
  try {
    runs = await carregar();
  } catch (e) {
    return <Diagnostico erro={e instanceof Error ? e.message : String(e)} />;
  }

  // Um grupo por ativo+janela. Comparar estratégias de janelas diferentes
  // seria comparar mercados diferentes.
  const grupos = new Map<string, Run[]>();
  for (const r of runs) {
    const chave = `${r.symbol}|${r.period_start}|${r.period_end}`;
    grupos.set(chave, [...(grupos.get(chave) ?? []), r]);
  }
  const janelas = [...grupos.entries()].sort(
    (a, b) => (b[1][0]?.period_start ?? "").localeCompare(a[1][0]?.period_start ?? "")
  );

  const modelo = [...runs].reverse().find((r) => r.params?.modelo)?.params?.modelo ?? null;

  // Vantagem média da híbrida contra o comprar-e-segurar, nas janelas onde
  // as duas rodaram.
  const comparaveis = janelas.filter(([, lista]) => {
    const temIa = lista.some((r) => ROTULO[r.strategy_name]?.ia);
    const temBase = lista.some((r) => r.strategy_name === "buy_and_hold");
    return temIa && temBase;
  });
  const ganhos = comparaveis.map(([, lista]) => {
    const ia = lista.find((r) => r.strategy_name === "hibrida_llm_risk");
    const bh = lista.find((r) => r.strategy_name === "buy_and_hold");
    return {
      retorno: (ia?.metrics?.retorno_total_pct ?? 0) - (bh?.metrics?.retorno_total_pct ?? 0),
      dd: (ia?.metrics?.max_drawdown_pct ?? 0) - (bh?.metrics?.max_drawdown_pct ?? 0),
    };
  });
  const venceuRetorno = ganhos.filter((g) => g.retorno > 0).length;
  const venceuDd = ganhos.filter((g) => g.dd > 0).length;
  const mediaDd = ganhos.length
    ? ganhos.reduce((s, g) => s + g.dd, 0) / ganhos.length
    : 0;

  return (
    <>
      <Cabecalho atual="/backtests" />

      <main className="mx-auto max-w-[1240px] px-5 pb-28 sm:px-8">
        <section className="grid grid-cols-1 gap-10 pt-14 pb-14 lg:grid-cols-12 lg:pt-20">
          <div className="lg:col-span-6">
            <h1 className="text-[clamp(2rem,4.5vw,2.9rem)] font-medium leading-[1.05] tracking-[-0.035em]">
              O que a estratégia já provou
            </h1>
            <p className="mt-5 max-w-[52ch] text-[14.5px] leading-relaxed text-vale-tinta-2">
              Cada janela abaixo compara a híbrida contra as duas baselines no mesmo
              período e com o mesmo capital. Métricas auditadas a partir das operações
              cruas, não do que o motor reportou.
            </p>
          </div>

          {ganhos.length > 0 && (
            <div className="grid grid-cols-3 gap-px self-start border border-vale-fio bg-vale-fio lg:col-span-6">
              <Placar
                rotulo="drawdown"
                valor={`${venceuDd}/${ganhos.length}`}
                nota={`${mediaDd >= 0 ? "+" : ""}${mediaDd.toFixed(1)} pts em média`}
                bom={venceuDd > ganhos.length / 2}
              />
              <Placar
                rotulo="retorno"
                valor={`${venceuRetorno}/${ganhos.length}`}
                nota="janelas vencidas"
                bom={venceuRetorno > ganhos.length / 2}
              />
              <Placar rotulo="modelo" valor={modelo ? "ativo" : "—"} nota={modelo ?? "não registrado"} />
            </div>
          )}
        </section>

        <CotaDiaria uso={calcularUso(runs as RunDeCota[])} modelo={modelo} />

        <div className="mt-16 space-y-14">
          {janelas.map(([chave, lista]) => {
            const [symbol, inicio, fim] = chave.split("|");
            const dias = Math.round(
              (new Date(fim).getTime() - new Date(inicio).getTime()) / 86400000
            );
            const ordenadas = [...lista].sort(
              (a, b) =>
                (b.metrics?.retorno_total_pct ?? -Infinity) -
                (a.metrics?.retorno_total_pct ?? -Infinity)
            );
            const lider = ordenadas[0]?.id;

            return (
              <section key={chave}>
                <div className="mb-4 flex items-baseline justify-between gap-4 border-b border-vale-fio pb-3">
                  <h2 className="num text-[17px] tracking-[-0.02em] text-vale-tinta">
                    {symbol}
                  </h2>
                  <span className="num text-[11.5px] text-vale-tinta-3">
                    {dataCurta(inicio)} ·{" "}
                    {dias} dias
                  </span>
                </div>

                <div className="overflow-x-auto">
                  <table className="w-full min-w-[720px] border-collapse">
                    <thead>
                      <tr className="text-[10.5px] uppercase tracking-[0.1em] text-vale-tinta-3">
                        <th className="pb-2.5 text-left font-normal">estratégia</th>
                        <th className="pb-2.5 text-right font-normal">retorno</th>
                        <th className="pb-2.5 text-right font-normal">sharpe</th>
                        <th className="pb-2.5 text-right font-normal">drawdown</th>
                        <th className="pb-2.5 text-right font-normal">acerto</th>
                        <th className="pb-2.5 text-right font-normal">trades</th>
                        <th className="pb-2.5 text-right font-normal">saldo</th>
                      </tr>
                    </thead>
                    <tbody>
                      {ordenadas.map((r) => {
                        const m = r.metrics;
                        const meta = ROTULO[r.strategy_name] ?? {
                          nome: r.strategy_name,
                          ia: true,
                        };
                        const ret = m?.retorno_total_pct ?? null;
                        return (
                          <tr
                            key={r.id}
                            className={`border-t border-vale-fio ${
                              r.id === lider ? "bg-vale-superficie" : ""
                            }`}
                          >
                            <td className="py-3 pr-4">
                              <span className="flex items-center gap-2.5">
                                <span
                                  className={`h-3.5 w-[2px] rounded-full ${
                                    meta.ia ? "bg-vale-alta" : "bg-vale-fio-forte"
                                  }`}
                                  aria-hidden="true"
                                />
                                <span className="text-[13.5px] text-vale-tinta">
                                  {meta.nome}
                                </span>
                              </span>
                            </td>
                            <td
                              className={`num py-3 text-right text-[13.5px] ${
                                ret == null
                                  ? "text-vale-tinta-3"
                                  : ret >= 0
                                    ? "text-vale-alta"
                                    : "text-vale-baixa"
                              }`}
                            >
                              {pct(ret)}
                            </td>
                            <td className="num py-3 text-right text-[13.5px] text-vale-tinta-2">
                              {dec(m?.sharpe)}
                            </td>
                            <td className="num py-3 text-right text-[13.5px] text-vale-tinta-2">
                              {pct(m?.max_drawdown_pct)}
                            </td>
                            <td className="num py-3 text-right text-[13.5px] text-vale-tinta-2">
                              {m?.taxa_acerto_pct == null
                                ? "—"
                                : `${m.taxa_acerto_pct.toFixed(0)}%`}
                            </td>
                            <td className="num py-3 text-right text-[13.5px] text-vale-tinta-2">
                              {m?.numero_trades ?? "—"}
                            </td>
                            <td className="num py-3 text-right text-[13.5px] text-vale-tinta-2">
                              {m?.saldo_final == null
                                ? "—"
                                : m.saldo_final.toLocaleString("pt-BR", {
                                    maximumFractionDigits: 0,
                                  })}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </section>
            );
          })}
        </div>

        <p className="mt-16 max-w-[70ch] border-l-2 border-vale-fio-forte pl-4 text-[13px] leading-relaxed text-vale-tinta-3">
          Quatro dos cinco ativos caíram nesta janela, e a hipótese é que o sistema
          protege na queda. A amostra favorece o sistema, então o resultado é
          consistente com a hipótese sem ser prova dela.
        </p>
      </main>
    </>
  );
}

function Placar({
  rotulo,
  valor,
  nota,
  bom,
}: {
  rotulo: string;
  valor: string;
  nota: string;
  bom?: boolean;
}) {
  return (
    <div className="bg-vale-superficie px-5 py-4">
      <div className="text-[10.5px] uppercase tracking-[0.1em] text-vale-tinta-3">
        {rotulo}
      </div>
      <div
        className={`num mt-1.5 text-[22px] tracking-[-0.03em] ${
          bom === undefined ? "text-vale-tinta" : bom ? "text-vale-alta" : "text-vale-tinta"
        }`}
      >
        {valor}
      </div>
      <div className="num mt-0.5 truncate text-[11px] text-vale-tinta-3" title={nota}>
        {nota}
      </div>
    </div>
  );
}
