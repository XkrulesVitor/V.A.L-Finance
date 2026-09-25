import type { PontoCurva } from "@/lib/carteira";

/*
 * A curva do cartão: só a forma, sem eixo nem número. O número está logo
 * ao lado, grande; aqui interessa o caminho até ele.
 *
 * Componente de servidor e SVG puro: não há nada para hidratar, então não
 * há como a curva divergir entre servidor e navegador.
 *
 * A cor segue a mesma regra da curva grande — polaridade contra o capital
 * inicial —, e a escala sempre inclui o inicial, para a linha tracejada
 * nunca sair do desenho.
 */

const W = 120;
const H = 36;
const M = 3;

export function MiniCurva({ pontos, inicial }: { pontos: PontoCurva[]; inicial: number }) {
  if (pontos.length < 2) return null;
  const valores = pontos.map((p) => p.equity);
  const min = Math.min(...valores, inicial);
  const max = Math.max(...valores, inicial);
  const faixa = max - min || 1;
  const px = (i: number) => M + (i / (pontos.length - 1)) * (W - 2 * M);
  const py = (v: number) => M + (1 - (v - min) / faixa) * (H - 2 * M);
  const linha = pontos.map((p, i) => `${i ? "L" : "M"}${px(i).toFixed(1)} ${py(p.equity).toFixed(1)}`).join(" ");
  const fim = valores[valores.length - 1];
  const cor = fim >= inicial ? "var(--color-vale-alta)" : "var(--color-vale-baixa)";

  return (
    <svg viewBox={`0 0 ${W} ${H}`} width={W} height={H} className="shrink-0" aria-hidden="true">
      <line
        x1={M}
        x2={W - M}
        y1={py(inicial)}
        y2={py(inicial)}
        stroke="var(--color-vale-fio-forte)"
        strokeWidth="1"
        strokeDasharray="2 3"
      />
      <path d={linha} fill="none" stroke={cor} strokeWidth="1.6" strokeLinejoin="round" strokeLinecap="round" />
      <circle cx={px(pontos.length - 1)} cy={py(fim)} r="2.2" fill={cor} />
    </svg>
  );
}
