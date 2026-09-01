import { CONSULTAS_POR_RODADA, type UsoDaCota } from "@/lib/cota";

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
    ok: { barra: "bg-[#3ddc84]", texto: "text-[#3ddc84]", trilho: "bg-[#16301f]" },
    atencao: { barra: "bg-[#eda100]", texto: "text-[#eda100]", trilho: "bg-[#2e2510]" },
    critico: { barra: "bg-[#e07a5f]", texto: "text-[#e07a5f]", trilho: "bg-[#301a14]" },
  }[faixa];

  const cabem = Math.floor(restantes / CONSULTAS_POR_RODADA);
  const reset = new Date(uso.inicioDaJanela.getTime() + 24 * 3600 * 1000);

  return (
    <section className="border border-[#1c2b21] rounded overflow-hidden mb-10">
      <div className="bg-[#0d1310] px-4 py-4">
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 mb-3">
          <span className="text-[10px] uppercase tracking-widest text-[#3d5c48]">
            cota diária do LLM
          </span>
          <span className="text-[10px] text-[#2d4636]">{modelo ?? "—"}</span>
          <span className={`ml-auto text-lg tabular-nums ${cor.texto}`}>
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
          <span className="text-[#5c9d78]">
            <span className="tabular-nums text-[#d8f5df]">{usadas}</span> de {limite} usadas
          </span>
          <span className="text-[#5c9d78]">
            restam <span className="tabular-nums text-[#d8f5df]">{restantes}</span>
          </span>
          <span className={cabem > 0 ? "text-[#5c9d78]" : "text-[#e07a5f]"}>
            {cabem > 0
              ? `cabe${cabem > 1 ? "m" : ""} ${cabem} rodada${cabem > 1 ? "s" : ""} de 91 dias`
              : "não cabe outra rodada de 91 dias hoje"}
          </span>
        </div>

        {rodadas.length > 0 && (
          <ul className="mt-3 pt-3 border-t border-[#141f18] flex flex-col gap-1">
            {rodadas.map((r) => (
              <li key={r.quando + r.rotulo} className="flex gap-3 text-[10px] text-[#3d5c48]">
                <span className="tabular-nums">
                  {new Date(r.quando).toLocaleTimeString("pt-BR", {
                    hour: "2-digit",
                    minute: "2-digit",
                  })}
                </span>
                <span className="text-[#5c9d78]">{r.rotulo}</span>
                <span className="ml-auto tabular-nums">
                  {r.chamadas}
                  {r.estimado && <span className="text-[#eda100]"> ~</span>}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>

      <p className="bg-[#0a0e0c] px-4 py-2.5 text-[10px] text-[#2d4636] leading-relaxed border-t border-[#141f18]">
        Estimativa a partir das rodadas gravadas — o contador de verdade é do Google e não é
        legível daqui. Chamadas feitas fora dos scripts (ou por rodadas que morreram antes de
        gravar) não aparecem, então trate como piso.
        {temEstimativa && (
          <>
            {" "}
            Linhas com <span className="text-[#eda100]">~</span> vêm de rodadas antigas, anteriores
            ao registro de chamadas reais: entram pelo total de consultas, que é um teto.
          </>
        )}{" "}
        Reseta à meia-noite do Pacífico —{" "}
        {reset.toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })}{" "}
        no seu horário.
      </p>
    </section>
  );
}
