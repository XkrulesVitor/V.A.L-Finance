import type { Posicao } from "@/lib/carteira";
import { sinal, usd } from "@/lib/carteira";
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
 */

export function CartaoDePosicao({ p }: { p: Posicao }) {
  const nome = p.par.replace("USDT", "");

  if (!p.aberta) {
    return (
      <div className="flex items-center justify-between gap-4 bg-vale-superficie px-6 py-5">
        <div className="flex items-baseline gap-3">
          <span className="text-[16px] font-medium tracking-[-0.01em] text-vale-tinta">{nome}</span>
          <span className="text-[12px] text-vale-tinta-3">em caixa</span>
        </div>
        <div className="text-right">
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

      {p.stop !== null && p.alvo !== null && p.precoEntrada !== null && p.preco !== null && (
        <Trilho stop={p.stop} alvo={p.alvo} entrada={p.precoEntrada} preco={p.preco} />
      )}
    </div>
  );
}

function Trilho({
  stop,
  alvo,
  entrada,
  preco,
}: {
  stop: number;
  alvo: number;
  entrada: number;
  preco: number;
}) {
  const faixa = alvo - stop;
  const pos = (v: number) => Math.min(100, Math.max(0, ((v - stop) / faixa) * 100));
  const xEntrada = pos(entrada);
  const xPreco = pos(preco);
  const acima = preco >= entrada;
  const distStop = ((preco - stop) / preco) * 100;
  const distAlvo = ((alvo - preco) / preco) * 100;

  return (
    <div className="mt-7" role="img"
      aria-label={`Preço ${usd(preco)}: ${distStop.toFixed(1)}% acima do stop de ${usd(stop)} e ${distAlvo.toFixed(1)}% abaixo do alvo de ${usd(alvo)}.`}>
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
          alvo <span className="text-vale-tinta-2">{usd(alvo)}</span>
        </span>
      </div>
    </div>
  );
}
