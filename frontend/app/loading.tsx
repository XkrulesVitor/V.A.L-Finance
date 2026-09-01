/**
 * As paginas sao Server Components que consultam o Supabase a cada request
 * (revalidate = 0). Sem este estado, o navegador fica em branco durante a
 * consulta -- indistinguivel de uma pagina quebrada.
 */
export default function Carregando() {
  return (
    <main className="min-h-screen bg-[#0a0e0c] text-[#d8f5df] font-mono px-6 py-10">
      <div className="max-w-4xl mx-auto">
        <div className="flex items-center gap-2 mb-6">
          <span className="h-2 w-2 rounded-full bg-[#3d5c48] animate-pulse" />
          <span className="text-xs uppercase tracking-widest text-[#3d5c48]">carregando</span>
        </div>
        <div className="flex flex-col gap-px bg-[#1c2b21] border border-[#1c2b21] rounded overflow-hidden">
          {[0, 1, 2].map((i) => (
            <div key={i} className="bg-[#0d1310] px-4 py-6">
              <div className="h-3 w-24 bg-[#141f18] rounded animate-pulse" />
            </div>
          ))}
        </div>
      </div>
    </main>
  );
}
