"""
Validacao do cerebro contra o Gemini de verdade -- passo 5.

    python backend/brain/validar_ao_vivo.py --listar-modelos
    python backend/brain/validar_ao_vivo.py
    python backend/brain/validar_ao_vivo.py --amostras 5 --espacamento-horas 12

Precisa de GEMINI_API_KEY no backend/.env. Nao precisa de chave da
Binance: historico de preco e endpoint publico.

## O que e conferido

- toda resposta valida contra `TeseDeOperacao` (o schema Pydantic);
- `confidence` sempre entre 0 e 1;
- `NO_TRADE` aparece pelo menos uma vez. Nao aparecer nao e erro
  automatico, mas e sinal de alerta: pode indicar prompt empurrando o
  modelo a sempre escolher um lado, que e exatamente o que a secao 6
  proibe. O script reporta e comenta em vez de falhar sozinho.

## Como as amostras sao montadas

Os snapshots sao espacados em 24h (configuravel), e nao consecutivos.
Dez candles seguidos de 1h descrevem praticamente o mesmo mercado -- o
modelo responderia dez vezes a mesma coisa, e a amostra nao diria nada
sobre variedade de resposta. Espacar cobre estados de mercado
diferentes dentro de um periodo ainda recente.

Metade das amostras e apresentada com posicao aberta e metade sem. Sem
isso, metade do vocabulario fica inalcancavel: HOLD e SELL so fazem
sentido com posicao existente (secao 6), e um teste que so pergunta
"sem posicao" nunca veria o modelo escolher entre os quatro estados.

Candles em andamento sao descartados antes de calcular as features --
e o caminho ao vivo, e e justamente onde o candle nao fechado
distorceria o `volume_relativo`.
"""

from dotenv import load_dotenv
load_dotenv()

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from adapters.binance_adapter import BinanceAdapter  # noqa: E402
from brain.llm_analyst import AnalistaLLM, ErroDoCerebro, TeseDeOperacao  # noqa: E402
from features.candles import somente_fechados  # noqa: E402
from features.feature_engine import CANDLES_NECESSARIOS, calcular_features  # noqa: E402

SIMBOLO_PADRAO = "BTCUSDT"
PAUSA_ENTRE_CHAMADAS_S = 5.0  # free tier tem limite por minuto (secao 8)


def listar_modelos() -> int:
    """Mostra o que a chave enxerga hoje -- nome de modelo do Gemini muda."""
    analista = AnalistaLLM()
    print("modelos visiveis para esta chave:\n")
    try:
        for nome in analista.provedor.listar_modelos():
            print(f"  {nome}")
    except Exception as erro:  # noqa: BLE001
        print(f"  falhou: {type(erro).__name__}: {erro}")
        return 1
    print(f"\nem uso agora: {analista.modelo}  (troque com GEMINI_MODELO no .env)")
    return 0


def montar_amostras(candles, quantidade, espacamento_horas):
    """
    Janelas terminando em pontos diferentes do passado recente.

    Cada janela tem `CANDLES_NECESSARIOS` candles -- a mesma que o cron
    job ao vivo vai montar -- e termina `espacamento_horas` antes da
    anterior. Nenhuma enxerga alem do proprio fim.
    """
    amostras = []
    for i in range(quantidade):
        fim = len(candles) - i * espacamento_horas
        inicio = fim - CANDLES_NECESSARIOS
        if inicio < 0:
            break
        janela = candles[inicio:fim]
        amostras.append({
            "janela": janela,
            "features": calcular_features(janela),
            "preco": janela[-1]["fechamento"],
            "quando": janela[-1]["abertura_em"],
            # Alterna pra que HOLD e SELL sejam alcancaveis.
            "posicao_aberta": i % 2 == 1,
        })
    return list(reversed(amostras))


def main() -> int:
    parser = argparse.ArgumentParser(description="Valida o cerebro contra o Gemini real.")
    parser.add_argument("--simbolo", default=SIMBOLO_PADRAO)
    parser.add_argument("--amostras", type=int, default=8)
    parser.add_argument("--espacamento-horas", type=int, default=24)
    parser.add_argument("--listar-modelos", action="store_true")
    argumentos = parser.parse_args()

    if argumentos.listar_modelos:
        return listar_modelos()

    analista = AnalistaLLM()
    print(f"modelo: {analista.modelo}")

    # Dado de PRODUCAO, nao testnet (o livro da testnet e sintetico).
    print(f"baixando candles de {argumentos.simbolo}...")
    binance = BinanceAdapter(testnet=False, somente_dados_publicos=True)
    horas = CANDLES_NECESSARIOS + argumentos.amostras * argumentos.espacamento_horas + 24
    candles = binance.buscar_historico(
        argumentos.simbolo, intervalo="1h", inicio=f"{horas} hours ago UTC"
    )

    fechados = somente_fechados(candles)
    descartados = len(candles) - len(fechados)
    print(f"  {len(candles)} candles, {descartados} em andamento descartado(s), "
          f"{len(fechados)} fechados")

    amostras = montar_amostras(fechados, argumentos.amostras, argumentos.espacamento_horas)
    print(f"  {len(amostras)} amostras espacadas de {argumentos.espacamento_horas}h\n")

    resultados, problemas = [], []
    for i, amostra in enumerate(amostras, start=1):
        posicao = "com posicao" if amostra["posicao_aberta"] else "sem posicao"
        try:
            tese = analista.analisar(
                features=amostra["features"],
                simbolo=argumentos.simbolo,
                posicao_aberta=amostra["posicao_aberta"],
                preco_atual=amostra["preco"],
            )
        except ErroDoCerebro as erro:
            print(f"  {i}/{len(amostras)}  FALHOU: {erro}")
            problemas.append(f"amostra {i}: {erro}")
            continue

        # Cinto e suspensorio: o schema ja restringiu a geracao, mas o
        # que o resto do sistema confia e a validacao deste lado.
        assert isinstance(tese, TeseDeOperacao)
        if not 0.0 <= tese.confidence <= 1.0:
            problemas.append(f"amostra {i}: confidence fora da faixa ({tese.confidence})")

        resultados.append(tese)
        rsi = amostra["features"]["rsi_14"]
        print(f"  {i}/{len(amostras)}  {posicao:<12} rsi={rsi:<6} -> "
              f"{tese.direction:<9} {tese.horizon:<6} conf={tese.confidence:.2f}")
        print(f"          {tese.reasoning}")

        if i < len(amostras):
            time.sleep(PAUSA_ENTRE_CHAMADAS_S)

    # ---------------- relatorio ----------------
    print(f"\n{'=' * 62}")
    print(f"chamadas reais ao Gemini: {analista.chamadas}")

    if not resultados:
        print("nenhuma resposta valida -- nada a concluir")
        return 1

    contagem = {}
    for tese in resultados:
        contagem[tese.direction] = contagem.get(tese.direction, 0) + 1
    print(f"respostas validas: {len(resultados)}/{len(amostras)}")
    print(f"distribuicao: {contagem}")

    confiancas = [tese.confidence for tese in resultados]
    print(f"confidence: min={min(confiancas):.2f} max={max(confiancas):.2f} "
          f"media={sum(confiancas) / len(confiancas):.2f}")
    print(f"todas entre 0 e 1: {all(0.0 <= c <= 1.0 for c in confiancas)}")

    if contagem.get("NO_TRADE"):
        print(f"NO_TRADE apareceu {contagem['NO_TRADE']}x -- o modelo usa a saida de nao operar")
    else:
        print("ATENCAO: NO_TRADE nao apareceu em nenhuma amostra.")
        print("  Nao e erro automatico, mas merece olhar: pode ser periodo de")
        print("  tendencia clara, ou prompt empurrando o modelo a sempre escolher")
        print("  um lado -- o que a secao 6 proibe explicitamente.")

    if problemas:
        print(f"\nproblemas ({len(problemas)}):")
        for problema in problemas:
            print(f"  - {problema}")
        return 1

    print("\ntudo dentro do contrato.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
