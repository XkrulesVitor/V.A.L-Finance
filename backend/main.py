"""
Ponto de entrada do cron job (Render).

Fase atual -- Passo 2 do roteiro: alem de provar que o pipeline roda
ponta a ponta (Binance -> Supabase -> frontend), agora tambem calcula
os indicadores tecnicos de cada par e os grava no campo `features`.

Ainda nao ha decisao de verdade: o `status` continua `skeleton_check`
de proposito, e so muda quando o cerebro entrar (passo 5) e tiver o que
decidir. Marcar como decidido antes disso sujaria o historico da tabela
`decisions`, que e justamente o que vai responder depois se o sistema
tem alguma vantagem real (principio 4, secao 4 do ARCHITECTURE.md).
"""

from dotenv import load_dotenv
load_dotenv()  # carrega .env localmente; no Render as env vars ja vem do painel

from datetime import datetime, timezone

from adapters.binance_adapter import BinanceAdapter
from db.supabase_client import get_supabase_client
from features.candles import somente_fechados
from features.feature_engine import CANDLES_NECESSARIOS, calcular_features

SIMBOLOS = ["BTCUSDT", "ETHUSDT"]  # ajuste os ativos que quer acompanhar
INTERVALO = "1h"

# Um a mais do que a Feature Engine precisa: o ultimo candle que a
# Binance devolve costuma ser o que ainda esta aberto, e ele e
# descartado logo abaixo. Sem essa folga, a janela chegaria curta.
CANDLES_A_PEDIR = CANDLES_NECESSARIOS + 1


def rodar_ciclo() -> None:
    # Dados publicos: sem credencial e com os candles REAIS do mainnet.
    # Antes isto usava testnet=True, cujo livro tem ~5% do volume real --
    # o que distorcia `volume_relativo`, uma das features gravadas aqui.
    binance = BinanceAdapter(somente_dados_publicos=True)
    supabase = get_supabase_client()

    for simbolo in SIMBOLOS:
        preco = binance.buscar_preco(simbolo)
        # CANDLES_NECESSARIOS vem da Feature Engine, e nao de um numero
        # solto aqui: quem sabe quanto historico cada indicador exige e
        # ela. Se um dia entrar um indicador de janela maior, o pedido a
        # Binance acompanha sozinho.
        candles = binance.buscar_candles(simbolo, intervalo=INTERVALO, limite=CANDLES_A_PEDIR)

        # Este e o caminho AO VIVO, e aqui o candle em andamento atrapalha:
        # o volume dele e parcial, o que empurra o `volume_relativo` pra
        # baixo em todo ciclo -- vies sistematico, sempre pro mesmo lado.
        # A Feature Engine continua pura; quem filtra e quem chama.
        fechados = somente_fechados(candles)
        features = calcular_features(fechados)

        market_snapshot = {
            "preco_atual": preco,
            # O ultimo candle FECHADO, e nao o mais recente da lista: e
            # dele que as features saem, e snapshot que nao bate com as
            # features seria armadilha na hora de auditar uma decisao.
            "ultimo_candle": fechados[-1] if fechados else None,
            "candles_em_andamento_descartados": len(candles) - len(fechados),
            "checado_em": datetime.now(timezone.utc).isoformat(),
        }

        supabase.table("decisions").insert(
            {
                "symbol": simbolo,
                "market_snapshot": market_snapshot,
                "features": features,
                "status": "skeleton_check",
            }
        ).execute()

        print(
            f"[{simbolo}] preco={preco} rsi={features['rsi_14']} "
            f"atr={features['atr_14']} vol_rel={features['volume_relativo']} "
            f"-- registrado no Supabase"
        )


if __name__ == "__main__":
    rodar_ciclo()
