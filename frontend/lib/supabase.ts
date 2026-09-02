import { createClient } from "@supabase/supabase-js";

/**
 * Conexão de leitura com o Supabase.
 *
 * As variáveis são checadas por nome antes de montar o cliente. Sem isso,
 * `createClient(undefined!, undefined!)` estoura com "Invalid URL" — uma
 * mensagem que não diz qual variável faltou nem onde configurá-la, e que
 * chega na tela como erro genérico. Saber *qual* das duas está ausente é a
 * diferença entre consertar em trinta segundos e ficar chutando.
 *
 * Detalhe da Vercel que causa exatamente este sintoma: variáveis
 * `NEXT_PUBLIC_*` são embutidas no bundle **durante o build**. Adicioná-las
 * no painel depois de um deploy não afeta o deploy que já existe — é
 * preciso reconstruir (Redeploy). O painel mostra a variável como
 * configurada, e mesmo assim o site continua quebrado até o próximo build.
 */

export const VARIAVEIS = [
  "NEXT_PUBLIC_SUPABASE_URL",
  "NEXT_PUBLIC_SUPABASE_ANON_KEY",
] as const;

/** Quais variáveis obrigatórias não chegaram neste build. */
export function variaveisFaltando(): string[] {
  const valores: Record<string, string | undefined> = {
    NEXT_PUBLIC_SUPABASE_URL: process.env.NEXT_PUBLIC_SUPABASE_URL,
    NEXT_PUBLIC_SUPABASE_ANON_KEY: process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY,
  };
  return VARIAVEIS.filter((v) => !valores[v]?.trim());
}

/**
 * Erros de configuração que a interface sabe explicar, separados de falhas
 * de rede ou de permissão — que exigem outra ação.
 */
export class ConfiguracaoAusente extends Error {
  constructor(public faltando: string[]) {
    super(`variáveis ausentes: ${faltando.join(", ")}`);
    this.name = "ConfiguracaoAusente";
  }
}

export function getSupabaseClient() {
  const faltando = variaveisFaltando();
  if (faltando.length) throw new ConfiguracaoAusente(faltando);

  const url = process.env.NEXT_PUBLIC_SUPABASE_URL!;
  if (!/^https?:\/\//.test(url)) {
    // Erro real já cometido neste projeto: colar a chave publicável no
    // campo da URL. O cliente aceita e só falha muito depois, com
    // mensagem que não aponta para a causa.
    throw new ConfiguracaoAusente([
      `NEXT_PUBLIC_SUPABASE_URL não parece uma URL (começa com "${url.slice(0, 12)}…"). ` +
        `Esperado https://<projeto>.supabase.co`,
    ]);
  }

  return createClient(url, process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!);
}

/**
 * Retrato seguro da configuração, para diagnóstico na tela.
 *
 * Mostra host da URL e prefixo+tamanho da chave — nunca o valor. O host de
 * um projeto Supabase é público, e o prefixo só identifica o TIPO de chave.
 * É o mínimo necessário para flagrar os dois erros que este projeto já
 * cometeu: colar a chave no campo da URL, e usar a chave secreta no lugar
 * da pública.
 */
export function impressaoDaConfig() {
  const url = (process.env.NEXT_PUBLIC_SUPABASE_URL ?? "").trim();
  const chave = (process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ?? "").trim();
  const urlOk = /^https?:\/\/[^/]+\.supabase\.(co|in)/.test(url);
  const chaveSecreta = chave.startsWith("sb_secret_") || chave.startsWith("service_role");

  return {
    url: url ? (urlOk ? url : `${url.slice(0, 24)}… (${url.length} chars)`) : "",
    urlOk,
    chave: chave ? `${chave.slice(0, 16)}… (${chave.length} chars)` : "",
    chaveOk: chave.length > 20 && !chaveSecreta,
    chaveSecreta,
  };
}
