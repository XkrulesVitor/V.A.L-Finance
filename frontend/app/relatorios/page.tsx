import type { Metadata } from "next";
import { Diagnostico } from "@/app/Diagnostico";
import { variaveisFaltando } from "@/lib/supabase";
import { Cabecalho } from "@/app/_componentes/Cabecalho";
import { carregarRelatorios, rotuloDaSemana, type Semana } from "@/lib/relatorios";
import { sinal, usd } from "@/lib/carteira";

export const metadata: Metadata = {
  title: "Relatórios",
  description: "Quanto cada estratégia rendeu, semana a semana.",
};

export const revalidate = 300;

const cor = (v: number | null) =>
  v === null || Math.abs(v) < 0.005 ? "text-vale-tinta-3" : v > 0 ? "text-vale-alta" : "text-vale-baixa";

function Pct({ v, className = "" }: { v: number | null; className?: string }) {
  if (v === null) return <span className={`text-vale-tinta-3 ${className}`}>—</span>;
  return (
    <span className={`${cor(v)} ${className}`}>
      {sinal(v)}
      {Math.abs(v).toFixed(2)}%
    </span>
  );
}

export default async function Relatorios() {
  const faltando = variaveisFaltando();
  if (faltando.length) return <Diagnostico faltando={faltando} />;
  const { semanas, desdeOInicio } = await carregarRelatorios();

  return (
    <>
      <Cabecalho atual="/relatorios" />
      <main className="mx-auto max-w-[900px] px-5 pb-20 sm:px-8">
        <h1 className="pt-12 pb-10 text-[clamp(1.9rem,4vw,2.6rem)] font-medium leading-none tracking-[-0.035em] lg:pt-16">
          Relatórios
        </h1>

        <section>
          <h2 className="mb-3 text-[13px] uppercase tracking-[0.12em] text-vale-tinta-3">Desde o início</h2>
          <ul className="grid grid-cols-2 gap-px border border-vale-fio bg-vale-fio sm:grid-cols-3">
            {desdeOInicio.map((d) => (
              <li key={d.id} className="bg-vale-superficie px-5 py-4">
                <div className="text-[13px] text-vale-tinta-2">{d.nome}</div>
                <div className="num mt-1.5 text-[18px] tracking-[-0.02em]">
                  <Pct v={d.pct} />
                </div>
                <div className={`num mt-0.5 text-[12px] ${cor(d.usd)}`}>
                  {sinal(d.usd)}
                  {usd(Math.abs(d.usd))}
                </div>
              </li>
            ))}
          </ul>
        </section>

        {semanas.map((s) => (
          <SemanaCartao key={s.inicio} s={s} />
        ))}
      </main>
    </>
  );
}

function SemanaCartao({ s }: { s: Semana }) {
  const comResultado = s.linhas.filter((l) => l.pct !== null);
  const topo = comResultado.length > 1 ? comResultado.reduce((a, b) => (b.pct! > a.pct! ? b : a)) : null;
  // Só destaca quem ganhou de fato: ficar parado em 0% não é "melhor".
  const melhor = topo && topo.pct! > 0.005 ? topo : null;

  return (
    <section className="mt-12">
      <div className="mb-3 flex items-baseline justify-between">
        <h2 className="text-[17px] font-medium tracking-[-0.015em]">{rotuloDaSemana(s.inicio, s.fim)}</h2>
        {s.emAndamento && <span className="text-[12px] text-vale-tinta-3">em andamento</span>}
      </div>
      <table className="w-full border-collapse border border-vale-fio text-[13px]">
        <tbody>
          {/* Quem ainda não existia na semana não aparece nela. */}
          {comResultado.map((l) => (
            <tr key={l.id} className="border-b border-vale-fio bg-vale-superficie last:border-b-0">
              <td className="px-5 py-3 text-vale-tinta">
                {l.nome}
                {melhor?.id === l.id && <span className="ml-2 text-[11px] text-vale-alta">melhor da semana</span>}
              </td>
              <td className="num px-3 py-3 text-right">
                <Pct v={l.pct} />
              </td>
              <td className={`num hidden px-3 py-3 text-right sm:table-cell ${cor(l.usd)}`}>
                {l.usd === null ? "" : `${sinal(l.usd)}${usd(Math.abs(l.usd))}`}
              </td>
              <td className="num px-5 py-3 text-right text-[12px] text-vale-tinta-3">
                {l.operacoes === 0 ? "sem operações" : l.operacoes === 1 ? "1 operação" : `${l.operacoes} operações`}
              </td>
            </tr>
          ))}
          <tr className="bg-vale-fundo">
            <td className="px-5 py-3 text-vale-tinta-3">Só segurar as moedas</td>
            <td className="num px-3 py-3 text-right">
              <Pct v={s.referenciaPct} />
            </td>
            <td className="hidden sm:table-cell" />
            <td />
          </tr>
        </tbody>
      </table>
    </section>
  );
}
