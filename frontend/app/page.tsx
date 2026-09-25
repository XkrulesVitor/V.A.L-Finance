import type { Metadata } from "next";
import { Diagnostico } from "@/app/Diagnostico";
import { variaveisFaltando } from "@/lib/supabase";
import { Cabecalho } from "@/app/_componentes/Cabecalho";
import { CartaoDaCarteira } from "@/app/_componentes/CartaoDaCarteira";
import { AVISO_DA_SORTE, Rodape } from "@/app/_componentes/Avisos";
import { COM_CONSELHO, FAMILIAS, carregarVisao } from "@/lib/carteiras";
import { PARES, usd } from "@/lib/carteira";
import { hora } from "@/lib/tempo";

export const metadata: Metadata = {
  title: "Carteiras",
  description: "Seis carteiras simuladas de bitcoin e ether, lado a lado, ao preço real.",
};

// Cinco minutos: a seção 11.3 da especificação. Cada visita dentro da
// janela reaproveita a página pronta em vez de consultar o Supabase.
export const revalidate = 300;

/*
 * As seis carteiras.
 *
 * Duas famílias, três carteiras cada, na ordem do catálogo: as que seguem
 * a tendência (seguram enquanto a alta durar) e as de stop gain (vendem no
 * lucro). O par que interessa comparar fica na mesma coluna — Réguas em
 * cima, Réguas com meta embaixo; Conselho em cima, Conselho com meta
 * embaixo.
 *
 * Esta página não lê o histórico de decisões (ver `lib/carteiras.ts`). O
 * detalhe de cada carteira — curva, posições, operações — está em
 * `/carteira/[id]`.
 */

export default async function Carteiras() {
  const faltando = variaveisFaltando();
  if (faltando.length) return <Diagnostico faltando={faltando} />;

  let dados;
  try {
    dados = await carregarVisao();
  } catch (e) {
    // Configuração ausente é tratada acima. Um erro de leitura (Supabase
    // fora do ar, timeout) é relançado: com ISR, devolver a tela de
    // diagnóstico a gravaria no cache no lugar da última versão boa por 5
    // min; relançando, o Next mantém a anterior e o error.tsx cobre o resto.
    throw e;
  }
  const { cartoes, conselho, precos, aoVivo } = dados;
  const operando = cartoes.filter((c) => c.carteira.ativa_desde).length;
  const vereditos = [...conselho.values()];

  return (
    <>
      <Cabecalho atual="/" />

      <main className="mx-auto max-w-[1240px] px-5 pb-16 sm:px-8">
        <section className="grid grid-cols-1 gap-8 pt-14 pb-12 lg:grid-cols-12 lg:items-end lg:pt-20">
          <div className="lg:col-span-8">
            <div className="flex items-center gap-2 text-[13px] text-vale-tinta-3">
              <span className="relative flex h-1.5 w-1.5">
                {operando > 0 && (
                  <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-vale-alta opacity-60" />
                )}
                <span
                  className={`relative inline-flex h-1.5 w-1.5 rounded-full ${operando > 0 ? "bg-vale-alta" : "bg-vale-tinta-3"}`}
                />
              </span>
              {operando} de {cartoes.length} operando
            </div>
            <h1 className="mt-3 text-[clamp(2rem,4.5vw,2.9rem)] font-medium leading-[1.05] tracking-[-0.035em]">
              Carteiras
            </h1>
            <p className="mt-4 max-w-[58ch] text-[14.5px] leading-relaxed text-vale-tinta-2">
              Seis jeitos de operar bitcoin e ether, lado a lado. Cada carteira começa com US$ 10.000
              por moeda; o dinheiro é simulado, os preços são reais.
            </p>
          </div>

          <div className="flex items-end gap-8 lg:col-span-4 lg:justify-end">
            <dl className="flex gap-8">
              {PARES.map((par) => (
                <div key={par}>
                  <dt className="text-[11px] uppercase tracking-[0.1em] text-vale-tinta-3">
                    {par.replace("USDT", "")}
                  </dt>
                  <dd className="num mt-1 text-[17px] tracking-[-0.02em] text-vale-tinta">
                    {precos.has(par) ? usd(precos.get(par)!) : "—"}
                  </dd>
                </div>
              ))}
            </dl>
            <p className="num pb-1 text-[11px] whitespace-nowrap text-vale-tinta-3">
              {aoVivo ? `ao vivo · ${hora(new Date())}` : "preço do último ciclo"}
            </p>
          </div>
        </section>

        <p className="max-w-[80ch] border-l border-vale-fio-forte pl-4 text-[12.5px] leading-relaxed text-vale-tinta-3">
          {AVISO_DA_SORTE}
        </p>

        {FAMILIAS.map((f) => {
          const daFamilia = cartoes.filter((c) => c.carteira.familia === f.id);
          if (!daFamilia.length) return null;
          return (
            <section key={f.id} className="mt-14">
              <div className="mb-4 flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1">
                <h2 className="text-[19px] font-medium tracking-[-0.02em]">{f.titulo}</h2>
                <p className="text-[13px] text-vale-tinta-3">{f.texto}</p>
              </div>
              <div className="grid grid-cols-1 gap-px border border-vale-fio bg-vale-fio lg:grid-cols-3">
                {daFamilia.map((c) => (
                  <CartaoDaCarteira
                    key={c.carteira.id}
                    cartao={c}
                    conselho={COM_CONSELHO.has(c.carteira.id) ? vereditos : null}
                  />
                ))}
              </div>
              {f.aviso && <p className="mt-3 text-[12px] text-vale-tinta-3">{f.aviso}</p>}
            </section>
          );
        })}

        <Rodape />
      </main>
    </>
  );
}
