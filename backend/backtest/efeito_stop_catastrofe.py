"""
Quanto o stop de catastrofe muda o ensemble de tendencia -- medido, nao
suposto.

    python backend/backtest/efeito_stop_catastrofe.py
    python backend/backtest/efeito_stop_catastrofe.py --fim 2024-09-03

## Por que isto e um script a parte

O estudo de tendencia (estudo_tendencia_diaria.py) foi pre-registrado com
duas configuracoes e nenhuma delas tinha stop. O ciclo ao vivo precisa de
um -- o agendamento do GitHub tem buracos de horas e uma posicao nao pode
ficar sem piso durante eles --, entao a versao que opera nao e exatamente
a versao medida. Este script mede a diferenca, nas mesmas janelas do estudo, sem
tocar no estudo original. Ele nao escolhe parametro nenhum: o nivel
(20%) foi fixado antes de rodar, e o que se quer saber e so se ele
atrapalha.

A mecanica e a do ciclo ao vivo: o stop e conferido em cada fechamento de
hora; disparou, sai; e so volta a entrar com um voto de um dia que fechou
depois da saida (`voto_vale_para_entrada`).
"""

import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import backtest.estudo_tendencia_diaria as etd  # noqa: E402
from backtest.engine import SELL, rodar_backtest  # noqa: E402
from backtest.estudo_votacao import ATIVOS, HORAS_JANELA, N_JANELAS  # noqa: E402
from estrategia import tendencia_diaria as regra  # noqa: E402

HORA_MS = 3_600_000


class BinariaComStop:
    def __init__(self, votos):
        self.votos = votos
        self.ultima_saida = None
        self.stops = 0
        self.__name__ = "tendencia_binaria_stop"

    def __call__(self, ctx):
        c = ctx.candle_atual
        fechou_em = c["abertura_em"] + HORA_MS
        if ctx.posicao_aberta and ctx.preco_atual <= regra.nivel_de_stop(ctx.preco_de_entrada):
            self.ultima_saida = fechou_em
            self.stops += 1
            return SELL
        dia = c["abertura_em"] // etd.DIA_MS - 1
        pode = regra.voto_vale_para_entrada((dia + 1) * etd.DIA_MS, self.ultima_saida)
        acao = regra.decidir(self.votos.get(dia), ctx.posicao_aberta, pode_entrar=pode)
        if acao == SELL:
            self.ultima_saida = fechou_em
        return acao


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--fim", help="fim do periodo (AAAA-MM-DD); padrao o do estudo")
    args = ap.parse_args()
    if args.fim:
        etd.FIM = datetime.fromisoformat(args.fim).replace(tzinfo=timezone.utc)
    print(f"periodo: {N_JANELAS} janelas de 91 dias terminando em {etd.FIM.date()}, stop {regra.STOP_CATASTROFE:.0%}")

    difs, dds, stops, janelas_com_stop = [], [], 0, 0
    for ativo in ATIVOS:
        serie = etd.baixar_com_aquecimento(ativo)
        votos = etd.votos_por_dia(serie)
        inicio = int((etd.FIM.timestamp() - N_JANELAS * HORAS_JANELA * 3600) * 1000)
        base = next(i for i, c in enumerate(serie) if c["abertura_em"] >= inicio)
        for j in range(N_JANELAS):
            candles = serie[base + j * HORAS_JANELA : base + (j + 1) * HORAS_JANELA]
            if len(candles) < HORAS_JANELA * 0.95:
                continue
            # Mesma guarda do estudo: janela sem voto no primeiro dia fica de
            # fora, para as janelas daqui serem exatamente as de la.
            if votos.get(candles[0]["abertura_em"] // etd.DIA_MS - 1) is None:
                continue
            sem = rodar_backtest(candles, etd.Binaria(votos), nome_estrategia="sem").metricas
            e = BinariaComStop(votos)
            com = rodar_backtest(candles, e, nome_estrategia="com").metricas
            difs.append(com["retorno_total_pct"] - sem["retorno_total_pct"])
            dds.append(com["max_drawdown_pct"] - sem["max_drawdown_pct"])
            stops += e.stops
            janelas_com_stop += e.stops > 0
            if e.stops:
                print(f"  {ativo} j{j}: {e.stops} stop(s)  retorno {sem['retorno_total_pct']:+7.2f} -> {com['retorno_total_pct']:+7.2f}"
                      f"  dd {sem['max_drawdown_pct']:+7.2f} -> {com['max_drawdown_pct']:+7.2f}")

    print(f"\n{len(difs)} janelas, {stops} stops em {janelas_com_stop} janelas")
    print(f"retorno  com - sem: media {statistics.mean(difs):+.2f} pts, pior {min(difs):+.2f}, melhor {max(difs):+.2f}")
    print(f"drawdown com - sem: media {statistics.mean(dds):+.2f} pts (positivo = menor drawdown)")


if __name__ == "__main__":
    main()
