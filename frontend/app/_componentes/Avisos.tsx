import { COM_CONSELHO } from "@/lib/carteiras";

/*
 * Os avisos fixos da especificação (PRE_REGISTRO_6_CARTEIRAS.md, 15.2),
 * curtos. Não são enfeite jurídico: cada um corrige uma leitura errada que
 * a tela convida a fazer — achar que dinheiro simulado é dinheiro, que
 * três meses de resultado escolhem uma carteira, ou que acertar mais
 * operações é ganhar mais.
 */

export const AVISO_DA_SORTE =
  "Poucas operações não dizem qual carteira é melhor: antes da primeira leitura, a diferença entre elas é quase toda sorte.";

export const AVISO_DO_ACERTO = "Vender no lucro sobe a taxa de acerto mesmo sem ganhar mais dinheiro.";

export const AVISO_DAS_IAS = "IAs gratuitas: dia sem resposta fica sem decisão.";

/**
 * Os avisos que valem para uma carteira, na página dela. Os que valem para
 * todas (dinheiro simulado, perda máxima, uso pessoal) estão no rodapé.
 */
export function avisosDa(id: string): string[] {
  const saida = [AVISO_DA_SORTE];
  if (id.startsWith("G")) {
    saida.push(
      `${AVISO_DO_ACERTO} Esta carteira existe para medir se vender no lucro compensa, não porque seja recomendado.`
    );
  }
  if (COM_CONSELHO.has(id)) saida.push(AVISO_DAS_IAS);
  return saida;
}

export function Rodape() {
  return (
    <footer className="mt-16 border-t border-vale-fio pt-6 text-[11.5px] leading-relaxed text-vale-tinta-3">
      <p className="max-w-[92ch]">
        Dinheiro simulado ao preço real da Binance; nenhuma ordem vai para corretora. Rentabilidade passada
        não garante rentabilidade futura. Perda máxima por operação ≈ 20% da conta mais o deslize — não
        replicar com dinheiro real sem dimensionar a posição.
      </p>
      <p className="mt-1.5">Uso pessoal. Não é recomendação de investimento.</p>
    </footer>
  );
}
