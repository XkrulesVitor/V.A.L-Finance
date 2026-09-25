import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { Diagnostico } from "@/app/Diagnostico";
import { getSupabaseClient, variaveisFaltando } from "@/lib/supabase";
import { Cabecalho } from "@/app/_componentes/Cabecalho";
import { CurvaDeCapital } from "@/app/_componentes/CurvaDeCapital";
import { CartaoDePosicao } from "@/app/_componentes/CartaoDePosicao";
import { HistoricoDeOperacoes } from "@/app/_componentes/HistoricoDeOperacoes";
import { Conselho } from "@/app/_componentes/Conselho";
import { Rodape, avisosDa } from "@/app/_componentes/Avisos";
import {
  CAPITAL_POR_CONTA,
  PARES,
  carregarCarteira,
  montarCurva,
  montarOperacoes,
  montarPosicoes,
  precosAoVivo,
  precosDasLeituras,
  sinal,
  usd,
} from "@/lib/carteira";
import {
  COM_CONSELHO,
  COM_META,
  IDS,
  NOTA_DO_HISTORICO,
  ROTULO_DA_FAMILIA,
  type Carteira,
  ehIdDeCarteira,
  lerCatalogo,
  lerConselho,
  primeiraLeitura,
} from "@/lib/carteiras";
import { dataCurta, diaMes, hora } from "@/lib/tempo";

/*
 * Uma carteira.
 *
 * É a antiga página Carteira, agora de uma das seis: toda consulta leva
 * `.eq("carteira", id)`. Ordem de prioridade, de cima para baixo: quanto
 * eu tenho, onde está aplicado, o que já foi fechado. O que interessa a
 * quem opera o sistema — a regra ciclo a ciclo, as travas, o deslize —
 * está no Motor, filtrado por esta carteira.
 */

export const revalidate = 300;
// Só as seis existem; qualquer outro id é 404, sem consultar o banco.
export const dynamicParams = false;

export function generateStaticParams() {
  return IDS.map((id) => ({ id }));
}

type Props = { params: Promise<{ id: string }> };

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { id } = await params;
  return {
    title: `Carteira ${id}`,
    description: `Patrimônio, posições e operações da carteira ${id} do forward test.`,
  };
}

export default async function PaginaDaCarteira({ params }: Props) {
  const { id } = await params;
  if (!ehIdDeCarteira(id)) notFound();

  const faltando = variaveisFaltando();
  if (faltando.length) return <Diagnostico faltando={faltando} />;

  let dados, catalogo, conselho, aoVivo;
  try {
    const sb = getSupabaseClient();
    [dados, catalogo, conselho, aoVivo] = await Promise.all([
      carregarCarteira(id),
      lerCatalogo(sb),
      COM_CONSELHO.has(id) ? lerConselho(sb) : Promise.resolve(null),
      precosAoVivo(PARES),
    ]);
  } catch (e) {
    // Configuração ausente é tratada acima. Um erro de leitura (Supabase
    // fora do ar, timeout) é relançado: com ISR, devolver a tela de
    // diagnóstico a gravaria no cache no lugar da última versão boa por 5
    // min; relançando, o Next mantém a anterior e o error.tsx cobre o resto.
    throw e;
  }
  const { contas, ordens, diario, ciclos, leituras } = dados;

  // Se a tabela `carteiras` ainda não tiver a linha, a página não quebra:
  // mostra o id no lugar do nome.
  const c: Carteira = catalogo.find((x) => x.id === id) ?? {
    id,
    nome: id,
    descricao_leiga: "",
    familia: id.startsWith("G") ? "stop_gain" : "tendencia",
    ativa_desde: null,
    ativa: false,
    ordem: 0,
  };

  const ultimoCiclo = precosDasLeituras(leituras);
  const precoFinal = new Map<string, number>();
  for (const p of PARES) {
    const v = aoVivo.get(p) ?? ultimoCiclo.get(p);
    if (v !== undefined) precoFinal.set(p, v);
  }
  const tudoAoVivo = PARES.every((p) => aoVivo.has(p));

  const posicoes = montarPosicoes(PARES, contas, ordens, precoFinal, leituras, {
    comMeta: COM_META.has(id),
    iniciada: Boolean(c.ativa_desde),
  });
  const operacoes = montarOperacoes(ordens);

  const inicial = PARES.length * CAPITAL_POR_CONTA;
  const caixa = posicoes.reduce((s, p) => s + p.caixa, 0);
  const investido = posicoes.reduce((s, p) => s + p.valor, 0);
  const patrimonio = caixa + investido;
  const delta = patrimonio - inicial;
  const deltaPct = inicial ? (delta / inicial) * 100 : 0;
  const realizado = operacoes.reduce((s, o) => s + o.resultado, 0);
  const emAberto = posicoes.reduce((s, p) => s + (p.emAberto ?? 0), 0);
  const positivo = delta >= 0;
  const operou = contas.length > 0;

  // A curva termina no valor de agora, e não no do último ciclo — senão o
  // gráfico e o número grande logo acima dele discordariam.
  const curva = montarCurva(ciclos, diario, PARES);
  if (curva.length) curva.push({ t: new Date().toISOString(), equity: patrimonio });

  const abertas = posicoes.filter((p) => p.aberta);
  const fora = posicoes.filter((p) => !p.aberta);
  const inicio = ciclos[0]?.created_at ?? c.ativa_desde;
  const nota = NOTA_DO_HISTORICO[id];

  return (
    <>
      <Cabecalho atual="/" />

      <main className="mx-auto max-w-[1240px] px-5 pb-16 sm:px-8">
        {/* ------------------------------------------------- identidade ---- */}
        <section className="pt-10 lg:pt-14">
          <Link href="/" className="text-[12.5px] text-vale-tinta-3 transition-colors hover:text-vale-tinta-2">
            ← Carteiras
          </Link>
          <div className="mt-7 flex items-baseline gap-3 text-[12px] text-vale-tinta-3">
            <span className="num">{id}</span>
            <span>{ROTULO_DA_FAMILIA[c.familia] ?? c.familia}</span>
          </div>
          <h1 className="mt-2 text-[clamp(2rem,4.5vw,2.9rem)] font-medium leading-[1.05] tracking-[-0.035em]">
            {c.nome}
          </h1>
          {c.descricao_leiga && (
            <p className="mt-4 max-w-[60ch] text-[14.5px] leading-relaxed text-vale-tinta-2">{c.descricao_leiga}</p>
          )}
        </section>

        {/* ------------------------------------------------ patrimônio ---- */}
        <section className="grid grid-cols-1 gap-10 pt-12 pb-14 lg:grid-cols-12 lg:gap-14">
          <div className="lg:col-span-5">
            <div className="text-[13px] text-vale-tinta-3">Patrimônio</div>

            <div className="num mt-2 text-[clamp(2.2rem,4.2vw,3.4rem)] leading-[0.95] tracking-[-0.045em] whitespace-nowrap text-vale-tinta">
              {usd(patrimonio)}
            </div>

            {operou ? (
              <div className={`num mt-4 text-[17px] ${positivo ? "text-vale-alta" : "text-vale-baixa"}`}>
                {sinal(delta)}
                {usd(Math.abs(delta))}
                <span className="ml-3">
                  {sinal(deltaPct)}
                  {Math.abs(deltaPct).toFixed(2)}%
                </span>
                {inicio && <span className="ml-3 text-[13px] text-vale-tinta-3">desde {diaMes(inicio)}</span>}
              </div>
            ) : (
              <div className="mt-4 text-[14px] text-vale-tinta-3">ainda não operou</div>
            )}

            <p className="mt-2 text-[12px] leading-relaxed text-vale-tinta-3">
              {c.ativa_desde
                ? [
                    nota ? `regra atual desde ${diaMes(c.ativa_desde)} · o resultado ${nota}` : `ativa desde ${diaMes(c.ativa_desde)}`,
                    `sem leitura até ${dataCurta(primeiraLeitura(c.ativa_desde))}`,
                  ].join(" · ")
                : "aguardando o primeiro ciclo"}
            </p>

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

        {/* -------------------------------------------------- Conselho ---- */}
        {conselho && (
          <section className="mb-16 border border-vale-fio bg-vale-superficie px-6 py-5">
            <Conselho vereditos={[...conselho.values()]} pares={PARES} aberto />
          </section>
        )}

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
            <span className="num ml-1 text-[14px] font-normal text-vale-tinta-3">{operacoes.length}</span>
          </h2>
          <HistoricoDeOperacoes operacoes={operacoes} />
        </section>

        {/* ---------------------------------------------------- avisos ---- */}
        <section className="mt-16 flex flex-col gap-6 lg:flex-row lg:items-start lg:justify-between">
          <ul className="flex max-w-[76ch] flex-col gap-1.5 text-[12px] leading-relaxed text-vale-tinta-3">
            {avisosDa(id).map((a) => (
              <li key={a}>{a}</li>
            ))}
          </ul>
          <Link
            href={`/motor?carteira=${id}`}
            className="shrink-0 text-[13px] text-vale-tinta-2 transition-colors hover:text-vale-tinta"
          >
            Decisões desta carteira no Motor →
          </Link>
        </section>

        <Rodape />
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
