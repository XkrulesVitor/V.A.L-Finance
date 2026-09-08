import { CONSULTAS_POR_RODADA, type UsoDaCota } from "@/lib/cota";
import { dataHora, hora } from "@/lib/tempo";

/**
 * Barra de consumo da cota diária do LLM.
 *
 * 100% = no limite. A cor muda por faixa porque um número sozinho não avisa
 * — quem olha de relance precisa ver "dá pra rodar" ou "não dá" sem ler.
 */
export function CotaDiaria({ uso, modelo }: { uso: UsoDaCota; modelo: string | null }) {
  const { usadas, restantes, pct, limite, rodadas, temEstimativa } = uso;

  const faixa =
    pct >= 90 ? "critico" : pct >= 65 ? "atencao" : ("ok" as "ok" | "atencao" | "critico");

  const cor = {
    ok: {
      barra: "bg-vale-alta",
      texto: "text-vale-alta",
      trilho: "bg-vale-elevado",
    },
    atencao: {
      barra: "bg-vale-tinta-2",
      texto: "text-vale-tinta",
      trilho: "bg-vale-elevado",
    },
    critico: {
      barra: "bg-vale-baixa",
      texto: "text-vale-baixa",
      trilho: "bg-vale-elevado",
    },
  }[faixa];

  const cabem = Math.floor(restantes / CONSULTAS_POR_RODADA);
  const reset = new Date(uso.inicioDaJanela.getTime() + 24 * 3600 * 1000);

  return (
    <section className="border border-vale-fio rounded overflow-hidden mb-10">
      <div className="bg-vale-superficie px-4 py-4">
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 mb-3">
          <span className="text-[10px] uppercase tracking-widest text-vale-tinta-3">
            cota diária do LLM
          </span>
          <span className="text-[10px] text-vale-tinta-3">{modelo ?? "—"}</span>
          <span className={`ml-auto text-lg num ${cor.texto}`}>
            {pct.toFixed(1)}%
          </span>
        </div>

        {/* barra */}
        <div
          className={`h-2 w-full rounded-sm overflow-hidden ${cor.trilho}`}
          role="meter"
          aria-valuenow={usadas}
          aria-valuemin={0}
          aria-valuemax={limite}
          aria-label={`${usadas} de ${limite} chamadas usadas hoje`}
        >
          <div
            className={`h-full ${cor.barra} transition-[width]`}
            style={{ width: `${Math.max(pct, usadas > 0 ? 1.5 : 0)}%` }}
          />
        </div>

        <div className="flex flex-wrap gap-x-6 gap-y-1 mt-3 text-xs">
          <span className="text-vale-tinta-2">
            <span className="num text-vale-tinta">{usadas}</span> de {limite} usadas
          </span>
          <span className="text-vale-tinta-2">
            restam <span className="num text-vale-tinta">{restantes}</span>
          </span>
          <span className={cabem > 0 ? "text-vale-tinta-2" : "text-vale-baixa"}>
            {cabem > 0
              ? `cabe${cabem > 1 ? "m" : ""} ${cabem} rodada${cabem > 1 ? "s" : ""} de 91 dias`
              : "não cabe outra rodada de 91 dias hoje"}
          </span>
        </div>

        {rodadas.length > 0 && (
          <ul className="mt-3 pt-3 border-t border-vale-fio flex flex-col gap-1">
            {rodadas.map((r) => (
              <li key={r.quando + r.rotulo} className="flex gap-3 text-[10px] text-vale-tinta-3">
                <span className="num">
                  {hora(r.quando)}
                </span>
                <span className="text-vale-tinta-2">{r.rotulo}</span>
                <span className="ml-auto num">
                  {r.chamadas}
                  {r.estimado && <span className="text-vale-tinta-2"> ~</span>}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>

      <p className="bg-vale-fundo px-4 py-2.5 text-[10px] text-vale-tinta-3 leading-relaxed border-t border-vale-fio">
        Estimativa a partir das rodadas gravadas — o contador de verdade é do Google e não é
        legível daqui. Chamadas feitas fora dos scripts (ou por rodadas que morreram antes de
        gravar) não aparecem, então trate como piso.
        {temEstimativa && (
          <>
            {" "}
            Linhas com <span className="text-vale-tinta-2">~</span> vêm de rodadas antigas, anteriores
            ao registro de chamadas reais: entram pelo total de consultas, que é um teto.
          </>
        )}{" "}
        Reseta à meia-noite do Pacífico —{" "}
        {dataHora(reset)}{" "}
        no seu horário.
      </p>
    </section>
  );
}
