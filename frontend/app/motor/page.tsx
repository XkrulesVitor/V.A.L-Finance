import type { Metadata } from "next";
import Link from "next/link";
import { Diagnostico } from "@/app/Diagnostico";
import { variaveisFaltando } from "@/lib/supabase";
import { Cabecalho } from "@/app/_componentes/Cabecalho";
import { FluxoDeDecisoes } from "@/app/_componentes/FluxoDeDecisoes";
import { PARES } from "@/lib/carteira";
import { IDS, ehIdDeCarteira } from "@/lib/carteiras";
import { carregarMotor } from "@/lib/motor";
import { resumirLeitura } from "@/lib/rotulos";
import { diaMes } from "@/lib/tempo";

export const metadata: Metadata = {
  title: "Motor",
  description: "Como as carteiras estão decidindo, ciclo a ciclo.",
};

export const revalidate = 300;

/*
 * O motor por dentro. É leitura de quem opera o sistema, não de quem
 * acompanha o dinheiro: o fluxo de decisões de todas as carteiras, ou de
 * uma só com `?carteira=G1`. O histórico da estratégia antiga da T1 (até
 * 22/09) continua aqui, abaixo do divisor.
 */

type Props = { searchParams: Promise<{ carteira?: string | string[] }> };

export default async function Motor({ searchParams }: Props) {
  const faltando = variaveisFaltando();
  if (faltando.length) return <Diagnostico faltando={faltando} />;

  const pedido = (await searchParams).carteira;
  const valor = Array.isArray(pedido) ? pedido[0] : pedido;
  const filtro = valor && ehIdDeCarteira(valor.toUpperCase()) ? valor.toUpperCase() : null;

  let dados;
  try {
    dados = await carregarMotor(filtro);
  } catch (e) {
    return <Diagnostico erro={e instanceof Error ? e.message : String(e)} />;
  }
  const { catalogo, fluxo, total, primeira, deslize, operacoesMedidas, ultimaColeta, contas, leituras } = dados;
  const nomes = Object.fromEntries(catalogo.map((c) => [c.id, c.nome]));
  const carteira = filtro ? catalogo.find((c) => c.id === filtro) : null;

  const ultimo = fluxo[0];
  const minutos = ultimo ? Math.round((Date.now() - new Date(ultimo.created_at).getTime()) / 60000) : null;
  // O agendamento do GitHub é melhor-esforço (medido: ~4 h de intervalo
  // médio). Um limiar de 1 h chamaria de parado um sistema saudável.
  const vivo = minutos !== null && minutos < 420;
  const ativas = catalogo.filter((c) => c.ativa_desde).length;

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
            {vivo ? "operando" : minutos === null ? "nenhum ciclo ainda" : `sem ciclo há ${minutos} min`}
          </div>
          <h1 className="mt-3 text-[clamp(2rem,4.5vw,2.9rem)] font-medium leading-[1.05] tracking-[-0.035em]">
            Motor{carteira && <span className="text-vale-tinta-3"> · {carteira.nome}</span>}
          </h1>
          <p className="mt-4 max-w-[60ch] text-[14.5px] leading-relaxed text-vale-tinta-2">
            {carteira
              ? `${carteira.descricao_leiga} Toda hora confere a proteção de 20% abaixo da entrada.`
              : "Seis carteiras decidem a cada ciclo, cada uma pela própria regra. Toda hora conferem a proteção de 20% abaixo da entrada. As IAs só votam no Conselho e explicam as operações."}{" "}
            Execução simulada ao preço real; nenhuma ordem sai para corretora.
          </p>

          <nav className="mt-7 flex flex-wrap gap-1.5" aria-label="Filtrar por carteira">
            <Filtro href="/motor" ativo={!filtro} rotulo="Todas" />
            {IDS.map((id) => (
              <Filtro key={id} href={`/motor?carteira=${id}`} ativo={filtro === id} rotulo={id} titulo={nomes[id]} />
            ))}
          </nav>
        </section>

        <section className="grid grid-cols-2 gap-px border border-vale-fio bg-vale-fio lg:grid-cols-6">
          <Medida
            rotulo="decisões"
            valor={total === null ? "—" : total.toLocaleString("pt-BR")}
            nota={primeira ? `desde ${diaMes(primeira)}` : "nenhuma ainda"}
          />
          {carteira ? (
            <>
              <Medida
                rotulo="carteira"
                valor={carteira.id}
                nota={carteira.ativa_desde ? `ativa desde ${diaMes(carteira.ativa_desde)}` : "aguardando o primeiro ciclo"}
              />
              {PARES.map((par) => {
                const posicionada = contas.some((k) => k.asset === par && k.quantity > 0);
                const r = resumirLeitura(leituras.get(par)?.features, posicionada);
                return (
                  <Medida
                    key={par}
                    rotulo={`${par.replace("USDT", "")} · ${posicionada ? "comprada" : "em caixa"}`}
                    valor={r?.valor ?? "—"}
                    nota={r?.nota ?? "sem leitura ainda"}
                  />
                );
              })}
            </>
          ) : (
            <>
              <Medida rotulo="carteiras" valor={`${ativas} de ${catalogo.length}`} nota="operando" />
              {PARES.map((par) => (
                <Medida
                  key={par}
                  rotulo={par.replace("USDT", "")}
                  valor={`${contas.filter((k) => k.asset === par && k.quantity > 0).length} de ${catalogo.length}`}
                  nota="carteiras compradas"
                />
              ))}
            </>
          )}
          <Medida
            rotulo="deslize vs backtest"
            valor={deslize === null ? "—" : `${deslize >= 0 ? "+" : ""}${deslize.toFixed(2)}%`}
            nota={operacoesMedidas ? `média de ${operacoesMedidas} operações` : "sem operação medida"}
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
          <FluxoDeDecisoes ciclos={fluxo} mostrarCarteira={!filtro} nomes={nomes} />
        </section>
      </main>
    </>
  );
}

function Filtro({ href, ativo, rotulo, titulo }: { href: string; ativo: boolean; rotulo: string; titulo?: string }) {
  return (
    <Link
      href={href}
      title={titulo}
      aria-current={ativo ? "page" : undefined}
      className={`num rounded-sm border px-2.5 py-1 text-[12px] transition-colors ${
        ativo
          ? "border-vale-fio-forte bg-vale-elevado text-vale-tinta"
          : "border-vale-fio text-vale-tinta-3 hover:border-vale-fio-forte hover:text-vale-tinta-2"
      }`}
    >
      {rotulo}
    </Link>
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
