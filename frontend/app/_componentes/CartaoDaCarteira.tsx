import Link from "next/link";
import { ArrowUpRight } from "@phosphor-icons/react/dist/ssr";
import type { CartaoDeCarteira, Veredito } from "@/lib/carteiras";
import { COM_CONSELHO, COM_META, NOTA_DO_HISTORICO, primeiraLeitura } from "@/lib/carteiras";
import { PARES, sinal, usd } from "@/lib/carteira";
import { dataCurta, diaMes } from "@/lib/tempo";
import { AVISO_DAS_IAS } from "./Avisos";
import { Conselho } from "./Conselho";
import { MiniCurva } from "./MiniCurva";

/*
 * Uma carteira na página inicial.
 *
 * De cima para baixo, a ordem de quem é dono do dinheiro: quanto vale,
 * quanto mudou, desde quando, e onde está aplicado (cada moeda comprada ou
 * em caixa). A parte de cima inteira é o link para a página da carteira; o
 * Conselho fica fora dele porque tem o seu próprio "abrir".
 *
 * Carteira que ainda não rodou mostra os US$ 20.000 iniciais e diz que
 * está esperando o primeiro ciclo — um cartão vazio pareceria defeito.
 */

export function CartaoDaCarteira({
  cartao,
  conselho,
}: {
  cartao: CartaoDeCarteira;
  conselho: Veredito[] | null;
}) {
  const { carteira: c, patrimonio, inicial, operou, ativos, curva } = cartao;
  const delta = patrimonio - inicial;
  const deltaPct = (delta / inicial) * 100;
  const cor = Math.abs(delta) < 0.005 ? "text-vale-tinta-2" : delta > 0 ? "text-vale-alta" : "text-vale-baixa";
  const nota = NOTA_DO_HISTORICO[c.id];
  const comMeta = COM_META.has(c.id);

  const rodape = [
    c.ativa_desde ? `sem leitura até ${dataCurta(primeiraLeitura(c.ativa_desde))}` : null,
    COM_CONSELHO.has(c.id) ? AVISO_DAS_IAS : null,
  ].filter(Boolean);

  return (
    <article className="flex flex-col bg-vale-superficie">
      <Link
        href={`/carteira/${c.id}`}
        className="group block px-6 pt-6 pb-5 transition-colors hover:bg-vale-elevado/40"
      >
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-baseline gap-2.5">
            <span className="num text-[11px] text-vale-tinta-3">{c.id}</span>
            <h3 className="text-[17px] font-medium tracking-[-0.015em] text-vale-tinta">{c.nome}</h3>
          </div>
          <ArrowUpRight
            size={14}
            weight="bold"
            className="text-vale-tinta-3 transition-colors group-hover:text-vale-tinta"
            aria-hidden="true"
          />
        </div>
        {/* altura mínima de 5 linhas: com ela, os números das três carteiras
            da mesma fileira ficam na mesma altura e dá para comparar de olho */}
        <p className="mt-2 text-[12.5px] leading-relaxed text-vale-tinta-3 lg:min-h-[5lh]">{c.descricao_leiga}</p>

        <div className="mt-6 flex items-end justify-between gap-4">
          <div className="min-w-0">
            <div className="num text-[27px] leading-none tracking-[-0.035em] text-vale-tinta">{usd(patrimonio)}</div>
            {operou ? (
              <div className={`num mt-2 text-[13px] ${cor}`}>
                {sinal(delta)}
                {usd(Math.abs(delta))}
                <span className="ml-2.5">
                  {sinal(deltaPct)}
                  {Math.abs(deltaPct).toFixed(2)}%
                </span>
              </div>
            ) : (
              <div className="mt-2 text-[12.5px] text-vale-tinta-3">ainda não operou</div>
            )}
          </div>
          <MiniCurva pontos={curva} inicial={inicial} />
        </div>

        <div className="mt-2 text-[11.5px] leading-relaxed text-vale-tinta-3">
          {c.ativa_desde ? (
            nota ? (
              <>
                regra atual desde {diaMes(c.ativa_desde)} · o resultado {nota}
              </>
            ) : (
              <>desde {diaMes(c.ativa_desde)}</>
            )
          ) : (
            "aguardando o primeiro ciclo"
          )}
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
              <li key={a.par} className="border-b border-vale-fio py-2.5 last:border-b-0">
                <div className="flex items-center justify-between gap-3">
                  <div className="flex items-center gap-2.5">
                    <span
                      className={`h-1.5 w-1.5 rounded-full ${
                        a.comprada ? "bg-vale-tinta-2" : "border border-vale-fio-forte"
                      }`}
                      aria-hidden="true"
                    />
                    <span className="w-9 text-[13px] text-vale-tinta">{nome}</span>
                    <span className="text-[12px] text-vale-tinta-3">{a.comprada ? "comprada" : "em caixa"}</span>
                  </div>
                  <div className="num text-right text-[12px]">
                    {a.comprada && a.emAbertoPct !== null ? (
                      <span className={corAberto} title="resultado da posição aberta">
                        {sinal(a.emAbertoPct)}
                        {Math.abs(a.emAbertoPct).toFixed(2)}%
                      </span>
                    ) : a.leitura ? (
                      <span className="text-vale-tinta-3" title={a.leitura.nota}>
                        {a.leitura.valor}
                      </span>
                    ) : null}
                  </div>
                </div>
                {comMeta && (operou || c.ativa_desde) && (
                  <div className="mt-1 pl-4 text-[11px] text-vale-tinta-3">
                    {a.comprada ? (
                      a.meta !== null ? (
                        <>
                          meta <span className="num text-vale-tinta-2">{usd(a.meta, 0)}</span>
                          {a.metaPct !== null && (
                            <span className="num ml-1.5">
                              {sinal(a.metaPct)}
                              {Math.abs(a.metaPct).toFixed(1)}%
                            </span>
                          )}
                        </>
                      ) : (
                        "sem meta registrada"
                      )
                    ) : a.armada === false ? (
                      <span title="vendeu na meta: só compra de novo quando o sinal recuar e voltar">
                        desarmada · espera o sinal recuar e voltar
                      </span>
                    ) : (
                      <span title="pode comprar no próximo sinal de entrada">armada</span>
                    )}
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      </Link>

      {conselho && (
        <div className="border-t border-vale-fio px-6 py-4">
          <Conselho vereditos={conselho} pares={PARES} />
        </div>
      )}

      {rodape.length > 0 && (
        <p className="mt-auto border-t border-vale-fio px-6 py-3 text-[11px] leading-relaxed text-vale-tinta-3">
          {rodape.join(" · ")}
        </p>
      )}
    </article>
  );
}
