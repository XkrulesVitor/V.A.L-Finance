"""
Roda o proximo ativo pendente da replicacao do passo 7.

    python backend/backtest/rodar_pendente.py
    python backend/backtest/rodar_pendente.py --listar

Existe pra ser chamado por agendamento. Um agendador que precisasse
decidir "qual ativo falta?" teria que ler o banco e raciocinar; aqui a
decisao e uma consulta e um `for`. Menos coisa pra dar errado as 4 da
manha.

## A janela e fixa de proposito

Os tres ativos rodam na MESMA janela que BTCUSDT e BNBUSDT ja rodaram
(10/08 a 09/11/2025). Comparar replicacoes em janelas diferentes nao
responde "existe vantagem na media?" -- responde uma pergunta
diferente para cada ativo. Por isso o timestamp esta fixo aqui e nao e
parametro: mudar a janela sem querer invalidaria a comparacao inteira,
em silencio.

## Ordem e criterio

Os ativos foram escolhidos ANTES de olhar o resultado deles no periodo
-- sao o que sobrou da lista de majors depois de BTC (caiu) e BNB
(subiu). Isso importa: a BNB foi escolhida sabendo que tinha subido, e
por isso aquele resultado sozinho nao prova nada. Estes tres nao.

Um ativo e considerado feito quando ja existe uma linha
`hibrida_llm_risk` para ele naquela janela. Rodar de novo por engano
nao quebra nada (o cache cobre), mas gasta tempo.
"""

from dotenv import load_dotenv
load_dotenv()

import argparse
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from db.supabase_client import get_supabase_client  # noqa: E402

# Mesma janela de BTCUSDT e BNBUSDT. Nao parametrizar e a protecao.
INICIO_MS = 1754856000000  # 2025-08-10 20:00 UTC
FIM_MS = 1762714800000     # 2025-11-09 19:00 UTC

ATIVOS = ["ETHUSDT", "SOLUSDT", "XRPUSDT"]
ESTRATEGIA = "hibrida_llm_risk"


def ja_rodados() -> set[str]:
    """Quais ativos ja tem a hibrida gravada naquela janela."""
    supabase = get_supabase_client()
    resposta = (
        supabase.table("backtest_runs")
        .select("symbol, period_start, params")
        .eq("strategy_name", ESTRATEGIA)
        .execute()
    )
    feitos = set()
    for linha in resposta.data or []:
        # A janela e identificada pelo numero de candles + inicio; comparar
        # o timestamp exato evita confundir com uma rodada de outro periodo.
        if (linha.get("params") or {}).get("candles") == 2184:
            feitos.add(linha["symbol"])
    return feitos


def main() -> int:
    parser = argparse.ArgumentParser(description="Roda o proximo ativo pendente.")
    parser.add_argument("--listar", action="store_true", help="so mostra o que falta")
    argumentos = parser.parse_args()

    try:
        feitos = ja_rodados()
    except Exception as erro:  # noqa: BLE001
        print(f"nao consegui consultar o Supabase: {type(erro).__name__}: {erro}")
        print("sem saber o que ja rodou, nao rodo nada -- repetir gasta cota a toa.")
        return 1

    pendentes = [a for a in ATIVOS if a not in feitos]
    print(f"ja rodados: {sorted(feitos) or 'nenhum'}")
    print(f"pendentes:  {pendentes or 'nenhum'}")

    if argumentos.listar:
        return 0
    if not pendentes:
        print("\nnada a fazer -- os tres ativos ja rodaram nesta janela.")
        return 0

    alvo = pendentes[0]
    print(f"\n=== rodando {alvo} ===\n", flush=True)

    comando = [
        sys.executable, "-u", str(RAIZ / "backtest" / "run_hybrid.py"),
        "--simbolo", alvo,
        "--inicio", str(INICIO_MS),
        "--fim", str(FIM_MS),
        "--notas", (
            "replicacao do passo 7 em ativo escolhido ANTES de ver o resultado "
            "do periodo; mesma janela e config de BTCUSDT/BNBUSDT"
        ),
    ]
    return subprocess.call(comando)


if __name__ == "__main__":
    sys.exit(main())
