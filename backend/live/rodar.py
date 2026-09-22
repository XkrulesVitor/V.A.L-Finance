"""
Ponto de entrada do forward test -- passo 8a.

    python backend/live/rodar.py                 # todos os pares
    python backend/live/rodar.py --pares BTCUSDT
    python backend/live/rodar.py --ensaio        # nao grava nada
    python backend/live/rodar.py --estrategia hibrida   # o motor antigo

Roda um ciclo por par: le o estado do banco, confere o stop, decide,
preenche a ordem de forma simulada ao preco real e grava tudo de volta.

## Duas estrategias, uma de cada vez

- `tendencia` (padrao desde 2026-09-22): a regra deterministica de
  `estrategia/tendencia_diaria.py`. O LLM so escreve a explicacao de cada
  operacao, depois dela gravada. Ver `live/ciclo_tendencia.py`.
- `hibrida`: o motor de 2026-09-04 a 2026-09-21 (LLM gera a tese, Risk
  Engine decide). Fica acessivel porque o historico gravado nesse periodo
  saiu dele.

As duas escrevem nas mesmas contas. Rodar as duas no mesmo agendamento
seria duas estrategias disputando o mesmo caixa -- por isso e uma OU outra.

## O que este processo NAO faz

Nao envia ordem pra corretora nenhuma. O preenchimento e nosso, ao preco
real de mercado -- e isso e deliberado, nao uma limitacao. Ver
`live/estado.py` para o motivo completo; em resumo, com ordem de verdade
existiriam dois sistemas e uma janela entre eles, e aqui a execucao e a
escrituracao sao a mesma escrita.

## Um par quebrado nao derruba os outros

Cada par roda no seu proprio try. Uma falha de rede no BTCUSDT nao pode
impedir o ETHUSDT de ter o stop conferido -- essa e a operacao mais
sensivel a atraso do sistema inteiro.

O processo sai com codigo 1 se ALGUM par falhou, pra que o GitHub Actions
marque a execucao em vermelho. Um ciclo silenciosamente quebrado durante
dias e o pior resultado possivel: o forward test pareceria estar rodando
e nao estaria.
"""

from dotenv import load_dotenv
load_dotenv()

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from adapters.binance_adapter import BinanceAdapter  # noqa: E402
from db.supabase_client import get_supabase_client  # noqa: E402
from live.estado import carregar_conta  # noqa: E402

PARES_PADRAO = ["BTCUSDT", "ETHUSDT"]


def main() -> int:
    ap = argparse.ArgumentParser(description="Ciclo ao vivo do forward test")
    ap.add_argument("--pares", nargs="+", default=PARES_PADRAO)
    ap.add_argument("--estrategia", choices=("tendencia", "hibrida"), default="tendencia")
    ap.add_argument(
        "--ensaio", action="store_true",
        help="mostra o estado atual e sai, sem decidir nem gravar nada",
    )
    args = ap.parse_args()

    supabase = get_supabase_client()

    if args.ensaio:
        for par in args.pares:
            print(f"  {carregar_conta(supabase, par)}")
        return 0

    # `somente_dados_publicos`: o ciclo so LE mercado. Sem credencial da
    # Binance em transito, e sem o endpoint que o CI nao alcanca.
    binance = BinanceAdapter(somente_dados_publicos=True)
    if args.estrategia == "tendencia":
        from live.ciclo_tendencia import rodar_ciclo_tendencia
        from live.explicador import Explicador
        explicador = Explicador()

        def ciclo(par):
            return rodar_ciclo_tendencia(supabase, binance, explicador, par)
    else:
        from brain.llm_analyst import AnalistaLLM
        from live.ciclo import rodar_ciclo
        analista = AnalistaLLM()

        def ciclo(par):
            return rodar_ciclo(supabase, binance, analista, par)

    print(f"estrategia: {args.estrategia}")
    falhas = []
    for par in args.pares:
        try:
            print(f"  {ciclo(par)}", flush=True)
        except Exception as erro:  # noqa: BLE001
            falhas.append(par)
            print(f"  [{par}] FALHA -- {type(erro).__name__}: {erro}", flush=True)

    if falhas:
        print(f"\n{len(falhas)} de {len(args.pares)} pares falharam: {falhas}")
        return 1

    print("\n--- carteira ---")
    for par in args.pares:
        conta = carregar_conta(supabase, par)
        estado = "posicionada" if conta.posicionada else "de fora"
        print(f"  {par:<10} {estado:<12} caixa {conta.caixa:>10,.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
