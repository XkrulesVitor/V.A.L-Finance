"use client";

import { Fragment, useState } from "react";
import { CaretDown, Warning } from "@phosphor-icons/react";
import type { LinhaDoFluxo } from "@/lib/motor";
import { motivoDeSaida } from "@/lib/rotulos";
import { dataHora } from "@/lib/tempo";

/*
 * O fluxo de decisões.
 *
 * Este é o componente que justifica a página existir. Cada linha mostra as
 * duas vozes do sistema lado a lado: o que o cérebro propôs e o que o motor
 * de risco fez. Quando elas divergem, a divergência é o dado mais
 * importante da tela — foi um override do risco que fechou a única
 * operação até agora, contra um HOLD do modelo.
 *
 * Um log que só mostrasse a ação final esconderia exatamente isso.
 *
 * Desde 22/09 a decisão é de uma regra, e a primeira voz passa a ser a
 * leitura dela: quantos dos 6 prazos em alta (Réguas), a distância até a
 * máxima de 55 dias (Tartarugas), o RSI de 2 dias (Repique) ou a soma dos
 * votos do Conselho. O LLM não decide nas regras — quando há operação, a
 * frase dele aparece no detalhe.
 *
 * Com todas as carteiras juntas, cada linha leva a etiqueta da carteira.
 */

const TOM: Record<string, string> = {
  BUY: "text-vale-alta",
  SELL: "text-vale-baixa",
  HOLD: "text-vale-tinta-2",
  NO_TRADE: "text-vale-tinta-3",
};

export function FluxoDeDecisoes({
  ciclos,
  mostrarCarteira = false,
  nomes = {},
}: {
  ciclos: LinhaDoFluxo[];
  mostrarCarteira?: boolean;
  nomes?: Record<string, string>;
}) {
  const [aberto, setAberto] = useState<string | null>(null);

  // O divisor da troca aparece uma vez só: logo acima da linha MAIS RECENTE
  // da estratégia antiga (a lista vem da mais recente para a mais antiga).
  // A era de cada linha vem da data, calculada no servidor — comparar
  // vizinhos punha um divisor falso em cima de qualquer linha sem
  // `features`, como uma reivindicação que ficou órfã.
  const primeiraHibrida = ciclos.findIndex((c) => c.hibrida);
  const indiceDoDivisor = primeiraHibrida > 0 ? primeiraHibrida : -1;

  if (!ciclos.length) {
    return (
      <div className="rounded border border-dashed border-vale-fio px-6 py-10 text-center text-[13.5px] text-vale-tinta-3">
        Nenhuma decisão registrada ainda.
      </div>
    );
  }

  const colunas = mostrarCarteira
    ? "sm:grid-cols-[92px_30px_48px_1fr_auto]"
    : "sm:grid-cols-[92px_66px_1fr_auto]";

  return (
    <div className="border border-vale-fio">
      {ciclos.map((c, i) => {
        const explicacao = c.order_result?.explicacao ?? null;
        const temDetalhe = Boolean(c.llm_output?.reasoning || c.risk_result?.motivo || explicacao);
        const troca = i === indiceDoDivisor;
        const expandido = aberto === c.id;
        const override = c.risk_result?.override_do_llm ?? false;
        const executou = Boolean(c.order_result);
        const resultado = c.order_result?.resultado_pct;
        const saida = c.order_result?.lado === "SELL" ? c.order_result.motivo : null;

        const acao = c.risk_result?.acao_final ?? c.status.toUpperCase();
        // `direcao_do_llm` é o que salva a linha mais importante do fluxo
        // antigo. Numa saída por stop o cérebro nem chega a ser consultado,
        // então `llm_output` é nulo — mas o motor de risco registra contra
        // QUAL tese ele agiu. Sem esse fallback, o override que fechou a
        // operação apareceria como um SELL solitário.
        const tese = c.llm_output?.direction ?? c.risk_result?.direcao_do_llm ?? null;
        const consultou = Boolean(c.llm_output);
        const par = c.symbol.replace("USDT", "");

        return (
          <Fragment key={c.id}>
          {troca && (
            <div className="border-t border-vale-fio bg-vale-fundo px-4 py-2.5 text-[11px] uppercase tracking-[0.1em] text-vale-tinta-3 sm:px-5">
              22/09 · acima, carteiras com regra · abaixo, estratégia híbrida da T1 (LLM decidia)
            </div>
          )}
          <div
            className={`${i > 0 ? "border-t border-vale-fio" : ""} ${
              executou ? "bg-vale-elevado/45" : "bg-vale-superficie"
            }`}
          >
            <button
              type="button"
              onClick={() => temDetalhe && setAberto(expandido ? null : c.id)}
              disabled={!temDetalhe}
              aria-expanded={temDetalhe ? expandido : undefined}
              className={`grid w-full grid-cols-[1fr_auto] items-center gap-x-3 gap-y-1.5 px-4 py-3 text-left ${colunas} sm:gap-x-4 sm:gap-y-2 sm:px-5 ${
                temDetalhe ? "cursor-pointer hover:bg-vale-elevado" : "cursor-default"
              } transition-colors`}
            >
              <span className="num text-[11.5px] whitespace-nowrap text-vale-tinta-3">
                <span className="sm:hidden">
                  {mostrarCarteira ? `${c.carteira} · ` : ""}
                  {par} ·{" "}
                </span>
                {dataHora(c.created_at)}
              </span>

              {mostrarCarteira && (
                <span
                  className="num hidden text-[11.5px] text-vale-tinta-3 sm:block"
                  title={nomes[c.carteira] ?? c.carteira}
                >
                  {c.carteira}
                </span>
              )}

              <span className="num hidden text-[12.5px] text-vale-tinta-2 sm:block">{par}</span>

              {/* as duas vozes */}
              <span className="col-span-2 flex flex-wrap items-center gap-x-2.5 gap-y-1 sm:col-span-1">
                {!c.hibrida ? (
                  <span className="num text-[12.5px] text-vale-tinta-2" title={c.leitura?.titulo}>
                    {c.leitura?.texto ?? "—"}
                  </span>
                ) : tese ? (
                  <span
                    className={`num text-[12.5px] ${
                      override
                        ? "text-vale-tinta-3 line-through decoration-vale-baixa/70"
                        : TOM[tese] ?? "text-vale-tinta-2"
                    }`}
                    title={consultou ? "tese do cérebro" : "última tese vigente"}
                  >
                    {tese}
                  </span>
                ) : (
                  <span
                    className="num text-[12.5px] text-vale-fio-forte"
                    title="fora da cadência: o cérebro não foi consultado"
                  >
                    ——
                  </span>
                )}
                <span className="text-vale-fio-forte">→</span>
                <span className={`num text-[12.5px] font-medium ${TOM[acao] ?? "text-vale-tinta-2"}`}>
                  {acao}
                </span>

                {saida && (
                  <span className="rounded-sm bg-vale-elevado px-1.5 py-0.5 text-[10px] uppercase tracking-[0.08em] text-vale-tinta-2">
                    {motivoDeSaida(saida)}
                  </span>
                )}
                {c.etiqueta && !executou && (
                  <span className="rounded-sm bg-vale-elevado px-1.5 py-0.5 text-[10px] uppercase tracking-[0.08em] text-vale-tinta-3">
                    {c.etiqueta}
                  </span>
                )}
                {override && (
                  <span className="inline-flex items-center gap-1 rounded-sm bg-vale-baixa/12 px-1.5 py-0.5 text-[10px] uppercase tracking-[0.08em] text-vale-baixa">
                    <Warning size={10} weight="fill" />
                    risco sobrepôs
                  </span>
                )}
                {c.risk_result?.aprovado === false && !override && (
                  <span className="rounded-sm bg-vale-elevado px-1.5 py-0.5 text-[10px] uppercase tracking-[0.08em] text-vale-tinta-3">
                    vetado
                  </span>
                )}
              </span>

              <span className="col-start-2 row-start-1 flex items-center justify-end gap-2.5 sm:col-start-auto sm:row-start-auto sm:gap-3">
                {resultado != null && (
                  <span
                    className={`num text-[12.5px] ${resultado >= 0 ? "text-vale-alta" : "text-vale-baixa"}`}
                  >
                    {resultado >= 0 ? "+" : ""}
                    {resultado.toFixed(2)}%
                  </span>
                )}
                <span className="num text-[12.5px] text-vale-tinta-3">
                  {/* Na operação executada, o preço do preenchimento (numa saída
                      por stop/meta, o fechamento que cruzou o nível), e não o
                      ticker da hora do ciclo. */}
                  {(c.order_result?.preco ?? c.preco)?.toLocaleString("pt-BR", { maximumFractionDigits: 2 })}
                </span>
                {temDetalhe && (
                  <CaretDown
                    size={12}
                    weight="bold"
                    className={`text-vale-tinta-3 transition-transform duration-200 ${
                      expandido ? "rotate-180" : ""
                    }`}
                  />
                )}
              </span>
            </button>

            {expandido && (
              <div className="border-t border-vale-fio bg-vale-fundo px-4 py-4 sm:px-5">
                <div className="grid gap-5 sm:grid-cols-2">
                  {c.llm_output && (
                    <div>
                      <div className="text-[10.5px] uppercase tracking-[0.1em] text-vale-tinta-3">
                        tese do cérebro
                      </div>
                      <p className="mt-2 max-w-[58ch] text-[13px] leading-relaxed text-vale-tinta-2">
                        {c.llm_output.reasoning}
                      </p>
                      <div className="num mt-2.5 text-[11.5px] text-vale-tinta-3">
                        horizonte {c.llm_output.horizon} · confiança{" "}
                        {c.llm_output.confidence.toFixed(2)}
                      </div>
                    </div>
                  )}
                  {c.risk_result?.motivo && (
                    <div>
                      <div className="text-[10.5px] uppercase tracking-[0.1em] text-vale-tinta-3">
                        {c.hibrida ? "motor de risco" : "regra"}
                      </div>
                      <p className="mt-2 max-w-[58ch] text-[13px] leading-relaxed text-vale-tinta-2">
                        {c.risk_result.motivo}
                      </p>
                    </div>
                  )}
                  {explicacao && (
                    <div>
                      <div className="text-[10.5px] uppercase tracking-[0.1em] text-vale-tinta-3">
                        em palavras
                      </div>
                      <p className="mt-2 max-w-[58ch] text-[13px] leading-relaxed text-vale-tinta-2">
                        {explicacao}
                      </p>
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
          </Fragment>
        );
      })}
    </div>
  );
}
