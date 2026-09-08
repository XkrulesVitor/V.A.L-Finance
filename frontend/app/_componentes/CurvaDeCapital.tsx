"use client";

import { useRef, useState } from "react";
import { diaMes, diaMesHora } from "@/lib/tempo";

/*
 * Curva de capital do forward test.
 *
 * Série única (capital total das contas somadas), então não há legenda —
 * o título nomeia a série. A cor não é decorativa: ela codifica polaridade
 * contra o capital inicial, que é o único julgamento que este gráfico faz.
 *
 * A linha de referência no capital inicial é o que dá sentido ao resto.
 * Sem ela o leitor não sabe se a curva subiu ou desceu, só que oscilou.
 */

export type Ponto = { t: string; equity: number };

type Props = {
  pontos: Ponto[];
  inicial: number;
  altura?: number;
};

const L = 8;        // margem esquerda
const R = 66;       // margem direita: espaço pro rótulo do fim
const T = 16;
const B = 26;
const W = 760;

export function CurvaDeCapital({ pontos, inicial, altura = 200 }: Props) {
  const svgRef = useRef<SVGSVGElement>(null);
  const [ativo, setAtivo] = useState<number | null>(null);

  if (pontos.length < 2) {
    return (
      <div
        className="flex items-center justify-center rounded border border-dashed border-vale-fio text-[13px] text-vale-tinta-3"
        style={{ height: altura }}
      >
        A curva aparece a partir do segundo ciclo.
      </div>
    );
  }

  const H = altura;
  const valores = pontos.map((p) => p.equity);
  // A escala SEMPRE inclui o capital inicial. Sem isso a linha de
  // referência poderia cair fora do desenho e o gráfico mentiria por
  // enquadramento.
  const min = Math.min(...valores, inicial);
  const max = Math.max(...valores, inicial);
  const folga = (max - min) * 0.18 || inicial * 0.004;
  const y0 = min - folga;
  const y1 = max + folga;

  const px = (i: number) => L + (i / (pontos.length - 1)) * (W - L - R);
  const py = (v: number) => T + (1 - (v - y0) / (y1 - y0)) * (H - T - B);

  const linha = pontos.map((p, i) => `${i ? "L" : "M"}${px(i)} ${py(p.equity)}`).join(" ");
  const area = `${linha} L${px(pontos.length - 1)} ${H - B} L${px(0)} ${H - B} Z`;

  const fim = pontos[pontos.length - 1].equity;
  const subiu = fim >= inicial;
  const cor = subiu ? "var(--color-vale-alta)" : "var(--color-vale-baixa)";
  const variacao = ((fim / inicial - 1) * 100).toFixed(2);

  const idFill = "curva-preenchimento";

  function aoMover(e: React.PointerEvent<SVGSVGElement>) {
    const el = svgRef.current;
    if (!el) return;
    const caixa = el.getBoundingClientRect();
    const x = ((e.clientX - caixa.left) / caixa.width) * W;
    const bruto = ((x - L) / (W - L - R)) * (pontos.length - 1);
    setAtivo(Math.max(0, Math.min(pontos.length - 1, Math.round(bruto))));
  }

  const p = ativo !== null ? pontos[ativo] : null;

  return (
    <div className="relative">
      <svg
        ref={svgRef}
        viewBox={`0 0 ${W} ${H}`}
        className="w-full touch-none"
        style={{ height: "auto" }}
        onPointerMove={aoMover}
        onPointerLeave={() => setAtivo(null)}
        role="img"
        aria-label={`Curva de capital do forward test: ${variacao}% desde o início, de ${pontos.length} ciclos.`}
      >
        <defs>
          <linearGradient id={idFill} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={cor} stopOpacity="0.10" />
            <stop offset="100%" stopColor={cor} stopOpacity="0" />
          </linearGradient>
        </defs>

        {/* referência: o capital inicial */}
        <line
          x1={L}
          y1={py(inicial)}
          x2={W - R}
          y2={py(inicial)}
          stroke="var(--color-vale-fio-forte)"
          strokeWidth="1"
          strokeDasharray="3 3"
        />
        <text
          x={W - R + 8}
          y={py(inicial) + 3.5}
          fontSize="10.5"
          fill="var(--color-vale-tinta-3)"
          className="num"
        >
          início
        </text>

        <path d={area} fill={`url(#${idFill})`} />
        <path
          d={linha}
          fill="none"
          stroke={cor}
          strokeWidth="2"
          strokeLinejoin="round"
          strokeLinecap="round"
        />

        {/* ponta: onde estamos agora */}
        <circle
          cx={px(pontos.length - 1)}
          cy={py(fim)}
          r="4"
          fill={cor}
          stroke="var(--color-vale-fundo)"
          strokeWidth="2.5"
        />
        <text
          x={W - R + 8}
          y={py(fim) + 3.5}
          fontSize="11.5"
          fill={cor}
          className="num"
          fontWeight="500"
        >
          {subiu ? "+" : ""}
          {variacao}%
        </text>

        {/* crosshair */}
        {ativo !== null && p && (
          <g>
            <line
              x1={px(ativo)}
              y1={T}
              x2={px(ativo)}
              y2={H - B}
              stroke="var(--color-vale-fio-forte)"
              strokeWidth="1"
            />
            <circle
              cx={px(ativo)}
              cy={py(p.equity)}
              r="4.5"
              fill="var(--color-vale-fundo)"
              stroke={cor}
              strokeWidth="2"
            />
          </g>
        )}

        {/* eixo do tempo: só as pontas, o meio é ruído */}
        <text x={L} y={H - 8} fontSize="10.5" fill="var(--color-vale-tinta-3)">
          {diaMes(pontos[0].t)}
        </text>
        <text
          x={W - R}
          y={H - 8}
          fontSize="10.5"
          fill="var(--color-vale-tinta-3)"
          textAnchor="end"
        >
          {diaMes(pontos[pontos.length - 1].t)}
        </text>
      </svg>

      {ativo !== null && p && (
        <div
          className="pointer-events-none absolute top-2 rounded border border-vale-fio-forte bg-vale-elevado px-2.5 py-1.5 shadow-lg"
          style={{
            left: `${(px(ativo) / W) * 100}%`,
            transform:
              px(ativo) > W * 0.6 ? "translateX(-108%)" : "translateX(8%)",
          }}
        >
          <div className="num text-[13px] text-vale-tinta">
            {p.equity.toLocaleString("pt-BR", {
              minimumFractionDigits: 2,
              maximumFractionDigits: 2,
            })}
          </div>
          <div className="text-[10.5px] text-vale-tinta-3">{diaMesHora(p.t)}</div>
        </div>
      )}
    </div>
  );
}
