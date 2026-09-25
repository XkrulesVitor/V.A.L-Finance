import { Fragment } from "react";
import type { Operacao } from "@/lib/carteira";
import { sinal, usd } from "@/lib/carteira";
import { motivoDeSaida } from "@/lib/rotulos";
import { dataHora } from "@/lib/tempo";

/*
 * Operações fechadas: cada linha é uma ida e volta completa — entrou,
 * saiu, quanto rendeu. É o extrato que interessa ao dono do dinheiro;
 * o log ciclo a ciclo do sistema mora na página Motor.
 *
 * O motivo da saída vem em código ("stop gain", "stop 2N"…) e aparece em
 * português leigo (`lib/rotulos.ts`).
 */

function duracao(ini: string, fim: string) {
  const h = Math.round((new Date(fim).getTime() - new Date(ini).getTime()) / 3_600_000);
  if (h < 48) return `${h} h`;
  return `${Math.round(h / 24)} d`;
}

export function HistoricoDeOperacoes({ operacoes }: { operacoes: Operacao[] }) {
  if (!operacoes.length) {
    return (
      <div className="border border-dashed border-vale-fio px-6 py-10 text-center text-[13.5px] text-vale-tinta-3">
        Nenhuma operação fechada ainda.
      </div>
    );
  }

  return (
    <div className="overflow-x-auto border border-vale-fio">
      <table className="w-full min-w-[640px] border-collapse">
        <thead>
          <tr className="text-[10.5px] uppercase tracking-[0.1em] text-vale-tinta-3">
            <th className="px-5 py-3 text-left font-normal">ativo</th>
            <th className="px-3 py-3 text-left font-normal">entrada → saída</th>
            <th className="px-3 py-3 text-right font-normal">preço</th>
            <th className="px-3 py-3 text-right font-normal">duração</th>
            <th className="px-3 py-3 text-left font-normal">saída por</th>
            <th className="px-5 py-3 text-right font-normal">resultado</th>
          </tr>
        </thead>
        <tbody>
          {operacoes.map((o, i) => {
            const cor = o.resultado >= 0 ? "text-vale-alta" : "text-vale-baixa";
            return (
              <Fragment key={`${o.par}-${o.saidaEm}-${i}`}>
              <tr className="border-t border-vale-fio bg-vale-superficie">
                <td className="px-5 py-3.5 text-[14px] font-medium text-vale-tinta">
                  {o.par.replace("USDT", "")}
                </td>
                <td className="num px-3 py-3.5 text-[12px] text-vale-tinta-3">
                  {dataHora(o.entradaEm)} <span className="text-vale-fio-forte">→</span>{" "}
                  {dataHora(o.saidaEm)}
                </td>
                <td className="num px-3 py-3.5 text-right text-[12.5px] text-vale-tinta-2">
                  {usd(o.precoEntrada)} <span className="text-vale-fio-forte">→</span>{" "}
                  {usd(o.precoSaida)}
                </td>
                <td className="num px-3 py-3.5 text-right text-[12.5px] text-vale-tinta-3">
                  {duracao(o.entradaEm, o.saidaEm)}
                </td>
                <td className="px-3 py-3.5 text-[12.5px] text-vale-tinta-3">
                  {motivoDeSaida(o.motivo)}
                </td>
                <td className={`num px-5 py-3.5 text-right text-[13.5px] ${cor}`}>
                  {sinal(o.resultado)}
                  {usd(Math.abs(o.resultado))}
                  <span className="ml-2.5 text-[12px]">
                    {sinal(o.resultadoPct)}
                    {Math.abs(o.resultadoPct).toFixed(2)}%
                  </span>
                </td>
              </tr>
              {o.explicacao && (
                <tr className="bg-vale-superficie">
                  <td colSpan={6} className="px-5 pb-3.5 pt-0 text-[12.5px] leading-relaxed text-vale-tinta-3">
                    {o.explicacao}
                  </td>
                </tr>
              )}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
