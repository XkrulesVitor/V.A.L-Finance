import Link from "next/link";
import type { CartaoDeCarteira } from "@/lib/carteiras";
import { COM_META } from "@/lib/carteiras";
import { sinal, usd } from "@/lib/carteira";
import { MiniCurva } from "./MiniCurva";

/*
 * Uma estratégia na página inicial: quanto vale, quanto mudou e onde o
 * dinheiro está agora. Sem descrição nem aviso — o dono pediu a tela limpa;
 * o detalhe técnico mora em /carteira/[id] e no Motor.
 */

export function CartaoDaCarteira({ cartao }: { cartao: CartaoDeCarteira }) {
  const { carteira: c, patrimonio, inicial, operou, ativos, curva } = cartao;
  const delta = patrimonio - inicial;
  const deltaPct = (delta / inicial) * 100;
  const cor = !operou || Math.abs(delta) < 0.005 ? "text-vale-tinta-3" : delta > 0 ? "text-vale-alta" : "text-vale-baixa";
  const comMeta = COM_META.has(c.id);

  return (
    <Link
      href={`/carteira/${c.id}`}
      className="group flex flex-col bg-vale-superficie px-6 pt-6 pb-5 transition-colors hover:bg-vale-elevado/40"
    >
      <h3 className="text-[16px] font-medium tracking-[-0.015em] text-vale-tinta">{c.nome}</h3>

      <div className="mt-5 flex items-end justify-between gap-4">
        <div className="min-w-0">
          <div className="num text-[26px] leading-none tracking-[-0.035em] text-vale-tinta">{usd(patrimonio)}</div>
          <div className={`num mt-2 text-[13px] ${cor}`}>
            {operou ? (
              <>
                {sinal(deltaPct)}
                {Math.abs(deltaPct).toFixed(2)}%
                <span className="ml-2 text-[12px] opacity-80">
                  {sinal(delta)}
                  {usd(Math.abs(delta))}
                </span>
              </>
            ) : c.ativa_desde ? (
              "nenhuma compra ainda"
            ) : (
              "começando"
            )}
          </div>
        </div>
        <MiniCurva pontos={curva} inicial={inicial} />
      </div>

      <ul className="mt-5 border-t border-vale-fio">
        {ativos.map((a) => {
          const nome = a.par.replace("USDT", "");
          const corAberto =
            a.emAbertoPct === null || Math.abs(a.emAbertoPct) < 0.005
              ? "text-vale-tinta-2"
              : a.emAbertoPct > 0
                ? "text-vale-alta"
                : "text-vale-baixa";
          return (
            <li key={a.par} className="flex items-center justify-between gap-3 border-b border-vale-fio py-2.5 last:border-b-0">
              <div className="flex items-center gap-2.5">
                <span
                  className={`h-1.5 w-1.5 rounded-full ${a.comprada ? "bg-vale-alta" : "border border-vale-fio-forte"}`}
                  aria-hidden="true"
                />
                <span className="w-9 text-[13px] text-vale-tinta">{nome}</span>
                <span className="text-[12px] text-vale-tinta-3">{a.comprada ? "comprado" : "em caixa"}</span>
              </div>
              <div className="num min-w-0 truncate text-right text-[12px]">
                {!a.comprada && a.espera && <span className="text-vale-tinta-3">{a.espera}</span>}
                {a.comprada && a.emAbertoPct !== null && (
                  <span className={corAberto}>
                    {sinal(a.emAbertoPct)}
                    {Math.abs(a.emAbertoPct).toFixed(2)}%
                  </span>
                )}
                {comMeta && a.comprada && a.metaPct !== null && (
                  <span className="ml-2 text-vale-tinta-3">
                    meta {sinal(a.metaPct)}
                    {Math.abs(a.metaPct).toFixed(1)}%
                  </span>
                )}
              </div>
            </li>
          );
        })}
      </ul>
    </Link>
  );
}
