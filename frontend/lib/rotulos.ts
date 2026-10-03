/**
 * Português leigo para o que o backend grava em código.
 *
 * Módulo puro — sem Supabase, sem data, sem fuso — para poder ser
 * importado por componente cliente sem arrastar nada do servidor para o
 * navegador. As chaves são exatamente as strings que `backend/live/`
 * grava (PRE_REGISTRO_6_CARTEIRAS.md, seção 2.9).
 */

/** `order_result.motivo` de uma saída → coluna "saída por". */
const MOTIVO_DE_SAIDA: Record<string, string> = {
  // as 6 carteiras
  "stop de catastrofe": "proteção de 20%",
  "stop 2N": "proteção pela oscilação",
  "stop gain": "meta de lucro",
  "tendencia virou": "tendência virou",
  repique: "repique",
  // estratégia anterior da T1 (até 21/09)
  "stop-loss rompido": "stop",
  "alvo atingido": "alvo",
  "tese de saida": "decisão",
  "nivel rompido": "stop",
};

export function motivoDeSaida(motivo: string | null | undefined): string {
  if (!motivo) return "—";
  return MOTIVO_DE_SAIDA[motivo] ?? motivo;
}

/**
 * Por que a carteira NÃO operou, quando o motivo é uma trava da regra e
 * não o sinal em si. Vira uma etiqueta curta no fluxo do Motor.
 */
export function etiquetaDaEspera(motivo: string | null | undefined): string | null {
  if (!motivo) return null;
  const m = motivo.toLowerCase();
  if (m.includes("desarmada")) return "desarmada";
  if (m.includes("travada")) return "travada";
  if (m.includes("painel pendente")) return "painel pendente";
  if (m.includes("sem quorum")) return "sem quórum";
  if (m.includes("historico") && m.includes("insuficiente")) return "sem histórico";
  return null;
}

/** Veredito congelado do Conselho (`painel_veredito.veredito`). */
export const VEREDITO: Record<string, { rotulo: string; tom: "alta" | "baixa" | "neutro" }> = {
  compra: { rotulo: "compra", tom: "alta" },
  venda: { rotulo: "venda", tom: "baixa" },
  neutro: { rotulo: "neutro", tom: "neutro" },
  sem_quorum: { rotulo: "sem quórum", tom: "neutro" },
};

/** Voto de uma IA (`trend_call`). */
export const VOTO: Record<string, { seta: string; rotulo: string }> = {
  UP: { seta: "↑", rotulo: "alta" },
  SIDEWAYS: { seta: "→", rotulo: "de lado" },
  DOWN: { seta: "↓", rotulo: "baixa" },
};

/** As três vagas do Conselho, na ordem do banco. */
export const VAGAS = [
  { id: "G", nome: "Google" },
  { id: "N", nome: "NVIDIA" },
  { id: "C", nome: "lab. chinês" },
] as const;

/* ------------------------------------------------------------ leituras */

export type Resumo = { valor: string; nota: string };

type Features = Record<string, unknown>;

const num = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? v : null);

const pct = (x: number) =>
  `${x > 0 ? "+" : x < 0 ? "−" : ""}${Math.abs(x * 100).toLocaleString("pt-BR", {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  })}%`;

const soma = (s: number | null) => (s === null ? "—" : `${s > 0 ? "+" : s < 0 ? "−" : ""}${Math.abs(s)}`);

type Regra = "reguas" | "painel" | "tartarugas" | "rsi2" | null;

/**
 * Qual regra gravou esta leitura. Pelos CAMPOS, e não só por
 * `features.estrategia`: o valor desse campo mudou entre versões do ciclo,
 * e a G1 grava o mesmo `tendencia_diaria` da T1. Nas carteiras do Conselho
 * `votos` é um objeto {G, N, C} — nunca confundir com os votos das Réguas.
 */
function regraDa(f: Features): Regra {
  const est = typeof f.estrategia === "string" ? f.estrategia : "";
  if (num(f.votos) !== null || est === "tendencia_diaria") return "reguas";
  if ("veredito" in f || "painel_veredito_id" in f || est.startsWith("painel")) return "painel";
  if ("maxima_55d" in f || est.startsWith("tartarugas")) return "tartarugas";
  if ("rsi2" in f || est.startsWith("rsi2")) return "rsi2";
  return null;
}

/**
 * O que a regra viu no último dia fechado, em uma linha: um valor curto e
 * uma nota. Serve ao cartão da página inicial, à página da carteira e ao
 * Motor. `null` quando não há leitura reconhecível.
 */
export function resumirLeitura(f: Features | null | undefined, posicionada = false): Resumo | null {
  if (!f) return null;
  switch (regraDa(f)) {
    case "reguas": {
      const v = num(f.votos);
      if (v === null) return { valor: "—", nota: "histórico insuficiente" };
      return {
        valor: `${v} de 6`,
        nota: posicionada ? "prazos em alta · sai com 2 ou menos" : "prazos em alta · entra com 4",
      };
    }
    case "painel": {
      const v = typeof f.veredito === "string" ? f.veredito : null;
      if (!v) return { valor: "aguardando", nota: "o Conselho ainda não votou o dia" };
      const validos = num(f.validos) ?? 0;
      if (v === "sem_quorum") return { valor: "sem quórum", nota: `${validos} de 3 IAs responderam` };
      return { valor: VEREDITO[v]?.rotulo ?? v, nota: `Conselho: soma ${soma(num(f.soma))} com ${validos} votos` };
    }
    case "tartarugas": {
      const c = num(f.fechamento_diario);
      const max = num(f.maxima_55d);
      const min = num(f.minima_20d);
      if (f.pronta === false || c === null || max === null || min === null)
        return { valor: "—", nota: "histórico insuficiente" };
      if (posicionada) return { valor: pct(c / min - 1), nota: "acima da mínima de 20 dias" };
      if (f.rompeu_alta === true) return { valor: "rompeu", nota: "fechou acima da máxima de 55 dias" };
      return { valor: `faltam ${pct(max / c - 1)}`, nota: "para a máxima de 55 dias" };
    }
    case "rsi2": {
      const r = num(f.rsi2);
      if (f.pronta === false || r === null) return { valor: "—", nota: "histórico insuficiente" };
      const valor = `RSI ${r.toLocaleString("pt-BR", { maximumFractionDigits: 0 })}`;
      if (posicionada) return { valor, nota: "vende no repique acima da média de 5 dias" };
      if (f.em_alta_longa === false) return { valor, nota: "abaixo da média de 200 dias: fica de fora" };
      return { valor, nota: "compra abaixo de 10" };
    }
    default:
      return null;
  }
}

/**
 * O que falta para comprar, em até ~24 caracteres: o lado direito de uma
 * moeda EM CAIXA no cartão da página inicial. Sem isto, uma carteira toda em
 * caixa (a Repique, à espera do RSI) parecia parada, embora decida a cada
 * hora. `pode_entrar === false` é a trava de reentrada ou o rearme da meta.
 */
export function esperaNoCartao(f: Features | null | undefined): string | null {
  if (!f) return null;
  const espera = f.pode_entrar === false;
  const dec1 = (x: number) => x.toLocaleString("pt-BR", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  switch (regraDa(f)) {
    case "reguas": {
      const v = num(f.votos);
      if (v === null) return "sem histórico";
      return espera ? `${v} de 6 · em espera` : `${v} de 6 · compra com 4`;
    }
    case "painel": {
      const v = typeof f.veredito === "string" ? f.veredito : null;
      if (!v) return "aguardando o Conselho";
      if (v === "sem_quorum") return "sem quórum";
      return `Conselho: ${VEREDITO[v]?.rotulo ?? v}${espera ? " · em espera" : ""}`;
    }
    case "tartarugas": {
      const c = num(f.fechamento_diario);
      const max = num(f.maxima_55d);
      if (f.pronta === false || c === null || max === null) return "sem histórico";
      if (espera) return "em espera";
      if (f.rompeu_alta === true) return "rompeu a máxima";
      return `faltam ${dec1(Math.abs(max / c - 1) * 100)}% p/ romper`;
    }
    case "rsi2": {
      const r = num(f.rsi2);
      if (f.pronta === false || r === null) return "sem histórico";
      const rsi = `RSI ${dec1(r)}`;
      if (espera) return `${rsi} · em espera`;
      if (f.em_alta_longa === false) return `${rsi} · sem alta longa`;
      return `${rsi} · compra < 10`;
    }
    default:
      return null;
  }
}

/** A mesma leitura, em poucos caracteres, para a coluna do fluxo do Motor. */
export function leituraCurta(f: Features | null | undefined): { texto: string; titulo: string } | null {
  if (!f) return null;
  switch (regraDa(f)) {
    case "reguas": {
      const v = num(f.votos);
      return { texto: `${v ?? "—"}/6`, titulo: "prazos em alta no último dia fechado" };
    }
    case "painel": {
      const v = typeof f.veredito === "string" ? f.veredito : null;
      if (!v) return { texto: "painel —", titulo: "o Conselho ainda não votou o dia" };
      if (v === "sem_quorum") return { texto: "s/ quórum", titulo: "menos de 2 IAs responderam" };
      return { texto: `${soma(num(f.soma))} ${VEREDITO[v]?.rotulo ?? v}`, titulo: "soma dos votos do Conselho" };
    }
    case "tartarugas": {
      const c = num(f.fechamento_diario);
      const max = num(f.maxima_55d);
      if (c === null || max === null) return { texto: "—", titulo: "histórico insuficiente" };
      return { texto: `${pct(c / max - 1)} máx`, titulo: "distância do fechamento até a máxima de 55 dias" };
    }
    case "rsi2": {
      const r = num(f.rsi2);
      if (r === null) return { texto: "—", titulo: "histórico insuficiente" };
      return {
        texto: `RSI ${r.toLocaleString("pt-BR", { maximumFractionDigits: 0 })}`,
        titulo: f.em_alta_longa === false ? "abaixo da média de 200 dias" : "RSI de 2 dias (compra abaixo de 10)",
      };
    }
    default:
      return null;
  }
}
