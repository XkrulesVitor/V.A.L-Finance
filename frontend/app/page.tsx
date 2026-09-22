import type { Metadata } from "next";
import { Diagnostico } from "@/app/Diagnostico";
import { variaveisFaltando } from "@/lib/supabase";
import { Cabecalho } from "@/app/_componentes/Cabecalho";
import { CurvaDeCapital } from "@/app/_componentes/CurvaDeCapital";
import { CartaoDePosicao } from "@/app/_componentes/CartaoDePosicao";
import { HistoricoDeOperacoes } from "@/app/_componentes/HistoricoDeOperacoes";
import {
  CAPITAL_POR_CONTA,
  carregar,
  montarCurva,
  montarOperacoes,
  montarPosicoes,
  precosAoVivo,
  precosDoUltimoCiclo,
  sinal,
  usd,
} from "@/lib/carteira";
import { diaMes, hora } from "@/lib/tempo";

export const metadata: Metadata = {
  title: "Carteira",
  description: "Patrimônio, posições abertas e operações fechadas do forward test.",
};

export const revalidate = 0;

/*
 * A carteira.
 *
 * Ordem de prioridade, de cima para baixo: quanto eu tenho, onde está
 * aplicado, o que já foi fechado. É a leitura de quem é dono do dinheiro.
 * O que interessa a quem opera o sistema — tese do cérebro, vetos do
 * risco, cadência, deslize — está na página Motor.
 */

export default async function Carteira() {
  const faltando = variaveisFaltando();
  if (faltando.length) return <Diagnostico faltando={faltando} />;

  let dados;
  try {
    dados = await carregar();
  } catch (e) {
    return <Diagnostico erro={e instanceof Error ? e.message : String(e)} />;
  }
  const { ciclos, contas, tendencia } = dados;

  const pares = [...new Set(ciclos.map((c) => c.symbol))].sort();
  const ultimoCiclo = precosDoUltimoCiclo(ciclos);
  const aoVivo = await precosAoVivo(pares);
  const precoFinal = new Map(pares.map((p) => [p, aoVivo.get(p) ?? ultimoCiclo.get(p) ?? 0]));
  const tudoAoVivo = pares.every((p) => aoVivo.has(p));

  const posicoes = montarPosicoes(pares, contas, ciclos, precoFinal, tendencia);
  const operacoes = montarOperacoes(ciclos);

  const inicial = pares.length * CAPITAL_POR_CONTA;
  const caixa = posicoes.reduce((s, p) => s + p.caixa, 0);
  const investido = posicoes.reduce((s, p) => s + p.valor, 0);
  const patrimonio = caixa + investido;
  const delta = patrimonio - inicial;
  const deltaPct = inicial ? (delta / inicial) * 100 : 0;
  const realizado = operacoes.reduce((s, o) => s + o.resultado, 0);
  const emAberto = posicoes.reduce((s, p) => s + (p.emAberto ?? 0), 0);
  const positivo = delta >= 0;

  // A curva termina no valor de agora, e não no do último ciclo — senão o
  // gráfico e o número grande logo acima dele discordariam.
  const curva = montarCurva(ciclos, pares);
  if (curva.length) curva.push({ t: new Date().toISOString(), equity: patrimonio });

  const abertas = posicoes.filter((p) => p.aberta);
  const fora = posicoes.filter((p) => !p.aberta);
  const inicio = ciclos[0]?.created_at;

  return (
    <>
      <Cabecalho atual="/" />

      <main className="mx-auto max-w-[1240px] px-5 pb-28 sm:px-8">
        {/* ------------------------------------------------ patrimônio ---- */}
        <section className="grid grid-cols-1 gap-10 pt-14 pb-14 lg:grid-cols-12 lg:gap-14 lg:pt-20">
          <div className="lg:col-span-5">
            <div className="text-[13px] text-vale-tinta-3">Patrimônio</div>

            <h1 className="num mt-2 text-[clamp(2.6rem,6.5vw,4rem)] leading-[0.95] tracking-[-0.045em] text-vale-tinta">
              {usd(patrimonio)}
            </h1>

            <div className={`num mt-4 text-[17px] ${positivo ? "text-vale-alta" : "text-vale-baixa"}`}>
              {sinal(delta)}
              {usd(Math.abs(delta))}
              <span className="ml-3">
                {sinal(deltaPct)}
                {Math.abs(deltaPct).toFixed(2)}%
              </span>
              {inicio && (
                <span className="ml-3 text-[13px] text-vale-tinta-3">desde {diaMes(inicio)}</span>
              )}
            </div>

            <dl className="mt-9 grid grid-cols-2 gap-x-8 gap-y-5">
              <Parcela rotulo="Realizado" valor={realizado} colorir />
              <Parcela rotulo="Em aberto" valor={emAberto} colorir />
              <Parcela rotulo="Investido" valor={investido} />
              <Parcela rotulo="Em caixa" valor={caixa} />
            </dl>

            <div
              className="mt-6 flex h-1.5 overflow-hidden rounded-full bg-vale-elevado"
              role="img"
              aria-label={`${((investido / patrimonio) * 100).toFixed(0)}% investido, ${((caixa / patrimonio) * 100).toFixed(0)}% em caixa`}
            >
              <div className="bg-vale-tinta-2" style={{ width: `${(investido / patrimonio) * 100}%` }} />
            </div>
            <div className="num mt-2 flex justify-between text-[11px] text-vale-tinta-3">
              <span>{((investido / patrimonio) * 100).toFixed(0)}% investido</span>
              <span>{((caixa / patrimonio) * 100).toFixed(0)}% em caixa</span>
            </div>
          </div>

          <div className="lg:col-span-7">
            <CurvaDeCapital pontos={curva} inicial={inicial} altura={250} />
            <p className="num mt-3 text-right text-[11px] text-vale-tinta-3">
              {tudoAoVivo ? `preços ao vivo · ${hora(new Date())}` : "preço do último ciclo — Binance indisponível agora"}
            </p>
          </div>
        </section>

        {/* ------------------------------------------------- posições ---- */}
        <section>
          <h2 className="mb-4 text-[19px] font-medium tracking-[-0.02em]">
            Posições{" "}
            <span className="num ml-1 text-[14px] font-normal text-vale-tinta-3">
              {abertas.length} aberta{abertas.length === 1 ? "" : "s"}
            </span>
          </h2>
          <div className="grid grid-cols-1 gap-px border border-vale-fio bg-vale-fio lg:grid-cols-2">
            {abertas.map((p) => (
              <CartaoDePosicao key={p.par} p={p} />
            ))}
            {fora.map((p) => (
              <CartaoDePosicao key={p.par} p={p} />
            ))}
          </div>
        </section>

        {/* ------------------------------------------ operações fechadas -- */}
        <section className="mt-20">
          <h2 className="mb-4 text-[19px] font-medium tracking-[-0.02em]">
            Operações fechadas{" "}
            <span className="num ml-1 text-[14px] font-normal text-vale-tinta-3">
              {operacoes.length}
            </span>
          </h2>
          <HistoricoDeOperacoes operacoes={operacoes} />
        </section>
      </main>
    </>
  );
}

function Parcela({ rotulo, valor, colorir }: { rotulo: string; valor: number; colorir?: boolean }) {
  const cor = !colorir || Math.abs(valor) < 0.005
    ? "text-vale-tinta"
    : valor > 0
      ? "text-vale-alta"
      : "text-vale-baixa";
  return (
    <div>
      <dt className="text-[12px] text-vale-tinta-3">{rotulo}</dt>
      <dd className={`num mt-1 text-[16px] tracking-[-0.02em] ${cor}`}>
        {colorir ? sinal(valor) : ""}
        {usd(colorir ? Math.abs(valor) : valor)}
      </dd>
    </div>
  );
}
