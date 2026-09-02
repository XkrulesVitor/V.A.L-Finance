import { VARIAVEIS, impressaoDaConfig } from "@/lib/supabase";

/**
 * Tela de diagnóstico — mostrada quando a leitura do Supabase falha.
 *
 * A versão anterior listava as duas causas possíveis e deixava a pessoa
 * adivinhar qual era. Isso é pouco: o servidor SABE o que aconteceu, e não
 * dizer é escolher esconder.
 *
 * Aqui aparece a mensagem real do erro e uma "impressão digital" da
 * configuração: host da URL, prefixo e tamanho da chave. Nada disso é
 * segredo — o host é público e o prefixo já identifica o tipo de chave —
 * mas é exatamente o que revela os dois erros que este projeto já cometeu:
 * colar a chave publicável no campo da URL, e usar a chave errada.
 */
export function Diagnostico({
  faltando,
  erro,
}: {
  faltando?: string[];
  erro?: string;
}) {
  const config = impressaoDaConfig();
  const semVariaveis = (faltando?.length ?? 0) > 0;

  return (
    <main className="min-h-screen bg-[#0a0e0c] text-[#d8f5df] font-mono px-6 py-10">
      <div className="max-w-2xl mx-auto">
        <div className="flex items-center gap-2 mb-4">
          <span className="h-2 w-2 rounded-full bg-[#eda100]" />
          <span className="text-xs uppercase tracking-widest text-[#eda100]">
            {semVariaveis ? "falta configurar" : "não consegui ler o banco"}
          </span>
        </div>

        <h1 className="text-xl mb-2 text-[#eafff0]">V.A.L Finance</h1>
        <p className="text-sm text-[#5c9d78] mb-6 leading-relaxed">
          {semVariaveis
            ? "O site subiu, mas não recebeu as variáveis de ambiente do Supabase."
            : "As variáveis chegaram, mas a consulta ao Supabase falhou."}
        </p>

        {/* o que o servidor viu */}
        <div className="border border-[#1c2b21] rounded p-4 mb-6">
          <div className="text-[10px] uppercase tracking-widest text-[#3d5c48] mb-3">
            o que este build recebeu
          </div>
          <dl className="flex flex-col gap-2 text-sm">
            <div className="flex flex-wrap gap-x-3">
              <dt className="text-[#3d5c48] w-40 shrink-0">URL</dt>
              <dd className={config.urlOk ? "text-[#d8f5df]" : "text-[#e07a5f]"}>
                {config.url || "— ausente —"}
                {!config.urlOk && config.url && (
                  <span className="block text-[11px] text-[#e07a5f] mt-1">
                    não parece uma URL. Esperado https://&lt;projeto&gt;.supabase.co
                  </span>
                )}
              </dd>
            </div>
            <div className="flex flex-wrap gap-x-3">
              <dt className="text-[#3d5c48] w-40 shrink-0">chave pública</dt>
              <dd className={config.chaveOk ? "text-[#d8f5df]" : "text-[#e07a5f]"}>
                {config.chave || "— ausente —"}
                {config.chaveSecreta && (
                  <span className="block text-[11px] text-[#e07a5f] mt-1">
                    isto é uma chave SECRETA. Nunca use em NEXT_PUBLIC_ — ela ignora RLS e vai
                    para o navegador. Troque pela publicável e rotacione esta.
                  </span>
                )}
              </dd>
            </div>
          </dl>
        </div>

        {erro && (
          <div className="border border-[#3d1a14] bg-[#1a0d0a] rounded p-4 mb-6">
            <div className="text-[10px] uppercase tracking-widest text-[#e07a5f] mb-2">
              erro retornado
            </div>
            <p className="text-[12px] text-[#d8f5df] leading-relaxed break-words">{erro}</p>
          </div>
        )}

        {semVariaveis && (
          <div className="border border-[#3d3115] bg-[#181307] rounded p-4 mb-6">
            <div className="text-[10px] uppercase tracking-widest text-[#eda100] mb-3">
              já adicionou na Vercel e mesmo assim aparece isto?
            </div>
            <p className="text-sm text-[#5c9d78] leading-relaxed">
              Variáveis <span className="text-[#8fd4a8]">NEXT_PUBLIC_*</span> são embutidas no
              código <strong className="text-[#d8f5df]">durante o build</strong>. Adicioná-las
              depois não altera um deploy pronto. Solução:{" "}
              <strong className="text-[#d8f5df]">Deployments → ⋯ → Redeploy</strong>, com{" "}
              <em>Use existing Build Cache</em> desmarcado.
            </p>
            <ul className="mt-3 flex flex-col gap-1">
              {VARIAVEIS.map((v) => (
                <li key={v} className="text-[12px] break-all">
                  <span className={faltando?.includes(v) ? "text-[#e07a5f]" : "text-[#3ddc84]"}>
                    {faltando?.includes(v) ? "✗" : "✓"}
                  </span>{" "}
                  <span className="text-[#5c9d78]">{v}</span>
                </li>
              ))}
            </ul>
          </div>
        )}

        {!semVariaveis && (
          <div className="border border-[#1c2b21] rounded p-4">
            <div className="text-[10px] uppercase tracking-widest text-[#3d5c48] mb-3">
              o que checar, em ordem
            </div>
            <ol className="flex flex-col gap-2 text-sm text-[#5c9d78] leading-relaxed">
              <li>
                <span className="text-[#d8f5df]">1.</span> A URL acima é mesmo a do seu projeto
                Supabase? Um valor colado no campo errado é o erro mais comum.
              </li>
              <li>
                <span className="text-[#d8f5df]">2.</span> A chave pública é a{" "}
                <span className="text-[#8fd4a8]">sb_publishable_…</span> (ou a{" "}
                <span className="text-[#8fd4a8]">anon</span> antiga) do{" "}
                <em>mesmo</em> projeto?
              </li>
              <li>
                <span className="text-[#d8f5df]">3.</span> As tabelas têm{" "}
                <span className="text-[#8fd4a8]">grant select</span> para{" "}
                <span className="text-[#8fd4a8]">anon</span>? Rode o{" "}
                <span className="text-[#8fd4a8]">supabase/schema.sql</span> inteiro — ele é
                idempotente.
              </li>
            </ol>
          </div>
        )}
      </div>
    </main>
  );
}
