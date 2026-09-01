import Link from "next/link";
import type { Metadata } from "next";
import bruto from "@/lib/regimes.json";

/**
 * O JSON é um snapshot gerado offline, então o TypeScript o infere com as
 * chaves literais daquele arquivo. Tipar aqui deixa o acesso por índice
 * (estratégia × regime) checado de verdade, em vez de virar `any` silencioso.
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
  title: "Regimes de mercado — ia-trading",
  description: "320 backtests em 64 janelas: o desempenho muda por regime, mas o prêmio é pequeno.",
};

/**
 * Estudo de regimes — snapshot, não dado ao vivo.
 *
 * Os 320 backtests foram rodados uma vez, offline, e o resultado agregado
 * vive em `lib/regimes.json`. Não vai para o Supabase de propósito: 320
 * linhas em `backtest_runs` criariam 64 grupos de período na página de
 * backtests e afogariam a comparação que aquela página existe para mostrar.
 *
 * Por ser snapshot, a data de geração aparece na tela. Um estudo sem data
 * vira "verdade atemporal" e envelhece sem avisar.
 */

const REGIMES: Regime[] = ["alta", "lateral", "baixa"];

const ROTULOS: Record<string, string> = {
  buy_and_hold: "Comprar e segurar",
  ema_crossover: "Cruzamento de médias",
  rsi_reversao: "RSI reversão",
  macd_histograma: "MACD histograma",
  acima_da_ema200: "Acima da EMA 200",
};

function corRetorno(v: number) {
  if (v > 5) return "text-[#3ddc84]";
  if (v < -5) return "text-[#e07a5f]";
  return "text-[#d8f5df]";
}

function corVantagem(v: number) {
  if (v > 1) return "text-[#3ddc84]";
  if (v < -1) return "text-[#e07a5f]";
  return "text-[#eda100]";
}

export default function Regimes() {
  const { por_regime, vantagem, oraculo, detector_real, transicoes, contagem_regime } = dados;
  const acerto = (detector_real.acertos / detector_real.de) * 100;
  const maiorRegime = REGIMES.reduce((a, b) =>
    contagem_regime[a] >= contagem_regime[b] ? a : b
  );
  const chuteBase = (contagem_regime[maiorRegime] / dados.janelas) * 100;

  return (
    <main className="min-h-screen bg-[#0a0e0c] text-[#d8f5df] font-mono px-6 py-10">
      <div className="max-w-5xl mx-auto">
        <nav className="flex items-center gap-4 text-xs mb-8">
          <Link href="/" className="text-[#5c9d78] hover:text-[#3ddc84] transition-colors">
            ← pipeline
          </Link>
          <span className="text-[#1c2b21]">/</span>
          <Link href="/backtests" className="text-[#5c9d78] hover:text-[#3ddc84] transition-colors">
            backtests
          </Link>
          <span className="text-[#1c2b21]">/</span>
          <span className="text-[#3ddc84]">regimes</span>
        </nav>

        <h1 className="text-xl mb-1 text-[#eafff0]">
          Regimes de mercado <span className="text-[#5c9d78]">/ estudo</span>
        </h1>
        <p className="text-xs text-[#5c9d78] mb-8 max-w-2xl leading-relaxed">
          {dados.backtests} backtests em {dados.janelas} janelas de 91 dias (8 ativos × 8 períodos,
          ~2 anos), sem nenhuma chamada de API. Cada janela rotulada pelo comportamento do próprio
          ativo: alta acima de +10%, baixa abaixo de −10%, lateral no meio.
        </p>

        {/* ---------- o número que decide ---------- */}
        <section className="border border-[#3d3115] bg-[#181307] rounded p-4 mb-10">
          <div className="text-[10px] uppercase tracking-widest text-[#eda100] mb-3">
            o número que decide se vale um seletor de regime
          </div>
          <div className="grid gap-4 sm:grid-cols-3 mb-4">
            <div>
              <div className="text-[10px] uppercase tracking-widest text-[#3d5c48] mb-1">
                comprar e segurar
              </div>
              <div className="text-lg tabular-nums text-[#d8f5df]">
                {oraculo.buy_and_hold.toFixed(2)}%
              </div>
            </div>
            <div>
              <div className="text-[10px] uppercase tracking-widest text-[#3d5c48] mb-1">
                seletor com regime perfeito
              </div>
              <div className="text-lg tabular-nums text-[#d8f5df]">
                {oraculo.perfeito.toFixed(2)}%
              </div>
            </div>
            <div>
              <div className="text-[10px] uppercase tracking-widest text-[#3d5c48] mb-1">
                teto do ganho
              </div>
              <div className="text-lg tabular-nums text-[#eda100]">
                +{oraculo.teto.toFixed(2)} pts
              </div>
            </div>
          </div>
          <p className="text-[11px] text-[#5c9d78] leading-relaxed">
            Mesmo <strong className="text-[#d8f5df]">sabendo o futuro</strong>, um seletor de regime
            ganharia {oraculo.teto.toFixed(2)} pontos. Esse é o limite superior, inalcançável.
          </p>
        </section>

        {/* ---------- detector realista ---------- */}
        <section className="border border-[#3d1a14] bg-[#1a0d0a] rounded p-4 mb-10">
          <div className="text-[10px] uppercase tracking-widest text-[#e07a5f] mb-3">
            e o detector honesto destrói valor
          </div>
          <div className="grid gap-4 sm:grid-cols-4 mb-4">
            <div>
              <div className="text-[10px] uppercase tracking-widest text-[#3d5c48] mb-1">
                acertou o regime
              </div>
              <div className="text-lg tabular-nums text-[#e07a5f]">
                {detector_real.acertos}/{detector_real.de}
              </div>
              <div className="text-[10px] text-[#3d5c48]">{acerto.toFixed(0)}%</div>
            </div>
            <div>
              <div className="text-[10px] uppercase tracking-widest text-[#3d5c48] mb-1">
                adaptativo
              </div>
              <div className="text-lg tabular-nums text-[#d8f5df]">
                {detector_real.adaptativo.toFixed(2)}%
              </div>
            </div>
            <div>
              <div className="text-[10px] uppercase tracking-widest text-[#3d5c48] mb-1">
                comprar e segurar
              </div>
              <div className="text-lg tabular-nums text-[#d8f5df]">
                {detector_real.buy_and_hold.toFixed(2)}%
              </div>
            </div>
            <div>
              <div className="text-[10px] uppercase tracking-widest text-[#3d5c48] mb-1">
                ganho real
              </div>
              <div className="text-lg tabular-nums text-[#e07a5f]">
                {detector_real.ganho.toFixed(2)} pts
              </div>
            </div>
          </div>
          <p className="text-[11px] text-[#5c9d78] leading-relaxed">
            Detector = o regime da janela anterior, sem olhar o futuro.{" "}
            {acerto.toFixed(0)}% de acerto é <strong className="text-[#d8f5df]">pior que chutar
            &ldquo;{maiorRegime}&rdquo; sempre</strong> ({chuteBase.toFixed(0)}% das janelas).
          </p>
        </section>

        {/* ---------- retorno por regime ---------- */}
        <section className="mb-10">
          <div className="text-[10px] uppercase tracking-widest text-[#3d5c48] mb-2">
            retorno médio por estratégia × regime
          </div>
          <div className="overflow-x-auto border border-[#1c2b21] rounded">
            <table className="w-full text-sm min-w-[36rem]">
              <thead>
                <tr className="text-[10px] uppercase tracking-widest text-[#3d5c48]">
                  <th className="text-left font-normal px-4 py-2.5">estratégia</th>
                  {REGIMES.map((r) => (
                    <th key={r} className="text-right font-normal px-4 py-2.5">
                      {r}{" "}
                      <span className="text-[#2d4636]">({contagem_regime[r]})</span>
                    </th>
                  ))}
                  <th className="text-right font-normal px-4 py-2.5">geral</th>
                </tr>
              </thead>
              <tbody>
                {dados.estrategias.map((n) => (
                  <tr key={n} className="border-t border-[#141f18]">
                    <td className="px-4 py-2.5 text-[#d8f5df]">{ROTULOS[n] ?? n}</td>
                    {REGIMES.map((r) => (
                      <td
                        key={r}
                        className={`text-right px-4 py-2.5 tabular-nums ${corRetorno(por_regime[n][r])}`}
                      >
                        {por_regime[n][r] > 0 ? "+" : ""}
                        {por_regime[n][r].toFixed(2)}%
                      </td>
                    ))}
                    <td
                      className={`text-right px-4 py-2.5 tabular-nums ${corRetorno(por_regime[n].geral)}`}
                    >
                      {por_regime[n].geral > 0 ? "+" : ""}
                      {por_regime[n].geral.toFixed(2)}%
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="text-[10px] text-[#3d5c48] mt-2 leading-relaxed max-w-2xl">
            O RSI perde 39 pontos para o comprar-e-segurar em alta e ganha 18 em baixa — variação de
            57 pontos conforme o regime. Não é ruído, é estrutura.
          </p>
        </section>

        {/* ---------- vantagem sobre b&h ---------- */}
        <section className="mb-10">
          <div className="text-[10px] uppercase tracking-widest text-[#3d5c48] mb-2">
            vantagem sobre o comprar-e-segurar (pontos)
          </div>
          <div className="overflow-x-auto border border-[#1c2b21] rounded">
            <table className="w-full text-sm min-w-[36rem]">
              <thead>
                <tr className="text-[10px] uppercase tracking-widest text-[#3d5c48]">
                  <th className="text-left font-normal px-4 py-2.5">estratégia</th>
                  {REGIMES.map((r) => (
                    <th key={r} className="text-right font-normal px-4 py-2.5">{r}</th>
                  ))}
                  <th className="text-right font-normal px-4 py-2.5">geral</th>
                  <th className="text-right font-normal px-4 py-2.5">venceu</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(vantagem).map(([n, v]) => (
                  <tr key={n} className="border-t border-[#141f18]">
                    <td className="px-4 py-2.5 text-[#d8f5df]">{ROTULOS[n] ?? n}</td>
                    {REGIMES.map((r) => (
                      <td
                        key={r}
                        className={`text-right px-4 py-2.5 tabular-nums ${corVantagem(v[r])}`}
                      >
                        {v[r] > 0 ? "+" : ""}
                        {v[r].toFixed(2)}
                      </td>
                    ))}
                    <td className={`text-right px-4 py-2.5 tabular-nums ${corVantagem(v.geral)}`}>
                      {v.geral > 0 ? "+" : ""}
                      {v.geral.toFixed(2)}
                    </td>
                    <td className="text-right px-4 py-2.5 tabular-nums text-[#5c9d78]">
                      {v.venceu}/{v.de}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="text-[10px] text-[#3d5c48] mt-2 leading-relaxed max-w-2xl">
            Nenhuma estratégia bate o comprar-e-segurar no geral, e todas vencem em menos da metade
            das janelas.
          </p>
        </section>

        {/* ---------- transições ---------- */}
        <section className="mb-10">
          <div className="text-[10px] uppercase tracking-widest text-[#3d5c48] mb-2">
            o regime persiste? (linha = anterior, coluna = seguinte)
          </div>
          <div className="overflow-x-auto border border-[#1c2b21] rounded">
            <table className="w-full text-sm min-w-[26rem]">
              <thead>
                <tr className="text-[10px] uppercase tracking-widest text-[#3d5c48]">
                  <th className="text-left font-normal px-4 py-2.5">de \ para</th>
                  {REGIMES.map((r) => (
                    <th key={r} className="text-right font-normal px-4 py-2.5">{r}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {REGIMES.map((a) => {
                  const total = REGIMES.reduce((s, b) => s + transicoes[a][b], 0) || 1;
                  return (
                    <tr key={a} className="border-t border-[#141f18]">
                      <td className="px-4 py-2.5 text-[#d8f5df]">{a}</td>
                      {REGIMES.map((b) => {
                        const pct = (transicoes[a][b] / total) * 100;
                        return (
                          <td
                            key={b}
                            className="text-right px-4 py-2.5 tabular-nums"
                            style={{ color: `rgb(${216 - pct * 1.2}, ${245 - pct}, ${223 - pct})` }}
                          >
                            {pct.toFixed(0)}%
                          </td>
                        );
                      })}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <p className="text-[10px] text-[#3d5c48] mt-2 leading-relaxed max-w-2xl">
            Depois de uma janela de alta vem 31% alta, 34% lateral, 34% baixa. É praticamente
            sorteio — e é por isso que o detector não funciona.
          </p>
        </section>

        <p className="text-[10px] text-[#2d4636] leading-relaxed max-w-2xl">
          Estudo rodado uma vez em {dados.gerado_em}, offline. Não é dado ao vivo. Viés conhecido e
          não corrigido: os ativos são majors que existem hoje — quem morreu no caminho não está na
          amostra, então os retornos absolutos são otimistas. A comparação entre estratégias segue
          válida: todas enfrentaram as mesmas janelas.
        </p>
      </div>
    </main>
  );
}
