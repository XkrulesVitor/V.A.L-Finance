"use client";

import { useEffect, useState } from "react";
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
 *
 * ## Por que a animação só começa depois de montar
 *
 * A primeira versão usava `initial={{ pathLength: 0 }}`, e isso quebrou a
 * produção com erro de hidratação (React #418). O motivo aparece no HTML
 * que o servidor mandava:
 *
 *     <path ... stroke-dasharray="0 1" stroke-dashoffset="0">
 *     <circle ... style="transform:scale(0);opacity:0">
 *
 * Ou seja, o servidor entregava o QUADRO INICIAL da animação. O navegador
 * hidratava já animando, encontrava outros valores nos mesmos atributos, e
 * o React recusava a árvore.
 *
 * A correção é renderizar o estado de REPOUSO nos dois lados — servidor e
 * primeira renderização do cliente são idênticos — e só então disparar a
 * animação. Como efeito colateral bom, quem tem JavaScript desligado vê a
 * marca inteira em vez de um SVG invisível.
 */

type Props = {
  tamanho?: number;
  animar?: boolean;
  className?: string;
};

export function Marca({ tamanho = 28, animar = true, className = "" }: Props) {
  const semMovimento = useReducedMotion();
  const [montado, setMontado] = useState(false);

  useEffect(() => setMontado(true), []);

  const mover = animar && !semMovimento && montado;

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
        initial={false}
        animate={
          mover
            ? { pathLength: [0, 1], opacity: [0, 0.38] }
            : { pathLength: 1, opacity: 0.38 }
        }
        transition={{ duration: 0.45, delay: 0.5, ease: "easeOut" }}
      />

      {/* a trajetória: cai até o stop e reverte */}
      <motion.path
        d="M5 6 L14.5 22 L27 5"
        stroke="currentColor"
        strokeWidth="2.15"
        strokeLinecap="round"
        strokeLinejoin="round"
        initial={false}
        animate={mover ? { pathLength: [0, 1] } : { pathLength: 1 }}
        transition={{ duration: 0.75, ease: [0.65, 0, 0.35, 1] }}
      />

      {/* o ponto de contato: a única cor da marca, porque é o único
          lugar onde algo aconteceu. O Motion ancora a escala no centro do
          próprio círculo (`transform-box: fill-box`), então não há origem
          para declarar aqui — declarar criava conflito com o que ele já
          escreve no style. */}
      <motion.circle
        cx="14.5"
        cy="22"
        r="2.4"
        fill="var(--color-vale-alta)"
        initial={false}
        animate={
          mover ? { scale: [0, 1.5, 1], opacity: [0, 1, 1] } : { scale: 1, opacity: 1 }
        }
        transition={{ duration: 0.5, delay: 0.72, ease: "easeOut" }}
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
