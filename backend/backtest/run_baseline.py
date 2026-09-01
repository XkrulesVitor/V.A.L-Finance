"""
Roda as baselines (passo 4 do roteiro) e grava o resultado.

    python backend/backtest/run_baseline.py
    python backend/backtest/run_baseline.py --simbolo ETHUSDT --inicio "2 years ago UTC"
    python backend/backtest/run_baseline.py --sem-supabase

Sobre a origem do dado: o historico vem da API publica de PRODUCAO da
Binance, com `testnet=False` e sem chave nenhuma. A testnet e o ambiente
onde ordens serao executadas mais pra frente (passo 8), nao uma fonte de
historico -- o livro dela e raso e sintetico, e backtest rodado em cima
disso mede ruido em vez de mercado.

Cada rodada tambem imprime a conferencia do `buy_and_hold` contra a
formula fechada, sobre os candles reais que acabaram de ser baixados. O
teste sintetico em `backend/tests/test_backtest_engine.py` ja cobre isso,
mas repetir aqui custa nada e transforma a verificacao em algo que
acontece toda vez, e nao so quando alguem lembra de rodar os testes.
"""

from dotenv import load_dotenv
load_dotenv()

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from adapters.binance_adapter import BinanceAdapter  # noqa: E402
from backtest.engine import (  # noqa: E402
    CAPITAL_INICIAL_PADRAO,
    TAXA_PADRAO,
    ResultadoBacktest,
    rodar_backtest,
    salvar_json,
)
from backtest.strategies import ESTRATEGIAS  # noqa: E402
from features.feature_engine import CANDLES_NECESSARIOS  # noqa: E402

PASTA_CACHE = Path(__file__).resolve().parent / ".cache"
PASTA_RESULTADOS = Path(__file__).resolve().parent / "resultados"


# --------------------------------------------------------------------
# Dados
# --------------------------------------------------------------------


def buscar_historico_com_cache(simbolo, intervalo, inicio, fim, usar_cache=True) -> list[dict]:
    """
    Baixa o historico da Binance, guardando uma copia local.

    O cache existe por conforto de desenvolvimento: um ano em 1h sao
    ~8.760 candles e ~9 requisicoes encadeadas, e durante o passo 7 este
    mesmo periodo vai ser rodado varias vezes seguidas comparando
    estrategias. Nao contradiz a decisao de nao guardar candle bruto no
    Supabase (secao 7) -- e arquivo local descartavel, fora do git, e nao
    estado do sistema.
    """
    PASTA_CACHE.mkdir(parents=True, exist_ok=True)
    apelido = re.sub(r"[^a-zA-Z0-9]+", "-", f"{simbolo}_{intervalo}_{inicio}_{fim or 'agora'}")
    arquivo = PASTA_CACHE / f"{apelido}.json"

    if usar_cache and arquivo.exists():
        candles = json.loads(arquivo.read_text(encoding="utf-8"))
        print(f"  cache: {len(candles)} candles de {arquivo.name}")
        return candles

    print(f"  baixando {simbolo} {intervalo} de '{inicio}' ate '{fim or 'agora'}'...")
    binance = BinanceAdapter(testnet=False, somente_dados_publicos=True)
    candles = binance.buscar_historico(simbolo, intervalo=intervalo, inicio=inicio, fim=fim)
    arquivo.write_text(json.dumps(candles), encoding="utf-8")
    print(f"  baixados {len(candles)} candles")
    return candles


# --------------------------------------------------------------------
# Conferencia
# --------------------------------------------------------------------


def conferir_buy_and_hold(candles, resultado, capital, taxa) -> tuple[bool, str]:
    """
    Compara o `buy_and_hold` do motor com a formula fechada.

    Entrada na abertura do candle 1 (a decisao nasceu no fechamento do
    candle 0), saida no fechamento do ultimo, uma taxa por ponta:

        esperado = capital * (fechamento_final / abertura_1) * (1 - taxa)^2
    """
    entrada = candles[1]["abertura"]
    saida = candles[-1]["fechamento"]
    esperado = capital * (saida / entrada) * (1 - taxa) ** 2
    obtido = resultado.metricas["saldo_final"]
    diferenca = abs(obtido - esperado)

    linhas = [
        f"    preco de entrada (abertura do candle 1): {entrada:,.2f}",
        f"    preco de saida  (fechamento do ultimo): {saida:,.2f}",
        f"    variacao pura do preco:                 {(saida / entrada - 1) * 100:+.2f}%",
        f"    esperado pela formula:                  {esperado:,.2f}",
        f"    calculado pelo motor:                   {obtido:,.2f}",
        f"    diferenca:                              {diferenca:,.6f}",
    ]
    # Tolerancia de 1 centavo: o motor arredonda o saldo final em 2 casas.
    return diferenca <= 0.01, "\n".join(linhas)


# --------------------------------------------------------------------
# Persistencia
# --------------------------------------------------------------------


def salvar_no_supabase(
    resultado: ResultadoBacktest, simbolo: str, notas: str, params_extra: dict | None = None
) -> str:
    """
    Grava a rodada na tabela `backtest_runs`.

    Guarda so metricas e parametros -- nem a curva de capital nem a lista
    de operacoes vao pro banco. Sao milhares de pontos por rodada, e o
    free tier tem 500MB; o que responde "essa estrategia bateu a outra?"
    sao as metricas. Curva e operacoes ficam no JSON local pra quando a
    duvida for sobre uma operacao especifica.
    """
    from db.supabase_client import get_supabase_client

    supabase = get_supabase_client()
    resposta = supabase.table("backtest_runs").insert({
        "strategy_name": resultado.estrategia,
        "symbol": simbolo,
        "period_start": resultado.periodo["inicio"],
        "period_end": resultado.periodo["fim"],
        "params": resultado.parametros
        | {"candles": resultado.periodo["candles"]}
        | (params_extra or {}),
        "metrics": resultado.metricas,
        "notes": notas,
    }).execute()
    return resposta.data[0]["id"]


# --------------------------------------------------------------------
# Entrada
# --------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description="Roda as baselines do passo 4.")
    parser.add_argument("--simbolo", default="BTCUSDT")
    parser.add_argument("--intervalo", default="1h")
    parser.add_argument("--inicio", default="1 year ago UTC")
    parser.add_argument("--fim", default=None)
    parser.add_argument("--capital", type=float, default=CAPITAL_INICIAL_PADRAO)
    parser.add_argument("--taxa", type=float, default=TAXA_PADRAO)
    parser.add_argument("--janela", type=int, default=CANDLES_NECESSARIOS)
    parser.add_argument("--sem-cache", action="store_true", help="ignora o cache local")
    parser.add_argument("--sem-supabase", action="store_true", help="nao grava no banco")
    parser.add_argument("--notas", default="baseline do passo 4 do roteiro")
    argumentos = parser.parse_args()

    print(f"\n=== baseline {argumentos.simbolo} {argumentos.intervalo} ===")
    candles = buscar_historico_com_cache(
        argumentos.simbolo, argumentos.intervalo, argumentos.inicio,
        argumentos.fim, usar_cache=not argumentos.sem_cache,
    )
    if len(candles) < 2:
        print("  historico insuficiente -- nada a fazer")
        return 1

    PASTA_RESULTADOS.mkdir(parents=True, exist_ok=True)
    resultados = {}

    print()
    for nome, estrategia in ESTRATEGIAS.items():
        resultado = rodar_backtest(
            candles, estrategia,
            capital_inicial=argumentos.capital,
            taxa_por_operacao=argumentos.taxa,
            janela_maxima=argumentos.janela,
            nome_estrategia=nome,
        )
        resultados[nome] = resultado
        print("  " + resultado.resumo())
        salvar_json(resultado, PASTA_RESULTADOS / f"{argumentos.simbolo}_{nome}.json")

    # Conferencia obrigatoria sobre os candles reais.
    print("\n  conferencia do buy_and_hold contra a formula fechada:")
    ok, detalhe = conferir_buy_and_hold(
        candles, resultados["buy_and_hold"], argumentos.capital, argumentos.taxa
    )
    print(detalhe)
    if not ok:
        print("\n  *** DIVERGENCIA: o motor nao bate com a formula. Nao confie neste resultado. ***")
        return 1
    print("    -> bate.")

    if argumentos.sem_supabase:
        print("\n  --sem-supabase: nada gravado no banco.")
        return 0

    print()
    for nome, resultado in resultados.items():
        try:
            identificador = salvar_no_supabase(resultado, argumentos.simbolo, argumentos.notas)
            print(f"  supabase: {nome} gravado ({identificador})")
        except KeyError as erro:
            print(f"  supabase: variavel de ambiente {erro} ausente -- veja backend/.env.example")
            print("            (resultados seguem salvos em backtest/resultados/)")
            return 0
        except Exception as erro:  # noqa: BLE001
            print(f"  supabase: falhou ao gravar {nome} -- {type(erro).__name__}: {erro}")
            print("            se a tabela nao existe, rode supabase/schema.sql no SQL Editor")
            return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
