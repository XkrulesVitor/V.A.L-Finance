import type { Metadata } from "next";
import bruto from "@/lib/regimes.json";
import { Cabecalho } from "@/app/_componentes/Cabecalho";
import { dataLonga } from "@/lib/tempo";

/*
 * Estudo de regimes — snapshot, não dado ao vivo.
 *
 * Os 320 backtests rodaram uma vez, offline, e o agregado vive em
 * `lib/regimes.json`. Não vai para o Supabase de propósito: 320 linhas em
 * `backtest_runs` criariam 64 grupos de período na página de evidência e
 * afogariam a comparação que aquela página existe para mostrar.
 *
 * Por ser snapshot, a data de geração aparece na tela. Estudo sem data
 * vira "verdade atemporal" e envelhece sem avisar.
 */

type Regime = "alta" | "lateral" | "baixa";
type PorRegime = Record<Regime, number> & { geral: number };
type Vantagem = PorRegime & { venceu: number; de: number };

type Estudo = {
  gerado_em: string;
  janelas: number;
  backtests: number;
  contagem_regime: Record<Regime, number>;
  estrategias: string[];
  por_regime: Record<string, PorRegime>;
  vantagem: Record<string, Vantagem>;
  melhor_por_regime: Record<Regime, string>;
  oraculo: { buy_and_hold: number; perfeito: number; teto: number };
  detector_real: {
    acertos: number; de: number; adaptativo: number;
    buy_and_hold: number; ganho: number;
  };
  transicoes: Record<Regime, Record<Regime, number>>;
};

const dados = bruto as Estudo;

export const metadata: Metadata = {
  title: "Regimes",
  description:
    "320 backtests em 64 janelas: o regime muda tudo, mas não dá para prever.",
};

const REGIMES: Regime[] = ["alta", "lateral", "baixa"];

const NOME: Record<string, string> = {
  buy_and_hold: "Comprar e segurar",
  ema_crossover: "Cruzamento de médias",
  rsi_reversao: "RSI reversão",
  macd_histograma: "MACD histograma",
  acima_da_ema200: "Acima da EMA 200",
};

const tom = (v: number) =>
  v > 3 ? "text-vale-alta" : v < -3 ? "text-vale-baixa" : "text-vale-tinta-2";

export default function Regimes() {
  const { por_regime, oraculo, detector_real, contagem_regime } = dados;
  const acerto = (detector_real.acertos / detector_real.de) * 100;
  const maior = REGIMES.reduce((a, b) =>
    contagem_regime[a] >= contagem_regime[b] ? a : b
  );
  const chuteBase = (contagem_regime[maior] / dados.janelas) * 100;

  return (
    <>
      <Cabecalho atual="/regimes" />

      <main className="mx-auto max-w-[1240px] px-5 pb-28 sm:px-8">
        <section className="grid grid-cols-1 gap-10 pt-14 pb-16 lg:grid-cols-12 lg:pt-20">
          <div className="lg:col-span-7">
            <h1 className="text-[clamp(2rem,4.5vw,2.9rem)] font-medium leading-[1.05] tracking-[-0.035em]">
              O regime muda tudo.
              <br />
              E não dá para prever.
            </h1>
            <p className="mt-5 max-w-[54ch] text-[14.5px] leading-relaxed text-vale-tinta-2">
              {dados.backtests} backtests em {dados.janelas} janelas de 91 dias, sem
              nenhuma chamada de API. A pergunta era se vale construir um seletor de
              regime. A resposta é não, e os dois números abaixo explicam por quê.
            </p>
          </div>
        </section>

        {/* ------------------------------------------- os dois números ---- */}
        <section className="grid grid-cols-1 gap-px border border-vale-fio bg-vale-fio lg:grid-cols-2">
          <div className="bg-vale-superficie p-7">
            <div className="text-[10.5px] uppercase tracking-[0.1em] text-vale-tinta-3">
              teto com regime perfeito
            </div>
            <div className="num mt-3 text-[38px] leading-none tracking-[-0.04em] text-vale-tinta">
              +{oraculo.teto.toFixed(2)}
              <span className="ml-1.5 text-[16px] text-vale-tinta-3">pts</span>
            </div>
            <p className="mt-4 max-w-[44ch] text-[13.5px] leading-relaxed text-vale-tinta-2">
              Mesmo <strong className="font-medium text-vale-tinta">sabendo o futuro</strong>,
              um seletor ganharia isso sobre o comprar-e-segurar. É o limite superior,
              inalcançável.
            </p>
            <div className="num mt-5 flex gap-6 border-t border-vale-fio pt-4 text-[12px] text-vale-tinta-3">
              <span>
                comprar e segurar{" "}
                <span className="text-vale-tinta-2">{oraculo.buy_and_hold.toFixed(2)}%</span>
              </span>
              <span>
                oráculo{" "}
                <span className="text-vale-tinta-2">{oraculo.perfeito.toFixed(2)}%</span>
              </span>
            </div>
          </div>

          <div className="bg-vale-superficie p-7">
            <div className="text-[10.5px] uppercase tracking-[0.1em] text-vale-tinta-3">
              ganho com detector honesto
            </div>
            <div className="num mt-3 text-[38px] leading-none tracking-[-0.04em] text-vale-baixa">
              {detector_real.ganho.toFixed(2)}
              <span className="ml-1.5 text-[16px] text-vale-tinta-3">pts</span>
            </div>
            <p className="mt-4 max-w-[44ch] text-[13.5px] leading-relaxed text-vale-tinta-2">
              Usando o regime da janela anterior, sem olhar o futuro:{" "}
              {acerto.toFixed(0)}% de acerto,{" "}
              <strong className="font-medium text-vale-tinta">
                pior que chutar sempre &ldquo;{maior}&rdquo;
              </strong>{" "}
              ({chuteBase.toFixed(0)}%).
            </p>
            <div className="num mt-5 flex gap-6 border-t border-vale-fio pt-4 text-[12px] text-vale-tinta-3">
              <span>
                adaptativo{" "}
                <span className="text-vale-baixa">{detector_real.adaptativo.toFixed(2)}%</span>
              </span>
              <span>
                acertou{" "}
                <span className="text-vale-tinta-2">
                  {detector_real.acertos}/{detector_real.de}
                </span>
              </span>
            </div>
          </div>
        </section>

        {/* ------------------------------------------------ por regime ---- */}
        <section className="mt-20">
          <div className="mb-4 flex items-baseline justify-between gap-4 border-b border-vale-fio pb-3">
            <h2 className="text-[19px] font-medium tracking-[-0.02em]">
              Retorno médio por regime
            </h2>
            <span className="num text-[11.5px] text-vale-tinta-3">
              {REGIMES.map((r) => `${r} ${contagem_regime[r]}`).join(" · ")}
            </span>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full min-w-[560px] border-collapse">
              <thead>
                <tr className="text-[10.5px] uppercase tracking-[0.1em] text-vale-tinta-3">
                  <th className="pb-2.5 text-left font-normal">estratégia</th>
                  {REGIMES.map((r) => (
                    <th key={r} className="pb-2.5 text-right font-normal">
                      {r}
                    </th>
                  ))}
                  <th className="pb-2.5 text-right font-normal">geral</th>
                </tr>
              </thead>
              <tbody>
                {dados.estrategias.map((e) => (
                  <tr key={e} className="border-t border-vale-fio">
                    <td className="py-3 pr-4 text-[13.5px] text-vale-tinta">
                      {NOME[e] ?? e}
                    </td>
                    {REGIMES.map((r) => (
                      <td
                        key={r}
                        className={`num py-3 text-right text-[13.5px] ${tom(por_regime[e]?.[r] ?? 0)}`}
                      >
                        {(por_regime[e]?.[r] ?? 0).toFixed(1)}%
                      </td>
                    ))}
                    <td
                      className={`num py-3 text-right text-[13.5px] ${tom(por_regime[e]?.geral ?? 0)}`}
                    >
                      {(por_regime[e]?.geral ?? 0).toFixed(1)}%
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <p className="mt-6 max-w-[70ch] border-l-2 border-vale-fio-forte pl-4 text-[13px] leading-relaxed text-vale-tinta-3">
            A premissa se confirma: o desempenho varia muito com o regime. O que não se
            confirma é a conclusão prática — o prêmio por acertar o regime é pequeno, e
            acertar não é possível. Foi isso que matou a ideia do seletor adaptativo
            antes de custar uma linha de código.
          </p>
        </section>

        <p className="num mt-16 text-[11px] text-vale-tinta-3">
          snapshot gerado em{" "}
          {dataLonga(dados.gerado_em)}
        </p>
      </main>
    </>
  );
}
