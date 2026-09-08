"use client";

import { motion, useReducedMotion } from "motion/react";

/*
 * A marca do V.A.L Finance.
 *
 * O desenho não é abstrato: é o mecanismo do sistema. Uma trajetória de
 * preço cai, e o vértice da queda pousa EXATAMENTE sobre a linha do stop.
 * É a tese inteira do projeto num traço — o que este sistema faz de melhor
 * não é escolher a hora de entrar, é impedir que a queda continue.
 *
 * O "V" que isso forma é o V de V.A.L. A coincidência entre o formato do
 * mecanismo e a inicial do nome é o motivo de a marca ser essa e não outra.
 *
 * A animação conta a mesma história em ordem: o preço traça, o stop entra,
 * e o vértice pisca uma vez no ponto de contato. Roda uma vez na montagem —
 * laço infinito em logo é ruído, não identidade.
 */

type Props = {
  tamanho?: number;
  animar?: boolean;
  className?: string;
};

export function Marca({ tamanho = 28, animar = true, className = "" }: Props) {
  const semMovimento = useReducedMotion();
  const mover = animar && !semMovimento;

  return (
    <svg
      width={tamanho}
      height={tamanho}
      viewBox="0 0 32 32"
      fill="none"
      role="img"
      aria-label="V.A.L Finance"
      className={className}
      style={{ overflow: "visible" }}
    >
      {/* a linha do stop: onde a queda tem que parar */}
      <motion.line
        x1="3"
        y1="22"
        x2="29"
        y2="22"
        stroke="currentColor"
        strokeWidth="1"
        strokeDasharray="2 2.5"
        opacity={0.38}
        initial={mover ? { pathLength: 0, opacity: 0 } : false}
        animate={mover ? { pathLength: 1, opacity: 0.38 } : undefined}
        transition={{ duration: 0.45, delay: 0.5, ease: "easeOut" }}
      />

      {/* a trajetória: cai até o stop e reverte */}
      <motion.path
        d="M5 6 L14.5 22 L27 5"
        stroke="currentColor"
        strokeWidth="2.15"
        strokeLinecap="round"
        strokeLinejoin="round"
        initial={mover ? { pathLength: 0 } : false}
        animate={mover ? { pathLength: 1 } : undefined}
        transition={{ duration: 0.75, ease: [0.65, 0, 0.35, 1] }}
      />

      {/* o ponto de contato: a única cor da marca, porque é o único
          lugar onde algo aconteceu */}
      <motion.circle
        cx="14.5"
        cy="22"
        r="2.4"
        fill="var(--color-vale-alta)"
        initial={mover ? { scale: 0, opacity: 0 } : false}
        animate={
          mover ? { scale: [0, 1.5, 1], opacity: [0, 1, 1] } : undefined
        }
        transition={{ duration: 0.5, delay: 0.72, ease: "easeOut" }}
        style={{ transformOrigin: "14.5px 22px" }}
      />
    </svg>
  );
}

/** Marca + palavra, para o cabeçalho. */
export function Assinatura({ className = "" }: { className?: string }) {
  return (
    <span className={`inline-flex items-center gap-2.5 ${className}`}>
      <Marca tamanho={24} />
      <span className="text-[15px] font-medium tracking-[-0.02em] text-vale-tinta">
        V.A.L
        {/* "Finance" sai no celular: o cabeçalho precisa caber numa linha,
            e a marca sozinha já identifica. */}
        <span className="ml-1.5 hidden font-normal text-vale-tinta-3 sm:inline">
          Finance
        </span>
      </span>
    </span>
  );
}
