import Link from "next/link";

export default function NaoEncontrado() {
  return (
    <main className="min-h-screen bg-vale-fundo text-vale-tinta  px-6 py-10">
      <div className="max-w-2xl mx-auto">
        <div className="text-xs uppercase tracking-widest text-vale-tinta-3 mb-4">404</div>
        <h1 className="text-xl mb-6 text-vale-tinta">Essa página não existe</h1>
        <nav className="flex flex-col gap-2 text-sm">
          <Link href="/" className="text-vale-tinta-2 hover:text-vale-alta transition-colors">
            → as seis carteiras
          </Link>
          <Link href="/motor" className="text-vale-tinta-2 hover:text-vale-alta transition-colors">
            → motor: as decisões, ciclo a ciclo
          </Link>
          <Link href="/backtests" className="text-vale-tinta-2 hover:text-vale-alta transition-colors">
            → backtests e cota
          </Link>
          <Link href="/regimes" className="text-vale-tinta-2 hover:text-vale-alta transition-colors">
            → estudo de regimes
          </Link>
        </nav>
      </div>
    </main>
  );
}
