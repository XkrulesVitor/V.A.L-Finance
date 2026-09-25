import type { Metadata } from "next";
import { Diagnostico } from "@/app/Diagnostico";
import { variaveisFaltando } from "@/lib/supabase";
import { Cabecalho } from "@/app/_componentes/Cabecalho";
import { CartaoDaCarteira } from "@/app/_componentes/CartaoDaCarteira";
import { FAMILIAS, carregarVisao } from "@/lib/carteiras";
import { PARES, sinal, usd } from "@/lib/carteira";
import { hora } from "@/lib/tempo";

export const metadata: Metadata = {
  title: "Carteiras",
  description: "Seis estratégias de bitcoin e ether, ao preço real.",
};

// Cinco minutos: cada visita dentro da janela reaproveita a página pronta.
export const revalidate = 300;

/*
 * A primeira tela: cada estratégia, quanto vale e onde está o dinheiro.
 * Sem texto explicativo (pedido do dono em 25/09): o que precisa de
 * análise fica nas páginas técnicas; o resumo por semana, em /relatorios.
 */

export default async function Carteiras() {
  const faltando = variaveisFaltando();
  if (faltando.length) return <Diagnostico faltando={faltando} />;

  // Erro de leitura é relançado: com ISR, o Next mantém a última versão boa.
  const { cartoes, precos, aoVivo } = await carregarVisao();
  const total = cartoes.reduce((s, c) => s + c.patrimonio, 0);
  const inicial = cartoes.reduce((s, c) => s + c.inicial, 0);
  const deltaPct = ((total - inicial) / inicial) * 100;

  return (
    <>
      <Cabecalho atual="/" />

      <main className="mx-auto max-w-[1240px] px-5 pb-20 sm:px-8">
        <section className="flex flex-wrap items-end justify-between gap-6 pt-12 pb-10 lg:pt-16">
          <div>
            <h1 className="text-[clamp(1.9rem,4vw,2.6rem)] font-medium leading-none tracking-[-0.035em]">Carteiras</h1>
            <p className="num mt-3 text-[13px] text-vale-tinta-3">
              {usd(total)} no total{" "}
              <span className={deltaPct >= 0 ? "text-vale-alta" : "text-vale-baixa"}>
                {sinal(deltaPct)}
                {Math.abs(deltaPct).toFixed(2)}%
              </span>
            </p>
          </div>
          <dl className="flex items-end gap-7">
            {PARES.map((par) => (
              <div key={par}>
                <dt className="text-[11px] uppercase tracking-[0.1em] text-vale-tinta-3">{par.replace("USDT", "")}</dt>
                <dd className="num mt-1 text-[16px] tracking-[-0.02em] text-vale-tinta">
                  {precos.has(par) ? usd(precos.get(par)!) : "—"}
                </dd>
              </div>
            ))}
            <p className="num pb-0.5 text-[11px] whitespace-nowrap text-vale-tinta-3">
              {aoVivo ? `ao vivo · ${hora(new Date())}` : "último ciclo"}
            </p>
          </dl>
        </section>

        {FAMILIAS.map((f) => {
          const daFamilia = cartoes.filter((c) => c.carteira.familia === f.id);
          if (!daFamilia.length) return null;
          return (
            <section key={f.id} className="mt-10 first-of-type:mt-0">
              <h2 className="mb-3 text-[13px] uppercase tracking-[0.12em] text-vale-tinta-3">{f.titulo}</h2>
              <div className="grid grid-cols-1 gap-px border border-vale-fio bg-vale-fio md:grid-cols-3">
                {daFamilia.map((c) => (
                  <CartaoDaCarteira key={c.carteira.id} cartao={c} />
                ))}
              </div>
            </section>
          );
        })}
      </main>
    </>
  );
}
