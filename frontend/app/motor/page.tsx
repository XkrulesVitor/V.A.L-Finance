import type { Metadata } from "next";
import { Diagnostico } from "@/app/Diagnostico";
import { variaveisFaltando } from "@/lib/supabase";
import { Cabecalho } from "@/app/_componentes/Cabecalho";
import { FluxoDeDecisoes } from "@/app/_componentes/FluxoDeDecisoes";
import { carregar } from "@/lib/carteira";
import { diaMes } from "@/lib/tempo";

export const metadata: Metadata = {
  title: "Motor",
  description: "Como o sistema está decidindo: ciclos, teses do cérebro, vetos do motor de risco.",
};

export const revalidate = 0;

/*
 * O motor por dentro. Saiu da página inicial porque é leitura de quem
 * opera o sistema, não de quem acompanha o dinheiro — mas nada se perdeu:
 * o fluxo de decisões com as duas vozes (cérebro e risco) continua aqui.
 */

export default async function Motor() {
  const faltando = variaveisFaltando();
  if (faltando.length) return <Diagnostico faltando={faltando} />;

  let dados;
  try {
    dados = await carregar();
  } catch (e) {
    return <Diagnostico erro={e instanceof Error ? e.message : String(e)} />;
  }
  const { ciclos, ultimaColeta } = dados;

  const ultimo = ciclos[ciclos.length - 1];
  const minutos = ultimo
    ? Math.round((Date.now() - new Date(ultimo.created_at).getTime()) / 60000)
    : null;
  // O agendamento do GitHub é melhor-esforço (medido: ~4 h de intervalo
  // médio). Um limiar de 1 h chamaria de parado um sistema saudável.
  const vivo = minutos !== null && minutos < 420;

  const consultas = ciclos.filter((c) => c.llm_output).length;
  const vetos = ciclos.filter((c) => c.risk_result?.aprovado === false).length;
  const overrides = ciclos.filter((c) => c.risk_result?.override_do_llm).length;
  const erros = ciclos.filter((c) => c.status === "brain_error").length;
  const deslizes = ciclos
    .map((c) => c.market_snapshot?.deslize_pct)
    .filter((v): v is number => typeof v === "number");
  const deslize = deslizes.length ? deslizes.reduce((a, b) => a + b, 0) / deslizes.length : null;

  return (
    <>
      <Cabecalho atual="/motor" />

      <main className="mx-auto max-w-[1240px] px-5 pb-28 sm:px-8">
        <section className="pt-14 pb-10 lg:pt-20">
          <div className="flex items-center gap-2 text-[13px] text-vale-tinta-3">
            <span className="relative flex h-1.5 w-1.5">
              {vivo && (
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-vale-alta opacity-60" />
              )}
              <span className={`relative inline-flex h-1.5 w-1.5 rounded-full ${vivo ? "bg-vale-alta" : "bg-vale-tinta-3"}`} />
            </span>
            {vivo ? "operando" : `sem ciclo há ${minutos} min`}
          </div>
          <h1 className="mt-3 text-[clamp(2rem,4.5vw,2.9rem)] font-medium leading-[1.05] tracking-[-0.035em]">
            Motor
          </h1>
          <p className="mt-4 max-w-[56ch] text-[14.5px] leading-relaxed text-vale-tinta-2">
            Cada ciclo confere stop e alvo; a cada 6 h o cérebro propõe uma tese e o motor
            de risco decide. Execução simulada ao preço real — nenhuma ordem sai para
            corretora.
          </p>
        </section>

        <section className="grid grid-cols-2 gap-px border border-vale-fio bg-vale-fio lg:grid-cols-6">
          <Medida rotulo="ciclos" valor={String(ciclos.length)} nota={ciclos[0] ? `desde ${diaMes(ciclos[0].created_at)}` : ""} />
          <Medida rotulo="consultas ao cérebro" valor={String(consultas)} nota={`${erros} com erro`} />
          <Medida rotulo="vetos do risco" valor={String(vetos)} nota="entradas barradas" />
          <Medida rotulo="risco sobrepôs" valor={String(overrides)} nota="contra a tese" />
          <Medida
            rotulo="deslize médio"
            valor={deslize === null ? "—" : `${deslize >= 0 ? "+" : ""}${deslize.toFixed(3)}%`}
            nota="ao vivo vs backtest"
          />
          <Medida
            rotulo="coleta"
            valor={ultimaColeta ? `${Math.round((Date.now() - new Date(ultimaColeta).getTime()) / 60000)} min` : "—"}
            nota="desde a última"
          />
        </section>

        <section className="mt-16">
          <h2 className="mb-5 text-[19px] font-medium tracking-[-0.02em]">
            Decisões{" "}
            <span className="num ml-1 text-[14px] font-normal text-vale-tinta-3">mais recentes primeiro</span>
          </h2>
          <FluxoDeDecisoes ciclos={[...ciclos].reverse().slice(0, 60)} />
        </section>
      </main>
    </>
  );
}

function Medida({ rotulo, valor, nota }: { rotulo: string; valor: string; nota: string }) {
  return (
    <div className="bg-vale-superficie px-5 py-4">
      <div className="text-[10.5px] uppercase tracking-[0.1em] text-vale-tinta-3">{rotulo}</div>
      <div className="num mt-2 text-[21px] tracking-[-0.03em] text-vale-tinta">{valor}</div>
      <div className="mt-0.5 text-[11.5px] text-vale-tinta-3">{nota}</div>
    </div>
  );
}
