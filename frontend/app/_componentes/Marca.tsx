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
 * ## Por que a animação é CSS puro e não Motion
 *
 * Duas versões anteriores usaram `motion/react` e as duas quebraram a
 * hidratação em produção (React #418) — inclusive depois de o servidor
 * passar a entregar o estado de repouso. O HTML servido pela Vercel era
 * idêntico, byte a byte, ao do mesmo build rodando local; local hidratava
 * limpo e a Vercel não. Ou seja, o problema não era O QUE o Motion
 * renderizava, era o que ele FAZIA no DOM durante a hidratação.
 *
 * Animação de logo não precisa de biblioteca. Em CSS:
 *
 * - não existe componente cliente: este arquivo é um componente de
 *   servidor, e o SVG chega pronto no HTML;
 * - não há nada mexendo no DOM enquanto o React hidrata, então a classe
 *   inteira de erro deixa de existir;
 * - funciona com JavaScript desligado;
 * - `prefers-reduced-motion` é respeitado pela regra global em
 *   `globals.css`, sem precisar de hook.
 *
 * Os keyframes moram em `globals.css` porque Tailwind v4 não gera
 * animação de `stroke-dashoffset`.
 */

/*
 * O traço. Duas curvas que descem até um vértice macio sobre a linha do
 * stop (y = 22) e sobem de novo.
 *
 * A primeira versão eram duas retas com vértice em quina, e ficava
 * "quadradona". Foram comparadas oito alternativas no tamanho real do
 * cabeçalho (24px) e ampliadas. As curvas que abriam as pontas até quase a
 * horizontal viravam asa ou Y a 24px; a taça funda virava U; a versão com o
 * braço direito mais alto lia como "✓", ambíguo demais num sistema que
 * decide comprar e vender. Esta é a que curva sem deixar de ser V.
 *
 * O fundo arredondado continua tocando o stop: a queda desacelera e para ali,
 * que é o que o sistema faz.
 */
export const TRACO =
  "M5 5 C7.5 12 11 19.5 13.6 21.4 Q15 22.5 16.4 21.4 C19 19.5 22.5 12 27 5";

type Props = {
  tamanho?: number;
  animar?: boolean;
  className?: string;
};

export function Marca({ tamanho = 28, animar = true, className = "" }: Props) {
  // `pathLength="1"` normaliza o comprimento do traço para 0..1, então o
  // keyframe do desenho não precisa saber a geometria real do caminho.
  const anima = animar ? "marca-anima" : "";

  return (
    <svg
      width={tamanho}
      height={tamanho}
      viewBox="0 0 32 32"
      fill="none"
      role="img"
      aria-label="V.A.L Finance"
      className={`${anima} ${className}`}
      style={{ overflow: "visible" }}
    >
      {/* a linha do stop: onde a queda tem que parar */}
      <line
        className="marca-stop"
        x1="3"
        y1="22"
        x2="29"
        y2="22"
        stroke="currentColor"
        strokeWidth="1"
        strokeDasharray="2 2.5"
        opacity="0.38"
      />

      {/* a trajetória: cai até o stop e reverte */}
      <path
        className="marca-traco"
        d={TRACO}
        pathLength="1"
        stroke="currentColor"
        strokeWidth="2.3"
        strokeLinecap="round"
        strokeLinejoin="round"
      />

      {/* o ponto de contato: a única cor da marca, porque é o único
          lugar onde algo aconteceu */}
      <circle
        className="marca-ponto"
        cx="15"
        cy="22"
        r="2.4"
        fill="var(--color-vale-alta)"
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
