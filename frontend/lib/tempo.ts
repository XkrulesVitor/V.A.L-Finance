/**
 * Formatação de data e hora com fuso FIXO.
 *
 * Sem isto o site quebra em produção. O servidor da Vercel roda em UTC e o
 * navegador do leitor roda em São Paulo, então `toLocaleString` sem
 * `timeZone` produz textos diferentes nos dois lados — e o React acusa
 * erro de hidratação (#418) porque o HTML que ele recebeu não bate com o
 * que ele mesmo renderizaria.
 *
 * O fuso é fixo em São Paulo de propósito, e não "o do leitor": este é um
 * painel de operação de um sistema que decide em horário de Brasília. Um
 * horário que muda conforme quem abre a página tornaria impossível
 * comparar o que se vê aqui com o log do backend.
 */

export const FUSO = "America/Sao_Paulo";

const comFuso = (o: Intl.DateTimeFormatOptions) => ({ ...o, timeZone: FUSO });

/** 08/09, 14:35 */
export function dataHora(iso: string | Date) {
  return new Date(iso).toLocaleString(
    "pt-BR",
    comFuso({ day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })
  );
}

/** 08 de set. */
export function diaMes(iso: string | Date) {
  return new Date(iso).toLocaleDateString(
    "pt-BR",
    comFuso({ day: "2-digit", month: "short" })
  );
}

/** 08 de setembro de 2026 */
export function dataLonga(iso: string | Date) {
  return new Date(iso).toLocaleDateString(
    "pt-BR",
    comFuso({ day: "2-digit", month: "long", year: "numeric" })
  );
}

/** 08/09/2026 */
export function dataCurta(iso: string | Date) {
  return new Date(iso).toLocaleDateString("pt-BR", comFuso({}));
}

/** 14:35 */
export function hora(iso: string | Date) {
  return new Date(iso).toLocaleTimeString(
    "pt-BR",
    comFuso({ hour: "2-digit", minute: "2-digit" })
  );
}

/** 08 de set., 14:35 */
export function diaMesHora(iso: string | Date) {
  return new Date(iso).toLocaleString(
    "pt-BR",
    comFuso({ day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" })
  );
}
