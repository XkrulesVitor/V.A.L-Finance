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
    <main className="min-h-screen bg-vale-fundo text-vale-tinta  px-6 py-10">
      <div className="max-w-2xl mx-auto">
        <div className="flex items-center gap-2 mb-4">
          <span className="h-2 w-2 rounded-full bg-vale-baixa" />
          <span className="text-xs uppercase tracking-widest text-vale-baixa">falhou</span>
        </div>
        <h1 className="text-xl mb-4 text-vale-tinta">Não consegui carregar os dados</h1>
        <p className="text-sm text-vale-tinta-2 mb-6 leading-relaxed">
          Quase sempre é uma destas duas coisas:
        </p>
        <ul className="text-sm text-vale-tinta-2 mb-6 flex flex-col gap-2">
          <li className="border border-vale-fio rounded px-4 py-3">
            <span className="text-vale-tinta">Variável de ambiente faltando.</span> O deploy precisa
            de <span className="text-vale-tinta-2">NEXT_PUBLIC_SUPABASE_URL</span> e{" "}
            <span className="text-vale-tinta-2">NEXT_PUBLIC_SUPABASE_ANON_KEY</span>.
          </li>
          <li className="border border-vale-fio rounded px-4 py-3">
            <span className="text-vale-tinta">Supabase fora do ar ou sem permissão.</span> As tabelas
            precisam de <span className="text-vale-tinta-2">grant select</span> para{" "}
            <span className="text-vale-tinta-2">anon</span> — está no{" "}
            <span className="text-vale-tinta-2">supabase/schema.sql</span>.
          </li>
        </ul>
        {error.digest && (
          <p className="text-[10px] text-vale-tinta-3 mb-4">digest: {error.digest}</p>
        )}
        <button
          onClick={reset}
          className="text-xs border border-vale-fio-forte text-vale-alta px-3 py-2 rounded hover:bg-vale-elevado transition-colors focus:outline-none focus-visible:ring-1 focus-visible:ring-vale-alta"
        >
          tentar de novo
        </button>
      </div>
    </main>
  );
}
