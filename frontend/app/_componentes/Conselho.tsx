import type { Veredito } from "@/lib/carteiras";
import { VAGAS, VEREDITO, VOTO } from "@/lib/rotulos";
import { diaMes } from "@/lib/tempo";

/*
 * O Conselho de IAs: o último veredito de cada ativo.
 *
 * Três IAs gratuitas de empresas diferentes votam uma vez por dia se a
 * tendência é de alta, de lado ou de baixa. A soma decide: +2 compra, −1
 * ou menos vende, o meio mantém. T3 e G3 leem o MESMO veredito — uma
 * linha de `painel_veredito`, dois usos —, então o bloco é igual nos dois
 * cartões.
 *
 * O que cada IA escreveu (`resumo_pt`) fica recolhido num <details>: é a
 * parte que interessa a quem quer saber o porquê, e texto demais na página
 * inicial esconde os números. Na página da carteira, vem aberto.
 */

const TOM = { alta: "text-vale-alta", baixa: "text-vale-baixa", neutro: "text-vale-tinta-2" } as const;

export function Conselho({
  vereditos,
  pares,
  aberto = false,
}: {
  vereditos: Veredito[];
  pares: string[];
  aberto?: boolean;
}) {
  const dia = vereditos.map((v) => v.dia_utc).sort().at(-1);
  const comFrase = vereditos.some((v) => v.detalhes.some((d) => d.resumo_pt));

  return (
    <div>
      <div className="flex items-baseline justify-between gap-3">
        <span className="text-[10.5px] uppercase tracking-[0.1em] text-vale-tinta-3">Conselho de IAs</span>
        {dia && (
          <span className="num text-[11px] text-vale-tinta-3">dia {diaMes(`${dia.slice(0, 10)}T12:00:00Z`)}</span>
        )}
      </div>

      {!vereditos.length ? (
        <p className="mt-2 text-[12px] text-vale-tinta-3">Sem veredito ainda.</p>
      ) : (
        <ul className="mt-2.5 flex flex-col gap-2">
          {pares.map((par) => {
            const v = vereditos.find((x) => x.simbolo === par);
            const nome = par.replace("USDT", "");
            if (!v) {
              return (
                <li key={par} className="flex items-center gap-3 text-[12px] text-vale-tinta-3">
                  <span className="w-9 text-vale-tinta-2">{nome}</span>sem veredito
                </li>
              );
            }
            const r = VEREDITO[v.veredito] ?? { rotulo: v.veredito, tom: "neutro" as const };
            return (
              <li key={par} className="flex items-center gap-3">
                <span className="w-9 text-[12.5px] text-vale-tinta-2">{nome}</span>
                <span className={`text-[12.5px] font-medium ${TOM[r.tom]}`}>{r.rotulo}</span>
                <span className="num ml-auto flex items-center gap-2.5 text-[11.5px] text-vale-tinta-3">
                  {VAGAS.map((g) => {
                    const voto = v.votos?.[g.id] ?? null;
                    return (
                      <span key={g.id} title={`${g.nome}: ${voto ? VOTO[voto]?.rotulo ?? voto : "sem resposta"}`}>
                        {g.id}
                        <span className={voto ? "ml-0.5 text-vale-tinta-2" : "ml-0.5 text-vale-fio-forte"}>
                          {voto ? (VOTO[voto]?.seta ?? "?") : "·"}
                        </span>
                      </span>
                    );
                  })}
                  <span className="text-vale-tinta-2" title="soma dos votos: +1 alta, 0 de lado, −1 baixa">
                    {v.soma == null ? "—" : `${v.soma > 0 ? "+" : v.soma < 0 ? "−" : ""}${Math.abs(v.soma)}`}
                  </span>
                </span>
              </li>
            );
          })}
        </ul>
      )}

      {comFrase && (
        <details className="group mt-3" open={aberto}>
          <summary className="cursor-pointer list-none text-[11.5px] text-vale-tinta-3 transition-colors hover:text-vale-tinta-2 [&::-webkit-details-marker]:hidden">
            <span className="group-open:hidden">o que cada IA disse +</span>
            <span className="hidden group-open:inline">o que cada IA disse −</span>
          </summary>
          <ul className="mt-2.5 flex flex-col gap-3">
            {pares.flatMap((par) => {
              const v = vereditos.find((x) => x.simbolo === par);
              if (!v) return [];
              return VAGAS.map((g) => {
                const d = v.detalhes.find((x) => x.vaga === g.id);
                if (!d?.resumo_pt) return null;
                const voto = d.trend_call ? VOTO[d.trend_call] : null;
                return (
                  <li key={`${par}-${g.id}`}>
                    <div className="num text-[10.5px] uppercase tracking-[0.08em] text-vale-tinta-3">
                      {par.replace("USDT", "")} · {g.nome}
                      {voto && <span className="ml-1.5 text-vale-tinta-2">{voto.seta} {voto.rotulo}</span>}
                      {d.modelo && <span className="ml-1.5 normal-case tracking-normal">{d.modelo}</span>}
                    </div>
                    <p className="mt-1 text-[12.5px] leading-relaxed text-vale-tinta-2">{d.resumo_pt}</p>
                  </li>
                );
              });
            })}
          </ul>
        </details>
      )}
    </div>
  );
}
