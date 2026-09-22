import type { Metadata } from "next";
import { Diagnostico } from "@/app/Diagnostico";
import { variaveisFaltando } from "@/lib/supabase";
import { Cabecalho } from "@/app/_componentes/Cabecalho";
import { FluxoDeDecisoes } from "@/app/_componentes/FluxoDeDecisoes";
import { ENTRA_COM, SAI_COM, TENDENCIA_DESDE, carregar } from "@/lib/carteira";
import { diaMes } from "@/lib/tempo";

export const metadata: Metadata = {
  title: "Motor",
  description: "Como o sistema está decidindo: a regra de tendência, ciclo a ciclo.",
};

export const revalidate = 0;

/*
 * O motor por dentro. Saiu da página inicial porque é leitura de quem
 * opera o sistema, não de quem acompanha o dinheiro — mas nada se perdeu:
 * o fluxo de decisões continua aqui, inclusive o da estratégia antiga.
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
  const { ciclos, ultimaColeta, tendencia } = dados;
  const pares = [...new Set(ciclos.map((c) => c.symbol))].sort();

  const ultimo = ciclos[ciclos.length - 1];
  const minutos = ultimo
    ? Math.round((Date.now() - new Date(ultimo.created_at).getTime()) / 60000)
    : null;
  // O agendamento do GitHub é melhor-esforço (medido: ~4 h de intervalo
  // médio). Um limiar de 1 h chamaria de parado um sistema saudável.
  const vivo = minutos !== null && minutos < 420;

  // Deslize contra onde o BACKTEST executaria (abertura das 01:00 UTC depois
  // do voto, ou do candle seguinte ao stop), só nas operações da regra. O
  // `deslize_pct` antigo de cada ciclo comparava com a abertura da hora em
  // curso, que só era a referência certa para a estratégia híbrida.
  const deslizes = ciclos
    .map((c) => c.order_result?.referencia_backtest?.deslize_pct)
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
            Uma vez por dia, compara o preço com a média de seis prazos: entra com {ENTRA_COM}{" "}
            em alta, sai com {SAI_COM} ou menos. Toda hora confere a proteção de 20% abaixo
            da entrada. O LLM não decide — só explica cada operação. Execução simulada ao
            preço real; nenhuma ordem sai para corretora.
          </p>
        </section>

        <section className="grid grid-cols-2 gap-px border border-vale-fio bg-vale-fio lg:grid-cols-6">
          <Medida rotulo="ciclos" valor={String(ciclos.length)} nota={ciclos[0] ? `desde ${diaMes(ciclos[0].created_at)}` : ""} />
          <Medida rotulo="regra" valor="tendência" nota={`desde ${diaMes(TENDENCIA_DESDE + "T12:00:00Z")}`} />
          {pares.slice(0, 2).map((par) => {
            const l = tendencia.get(par);
            return (
              <Medida
                key={par}
                rotulo={par.replace("USDT", "")}
                valor={l?.votos != null ? `${l.votos} de 6` : "—"}
                nota={l?.dia ? `prazos em alta · ${diaMes(l.dia + "T12:00:00Z")}` : "sem leitura ainda"}
              />
            );
          })}
          <Medida
            rotulo="deslize vs backtest"
            valor={deslize === null ? "—" : `${deslize >= 0 ? "+" : ""}${deslize.toFixed(2)}%`}
            nota={deslizes.length ? `média de ${deslizes.length} operações` : "sem operação medida"}
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
