/**
 * Consumo da cota diária do LLM.
 *
 * ## Isto é uma estimativa, não o contador do Google
 *
 * A conta é feita somando as chamadas registradas pelas rodadas gravadas em
 * `backtest_runs`. Chamadas feitas fora desses scripts — `validar_ao_vivo.py`,
 * uma rodada com `--sem-supabase`, ou uma rodada que morreu antes de gravar —
 * não aparecem aqui e mesmo assim consumiram cota de verdade.
 *
 * Por isso a estimativa é deliberadamente **conservadora**: rodadas antigas,
 * gravadas antes de o campo `chamadas_reais` existir, entram pelo número total
 * de consultas, que é um teto (inclui os acertos de cache, que não custam
 * nada). Errar para cima num indicador de "estou acabando?" é o erro barato;
 * errar para baixo faz a rodada morrer no meio.
 */

/** Medido na própria mensagem de erro da API: 500/dia por modelo, free tier. */
export const LIMITE_DIARIO = 500;

/**
 * O limite diário do Gemini free tier reseta à meia-noite do **Pacífico**, não
 * do fuso local. Somar "as rodadas de hoje" pelo relógio de Brasília daria a
 * janela errada por 4 a 5 horas — o suficiente para o painel dizer que sobra
 * cota quando ela já virou, ou o contrário.
 */
export function inicioDoDiaDeCota(agora = new Date()): Date {
  const emLA = new Date(agora.toLocaleString("en-US", { timeZone: "America/Los_Angeles" }));
  const deslocamentoMs = agora.getTime() - emLA.getTime();
  const meiaNoiteLA = new Date(emLA);
  meiaNoiteLA.setHours(0, 0, 0, 0);
  return new Date(meiaNoiteLA.getTime() + deslocamentoMs);
}

export type RunDeCota = {
  created_at: string;
  strategy_name: string;
  symbol: string;
  params: {
    chamadas_reais?: number;
    acertos_de_cache?: number;
    modelo?: string;
    auditoria?: { consultas_ao_cerebro?: number };
  } | null;
};

export type UsoDaCota = {
  usadas: number;
  restantes: number;
  pct: number;
  limite: number;
  inicioDaJanela: Date;
  rodadas: { quando: string; rotulo: string; chamadas: number; estimado: boolean }[];
  temEstimativa: boolean;
};

export function calcularUso(runs: RunDeCota[], agora = new Date()): UsoDaCota {
  const inicio = inicioDoDiaDeCota(agora);
  const rodadas: UsoDaCota["rodadas"] = [];
  let usadas = 0;
  let temEstimativa = false;

  for (const r of runs) {
    if (new Date(r.created_at) < inicio) continue;
    const exatas = r.params?.chamadas_reais;
    // Sem o campo exato, o total de consultas é o teto do que pode ter
    // custado. Marcado como estimado para a UI poder dizer isso.
    const estimado = exatas === undefined || exatas === null;
    const chamadas = estimado ? (r.params?.auditoria?.consultas_ao_cerebro ?? 0) : exatas;
    if (chamadas <= 0) continue;
    if (estimado) temEstimativa = true;
    usadas += chamadas;
    rodadas.push({
      quando: r.created_at,
      rotulo: `${r.symbol} · ${r.strategy_name}`,
      chamadas,
      estimado,
    });
  }

  return {
    usadas,
    restantes: Math.max(0, LIMITE_DIARIO - usadas),
    pct: Math.min(100, Math.round((usadas / LIMITE_DIARIO) * 1000) / 10),
    limite: LIMITE_DIARIO,
    inicioDaJanela: inicio,
    rodadas: rodadas.sort((a, b) => b.quando.localeCompare(a.quando)),
    temEstimativa,
  };
}

/** Quantas rodadas de 91 dias (364 consultas) ainda cabem hoje. */
export const CONSULTAS_POR_RODADA = 364;
