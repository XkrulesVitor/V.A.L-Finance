import { VARIAVEIS } from "@/lib/supabase";

/**
 * Estado exibido quando o build subiu sem as variáveis de ambiente.
 *
 * Não é uma tela de erro — é um diagnóstico. Ela diz exatamente qual
 * variável faltou e, principalmente, o passo que quase todo mundo pula:
 * na Vercel, adicionar uma variável `NEXT_PUBLIC_*` não conserta um deploy
 * que já existe, porque essas variáveis são embutidas durante o build. O
 * painel mostra "Added", o site continua quebrado, e a causa fica
 * invisível até alguém saber disso.
 */
export function ConfiguracaoPendente({ faltando }: { faltando: string[] }) {
  return (
    <main className="min-h-screen bg-[#0a0e0c] text-[#d8f5df] font-mono px-6 py-10">
      <div className="max-w-2xl mx-auto">
        <div className="flex items-center gap-2 mb-4">
          <span className="h-2 w-2 rounded-full bg-[#eda100]" />
          <span className="text-xs uppercase tracking-widest text-[#eda100]">
            falta configurar
          </span>
        </div>

        <h1 className="text-xl mb-2 text-[#eafff0]">V.A.L Finance</h1>
        <p className="text-sm text-[#5c9d78] mb-6 leading-relaxed">
          O site subiu, mas não recebeu as variáveis de ambiente do Supabase.
        </p>

        <div className="border border-[#3d3115] bg-[#181307] rounded p-4 mb-6">
          <div className="text-[10px] uppercase tracking-widest text-[#eda100] mb-3">
            variáveis que não chegaram neste build
          </div>
          <ul className="flex flex-col gap-1.5">
            {faltando.map((v) => (
              <li key={v} className="text-sm text-[#d8f5df] break-all">
                <span className="text-[#e07a5f]">✗</span> {v}
              </li>
            ))}
            {VARIAVEIS.filter((v) => !faltando.includes(v)).map((v) => (
              <li key={v} className="text-sm text-[#3d5c48]">
                <span className="text-[#3ddc84]">✓</span> {v}
              </li>
            ))}
          </ul>
        </div>

        <div className="border border-[#1c2b21] rounded p-4 mb-6">
          <div className="text-[10px] uppercase tracking-widest text-[#3d5c48] mb-3">
            se você já adicionou na Vercel e mesmo assim aparece isto
          </div>
          <p className="text-sm text-[#5c9d78] leading-relaxed mb-3">
            É o caso mais comum, e não é você errando: variáveis{" "}
            <span className="text-[#8fd4a8]">NEXT_PUBLIC_*</span> são embutidas no código{" "}
            <strong className="text-[#d8f5df]">durante o build</strong>. Adicioná-las depois não
            altera um deploy que já foi construído — o painel mostra &ldquo;Added&rdquo; e o site
            continua quebrado.
          </p>
          <p className="text-sm text-[#5c9d78] leading-relaxed">
            Solução: <strong className="text-[#d8f5df]">Deployments → ⋯ → Redeploy</strong>, com{" "}
            <em>Use existing Build Cache</em> desmarcado.
          </p>
        </div>

        <div className="border border-[#1c2b21] rounded p-4">
          <div className="text-[10px] uppercase tracking-widest text-[#3d5c48] mb-3">
            valores esperados
          </div>
          <pre className="text-[11px] text-[#5c9d78] leading-relaxed whitespace-pre-wrap break-all">
{`NEXT_PUBLIC_SUPABASE_URL=https://<projeto>.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=sb_publishable_...`}
          </pre>
          <p className="text-[11px] text-[#3d5c48] mt-3 leading-relaxed">
            A URL precisa começar com <span className="text-[#5c9d78]">https://</span> — colar a
            chave no campo da URL é um erro fácil de cometer e difícil de enxergar. E nunca use aqui
            a chave secreta (<span className="text-[#5c9d78]">sb_secret_</span>): tudo com prefixo{" "}
            <span className="text-[#5c9d78]">NEXT_PUBLIC_</span> vai para o navegador.
          </p>
        </div>
      </div>
    </main>
  );
}
