import Link from "next/link";
import { Assinatura } from "./Marca";

/*
 * Cabeçalho. Uma linha, 64px, três destinos.
 *
 * Os slugs não mudaram na remodelagem — memória muscular e link salvo
 * valem mais que consistência de nomenclatura.
 */

const DESTINOS = [
  { href: "/", rotulo: "Operação" },
  { href: "/backtests", rotulo: "Evidência" },
  { href: "/regimes", rotulo: "Regimes" },
];

export function Cabecalho({ atual }: { atual: string }) {
  return (
    <header className="sticky top-0 z-50 h-16 border-b border-vale-fio bg-vale-fundo/85 backdrop-blur-xl">
      <div className="mx-auto flex h-full max-w-[1240px] items-center justify-between gap-4 px-4 sm:px-8">
        <Link href="/" className="transition-opacity hover:opacity-70">
          <Assinatura />
        </Link>

        <nav className="-mr-2 flex items-center">
          {DESTINOS.map((d) => {
            const ativo = d.href === atual;
            return (
              <Link
                key={d.href}
                href={d.href}
                aria-current={ativo ? "page" : undefined}
                className={`rounded px-2.5 py-1.5 text-[12.5px] whitespace-nowrap transition-colors sm:px-3 sm:text-[13px] ${
                  ativo
                    ? "text-vale-tinta"
                    : "text-vale-tinta-3 hover:text-vale-tinta-2"
                }`}
              >
                {d.rotulo}
              </Link>
            );
          })}
        </nav>
      </div>
    </header>
  );
}
