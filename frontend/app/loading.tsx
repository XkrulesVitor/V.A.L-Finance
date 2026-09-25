/**
 * As paginas sao Server Components que consultam o Supabase (as carteiras
 * a cada 5 minutos, `revalidate = 300`; o Motor a cada visita). Sem este
 * estado, o navegador fica em branco durante a consulta -- indistinguivel
 * de uma pagina quebrada.
 */
export default function Carregando() {
  return (
    <main className="min-h-screen bg-vale-fundo text-vale-tinta  px-6 py-10">
      <div className="max-w-4xl mx-auto">
        <div className="flex items-center gap-2 mb-6">
          <span className="h-2 w-2 rounded-full bg-vale-tinta-3 animate-pulse" />
          <span className="text-xs uppercase tracking-widest text-vale-tinta-3">carregando</span>
        </div>
        <div className="flex flex-col gap-px bg-vale-fio border border-vale-fio rounded overflow-hidden">
          {[0, 1, 2].map((i) => (
            <div key={i} className="bg-vale-superficie px-4 py-6">
              <div className="h-3 w-24 bg-vale-fio rounded animate-pulse" />
            </div>
          ))}
        </div>
      </div>
    </main>
  );
}
