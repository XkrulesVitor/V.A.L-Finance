import Link from "next/link";

export default function NaoEncontrado() {
  return (
    <main className="min-h-screen bg-[#0a0e0c] text-[#d8f5df] font-mono px-6 py-10">
      <div className="max-w-2xl mx-auto">
        <div className="text-xs uppercase tracking-widest text-[#3d5c48] mb-4">404</div>
        <h1 className="text-xl mb-6 text-[#eafff0]">Essa página não existe</h1>
        <nav className="flex flex-col gap-2 text-sm">
          <Link href="/" className="text-[#5c9d78] hover:text-[#3ddc84] transition-colors">
            → pipeline e indicadores
          </Link>
          <Link href="/backtests" className="text-[#5c9d78] hover:text-[#3ddc84] transition-colors">
            → backtests e cota
          </Link>
          <Link href="/regimes" className="text-[#5c9d78] hover:text-[#3ddc84] transition-colors">
            → estudo de regimes
          </Link>
        </nav>
      </div>
    </main>
  );
}
