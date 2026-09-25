import type { Leitura, Posicao } from "@/lib/carteira";
import { ENTRA_COM, PRAZOS, SAI_COM, sinal, usd } from "@/lib/carteira";
import type { Resumo } from "@/lib/rotulos";
import { diaMes } from "@/lib/tempo";

/*
 * Um ativo da carteira.
 *
 * Aberto, o cartão responde três perguntas sem o leitor fazer conta:
 * quanto vale, quanto está ganhando ou perdendo, e quão perto está de sair.
 * A terceira é o trilho: a faixa entre o stop e o alvo, com a entrada e o
 * preço de agora marcados nela. Um número de stop solto não diz "estou a
 * 0,4% de ser vendido"; o trilho diz.
 *
 * Fora de posição, o cartão fica curto de propósito: só o preço e o caixa.
 *
 * Desde 22/09 a regra da T1 é de tendência e não tem alvo — a saída é a
 * própria tendência virar. Para ela entra a Força: os seis prazos que a
 * regra consulta, acesos quando o preço está acima da média daquele prazo.
 * É a mesma pergunta ("quão perto estou de sair?") respondida com a régua
 * que decide de verdade.
 *
 * Com seis carteiras, o cartão escolhe a régua de cada uma:
 * - com meta de lucro (G1, G3): o trilho, da proteção até a meta;
 * - Réguas (T1, G1): a Força;
 * - as outras (Tartarugas, Repique, Conselho): a leitura da regra em uma
 *   linha e a distância até a proteção.
 * Fora de posição, G1 e G3 dizem se estão armadas: depois de vender na
 * meta, só recompram quando o sinal recuar e voltar.
 */

export function CartaoDePosicao({ p }: { p: Posicao }) {
  const nome = p.par.replace("USDT", "");

  if (!p.aberta) {
    const desarmada = p.armada === false;
    return (
      <div className="flex items-center justify-between gap-4 bg-vale-superficie px-6 py-5">
        <div className="min-w-0">
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <span className="text-[16px] font-medium tracking-[-0.01em] text-vale-tinta">{nome}</span>
            <span className="text-[12px] text-vale-tinta-3">em caixa</span>
            {p.armada !== null && <Armada armada={p.armada} />}
          </div>
          {desarmada ? (
            <div className="mt-2 text-[11.5px] text-vale-tinta-3">
              vendeu na meta · recompra quando o sinal recuar e voltar
            </div>
          ) : p.tendencia?.votos != null ? (
            <div className="mt-2 flex items-center gap-2.5">
              <Pontos leitura={p.tendencia} />
              <span className="num text-[11.5px] text-vale-tinta-3">
                {p.tendencia.votos} de 6 ·{" "}
                {p.tendencia.podeEntrar === false && p.tendencia.votos >= ENTRA_COM
                  ? "espera um dia fechar depois da última saída"
                  : `entra com ${ENTRA_COM}`}
              </span>
            </div>
          ) : (
            p.resumo && <LinhaDeLeitura resumo={p.resumo} className="mt-2" />
          )}
        </div>
        <div className="shrink-0 text-right">
          <div className="num text-[15px] text-vale-tinta-2">{usd(p.caixa)}</div>
          {p.preco !== null && (
            <div className="num mt-0.5 text-[11.5px] text-vale-tinta-3">
              {nome} a {usd(p.preco)}
            </div>
          )}
        </div>
      </div>
    );
  }

  const ganhando = (p.emAberto ?? 0) >= 0;
  const cor = ganhando ? "text-vale-alta" : "text-vale-baixa";
  const comTrilho = p.stop !== null && p.alvo !== null && p.precoEntrada !== null && p.preco !== null;

  return (
    <div className="bg-vale-superficie px-6 pt-6 pb-7">
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="flex items-baseline gap-3">
            <span className="text-[18px] font-medium tracking-[-0.015em] text-vale-tinta">{nome}</span>
            <span className="num text-[12px] text-vale-tinta-3">
              {p.quantidade.toLocaleString("pt-BR", { maximumFractionDigits: 5 })}
            </span>
          </div>
          {p.abertaEm && (
            <div className="mt-1 text-[12px] text-vale-tinta-3">aberta em {diaMes(p.abertaEm)}</div>
          )}
        </div>
        <div className="text-right">
          <div className="num text-[22px] leading-none tracking-[-0.03em] text-vale-tinta">
            {usd(p.valor)}
          </div>
          {p.emAberto !== null && p.emAbertoPct !== null && (
            <div className={`num mt-1.5 text-[13px] ${cor}`}>
              {sinal(p.emAberto)}
              {usd(Math.abs(p.emAberto))}
              <span className="ml-2">
                {sinal(p.emAbertoPct)}
                {Math.abs(p.emAbertoPct).toFixed(2)}%
              </span>
            </div>
          )}
        </div>
      </div>

      {comTrilho && (
        <Trilho
          stop={p.stop!}
          alvo={p.alvo!}
          entrada={p.precoEntrada!}
          preco={p.preco!}
          rotuloDoAlvo={p.comMeta ? "meta" : "alvo"}
        />
      )}
      {p.tendencia?.votos != null ? (
        <Forca leitura={p.tendencia} />
      ) : (
        p.resumo && <LinhaDeLeitura resumo={p.resumo} className="mt-6" />
      )}
      {!comTrilho && <Protecao stop={p.stop} preco={p.preco} />}
      {p.explicacao && (
        <p className="mt-5 max-w-[60ch] text-[12.5px] leading-relaxed text-vale-tinta-3">{p.explicacao}</p>
      )}
    </div>
  );
}

function Armada({ armada }: { armada: boolean }) {
  return (
    <span
      className={`rounded-sm px-1.5 py-0.5 text-[10px] uppercase tracking-[0.08em] ${
        armada ? "bg-vale-elevado text-vale-tinta-2" : "border border-vale-fio-forte text-vale-tinta-3"
      }`}
      title={
        armada
          ? "pode comprar no próximo sinal de entrada"
          : "vendeu na meta: espera o sinal recuar e voltar antes de comprar de novo"
      }
    >
      {armada ? "armada" : "desarmada"}
    </span>
  );
}

function LinhaDeLeitura({ resumo, className = "" }: { resumo: Resumo; className?: string }) {
  return (
    <div className={`num text-[11.5px] text-vale-tinta-3 ${className}`}>
      <span className="text-vale-tinta-2">{resumo.valor}</span> · {resumo.nota}
    </div>
  );
}

function Trilho({
  stop,
  alvo,
  entrada,
  preco,
  rotuloDoAlvo,
}: {
  stop: number;
  alvo: number;
  entrada: number;
  preco: number;
  rotuloDoAlvo: string;
}) {
  const faixa = alvo - stop;
  const pos = (v: number) => Math.min(100, Math.max(0, ((v - stop) / faixa) * 100));
  const xEntrada = pos(entrada);
  const xPreco = pos(preco);
  const acima = preco >= entrada;
  const distStop = ((preco - stop) / preco) * 100;
  const distAlvo = ((alvo - preco) / preco) * 100;
  const alvoPct = (alvo / entrada - 1) * 100;

  return (
    <div className="mt-7" role="img"
      aria-label={`Preço ${usd(preco)}: ${distStop.toFixed(1)}% acima da proteção de ${usd(stop)} e ${distAlvo.toFixed(1)}% abaixo da ${rotuloDoAlvo} de ${usd(alvo)}.`}>
      <div className="relative h-8">
        {/* rótulo do preço de agora, sobre o marcador */}
        <div
          className={`num absolute -top-0.5 -translate-x-1/2 whitespace-nowrap text-[11.5px] ${acima ? "text-vale-alta" : "text-vale-baixa"}`}
          style={{ left: `clamp(24px, ${xPreco}%, calc(100% - 24px))` }}
        >
          {usd(preco)}
        </div>

        {/* a faixa: perda à esquerda da entrada, ganho à direita */}
        <div className="absolute inset-x-0 bottom-2 h-[3px] overflow-hidden rounded-full bg-vale-elevado">
          <div className="absolute inset-y-0 left-0 bg-vale-baixa/25" style={{ width: `${xEntrada}%` }} />
          <div className="absolute inset-y-0 right-0 bg-vale-alta/25" style={{ width: `${100 - xEntrada}%` }} />
        </div>

        {/* entrada */}
        <div
          className="absolute bottom-0.5 h-[15px] w-px bg-vale-tinta-2"
          style={{ left: `${xEntrada}%` }}
          aria-hidden="true"
        />

        {/* preço de agora */}
        <div
          className={`absolute h-3 w-3 rounded-full ring-[3px] ring-vale-superficie ${acima ? "bg-vale-alta" : "bg-vale-baixa"}`}
          style={{ left: `${xPreco}%`, bottom: "3.5px", transform: "translate(-50%, 50%)" }}
          aria-hidden="true"
        />
      </div>

      <div className="num mt-1.5 grid grid-cols-3 text-[11px] text-vale-tinta-3">
        <span>
          stop <span className="text-vale-tinta-2">{usd(stop)}</span>
        </span>
        <span className="text-center">
          entrada <span className="text-vale-tinta-2">{usd(entrada)}</span>
        </span>
        <span className="text-right">
          {rotuloDoAlvo} <span className="text-vale-tinta-2">{usd(alvo)}</span>
          <span className="ml-1">
            {sinal(alvoPct)}
            {Math.abs(alvoPct).toFixed(1)}%
          </span>
        </span>
      </div>
    </div>
  );
}

function Forca({ leitura }: { leitura: Leitura }) {
  const v = leitura.votos ?? 0;

  return (
    <div className="mt-7">
      <div className="flex items-baseline justify-between gap-4 text-[11.5px]">
        <span className="text-vale-tinta-2">
          tendência <span className="num text-vale-tinta">{v} de 6</span> em alta
        </span>
        <span className="num text-vale-tinta-3">sai com {SAI_COM} ou menos</span>
      </div>

      <div className="mt-2.5 grid grid-cols-6 gap-1" role="img"
        aria-label={`${v} de 6 prazos com o preço acima da média. A posição sai quando restarem ${SAI_COM} ou menos.`}>
        {PRAZOS.map((n, i) => {
          const acima = leitura.prazos[String(n)]?.acima ?? false;
          // a linha de saída: os segmentos até SAI_COM ficam marcados por baixo
          const zonaDeSaida = i < SAI_COM;
          return (
            <div key={n}>
              <div className={`h-[5px] rounded-full ${acima ? "bg-vale-alta" : "bg-vale-elevado"}`} />
              <div className={`num mt-1.5 text-center text-[10.5px] ${zonaDeSaida ? "text-vale-tinta-3" : "text-vale-tinta-3/70"}`}>
                {n}d
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/** Distância até o stop, para as posições sem trilho. */
function Protecao({ stop, preco }: { stop: number | null; preco: number | null }) {
  if (stop === null || preco === null) return null;
  const dist = ((preco - stop) / preco) * 100;
  if (dist >= 0) {
    return (
      <div className="num mt-3 text-[11px] text-vale-tinta-3">
        proteção em <span className="text-vale-tinta-2">{usd(stop)}</span> · {dist.toFixed(1)}% abaixo
      </div>
    );
  }
  // O stop só é conferido em fechamentos de 1h (é o que o estudo mede),
  // então o preço ao vivo pode passar dele antes da venda.
  return (
    <div className="num mt-3 text-[11px] text-vale-baixa">
      preço abaixo da proteção de {usd(stop)} · a venda sai no próximo fechamento de hora abaixo dela
    </div>
  );
}

function Pontos({ leitura }: { leitura: Leitura }) {
  return (
    <span className="flex gap-[3px]" aria-hidden="true">
      {PRAZOS.map((n) => (
        <span key={n}
          className={`h-[5px] w-[5px] rounded-full ${leitura.prazos[String(n)]?.acima ? "bg-vale-alta" : "bg-vale-elevado"}`} />
      ))}
    </span>
  );
}
