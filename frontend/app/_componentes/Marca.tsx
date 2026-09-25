import type { CSSProperties } from "react";

/*
 * A marca do V.A.L Finance: "VAL" em letras pesadas e arredondadas, com
 * serifas macias (pedido do dono em 25/09, a partir de um esboço dele).
 *
 * As letras são desenhadas à mão, em curvas — não dependem de fonte
 * instalada nem baixada, e o favicon (`app/icon.svg`) reaproveita o V.
 * O A leva a cor da alta; V e L ficam na cor do texto.
 *
 * ## Animação
 *
 * - Entrada: as letras sobem do "chão" (a linha de base), uma depois da
 *   outra, e assentam com um leve achatamento.
 * - Em repouso: a cada 7 s as letras dão um pulinho em onda; o A pula mais
 *   alto.
 * - Passar o mouse no link dispara a onda na hora.
 *
 * É CSS puro, e isso é decisão: duas versões da marca antiga com
 * `motion/react` quebraram a hidratação em produção (React #418). Sem
 * JavaScript no caminho, este é um componente de servidor, o SVG chega
 * pronto no HTML e nada mexe no DOM enquanto o React hidrata. A regra
 * global de `prefers-reduced-motion` em `globals.css` desliga tudo.
 */

// Caixa das letras: x 19–353, y 35–149 (linha de base em ~149).
export const LETRA_V =
  "M30 35 H66 C72 35 76 39 76 44 C76 49 72 52 69 54 L84 99 Q87 106 91 99 L106 60 Q107 54 101 52 C97 51 96 47 97 43 C98 38 101 36 106 36 H133 C139 36 142 40 142 45 C142 49 138 52 133 54 L105 118 C99 133 94 149 80 149 C70 149 66 140 62 133 L31 60 Q30 54 24 53 C20 52 19 47 20 44 C21 38 25 35 30 35 Z";
const LETRA_A =
  "M178 35 H194 C200 35 203 38 206 44 L244 126 C247 133 250 133 254 136 C258 139 256 148 248 148 H207 C199 148 197 139 203 135 C207 132 207 128 206 125 L203 120 C197 117 178 117 172 120 L166 128 C166 133 170 133 174 135 C179 138 178 148 170 148 H138 C131 148 130 139 136 136 C141 133 142 131 143 128 L171 60 C171 50 171 40 178 35 Z " +
  "M186 72 C188 72 190 76 191 80 L198 101 C199 104 197 104 195 104 H178 C176 104 175 103 176 100 L182 79 C183 75 184 72 186 72 Z";
const LETRA_L =
  "M262 35 H305 C311 35 313 39 313 43 C313 48 309 51 303 52 C301 53 301 55 301 58 L301 124 C301 129 305 131 312 131 C322 131 328 124 332 113 C334 108 338 106 343 106 C348 106 352 110 352 117 L350 133 C349 141 346 148 338 148 H264 C258 148 255 143 257 139 C259 135 265 134 268 130 L268 58 C268 54 266 53 261 52 C257 51 255 47 255 43 C255 38 258 35 262 35 Z";

const CAIXA = { x: 18, y: 33, w: 337, h: 118 };

type Props = {
  altura?: number;
  animar?: boolean;
  className?: string;
};

export function Marca({ altura = 22, animar = true, className = "" }: Props) {
  const letras = [
    { d: LETRA_V, cor: "currentColor", salto: 16 },
    { d: LETRA_A, cor: "var(--color-vale-alta)", salto: 26 },
    { d: LETRA_L, cor: "currentColor", salto: 16 },
  ];
  return (
    <svg
      viewBox={`${CAIXA.x} ${CAIXA.y} ${CAIXA.w} ${CAIXA.h}`}
      height={altura}
      width={Math.round((altura * CAIXA.w) / CAIXA.h)}
      role="img"
      aria-label="V.A.L Finance"
      className={`marca ${animar ? "marca-anima" : ""} ${className}`}
      style={{ overflow: "visible" }}
    >
      {/* O "chão": na entrada, as letras sobem de baixo da linha de base. */}
      <clipPath id="marca-chao">
        <rect x="0" y="-200" width="400" height="351" />
      </clipPath>
      <g clipPath="url(#marca-chao)">
        {letras.map((l, i) => (
          <path
            key={i}
            className="marca-letra"
            d={l.d}
            fill={l.cor}
            fillRule="evenodd"
            style={{ "--i": i, "--salto": l.salto } as CSSProperties}
          />
        ))}
      </g>
    </svg>
  );
}

/** Marca + "Finance", para o cabeçalho. */
export function Assinatura({ className = "" }: { className?: string }) {
  return (
    <span className={`inline-flex items-baseline gap-2 text-vale-tinta ${className}`}>
      <Marca altura={21} />
      {/* "Finance" sai no celular: o cabeçalho precisa caber numa linha. */}
      <span className="hidden text-[13px] text-vale-tinta-3 sm:inline">Finance</span>
    </span>
  );
}
