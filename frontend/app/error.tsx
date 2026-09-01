"use client";

/**
 * Erro em runtime. Quase sempre significa Supabase inacessivel ou variavel
 * de ambiente faltando no deploy -- por isso a mensagem diz o que checar em
 * vez de so pedir desculpa. Erro que nao ajuda a consertar e ruido.
 */
export default function Erro({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <main className="min-h-screen bg-[#0a0e0c] text-[#d8f5df] font-mono px-6 py-10">
      <div className="max-w-2xl mx-auto">
        <div className="flex items-center gap-2 mb-4">
          <span className="h-2 w-2 rounded-full bg-[#e07a5f]" />
          <span className="text-xs uppercase tracking-widest text-[#e07a5f]">falhou</span>
        </div>
        <h1 className="text-xl mb-4 text-[#eafff0]">Não consegui carregar os dados</h1>
        <p className="text-sm text-[#5c9d78] mb-6 leading-relaxed">
          Quase sempre é uma destas duas coisas:
        </p>
        <ul className="text-sm text-[#5c9d78] mb-6 flex flex-col gap-2">
          <li className="border border-[#1c2b21] rounded px-4 py-3">
            <span className="text-[#d8f5df]">Variável de ambiente faltando.</span> O deploy precisa
            de <span className="text-[#8fd4a8]">NEXT_PUBLIC_SUPABASE_URL</span> e{" "}
            <span className="text-[#8fd4a8]">NEXT_PUBLIC_SUPABASE_ANON_KEY</span>.
          </li>
          <li className="border border-[#1c2b21] rounded px-4 py-3">
            <span className="text-[#d8f5df]">Supabase fora do ar ou sem permissão.</span> As tabelas
            precisam de <span className="text-[#8fd4a8]">grant select</span> para{" "}
            <span className="text-[#8fd4a8]">anon</span> — está no{" "}
            <span className="text-[#8fd4a8]">supabase/schema.sql</span>.
          </li>
        </ul>
        {error.digest && (
          <p className="text-[10px] text-[#2d4636] mb-4">digest: {error.digest}</p>
        )}
        <button
          onClick={reset}
          className="text-xs border border-[#1e3d2a] text-[#3ddc84] px-3 py-2 rounded hover:bg-[#0e1a13] transition-colors focus:outline-none focus-visible:ring-1 focus-visible:ring-[#3ddc84]"
        >
          tentar de novo
        </button>
      </div>
    </main>
  );
}
