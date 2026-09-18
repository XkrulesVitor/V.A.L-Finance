"""
Estudo: votacao entre varias estrategias -- a ideia de "comprar quando uma
% das estrategias der gatilho", medida antes de ser construida.

    python backend/backtest/estudo_votacao.py            # baixa (com cache) e roda
    python backend/backtest/estudo_votacao.py --rapido   # 2 ativos, para conferir o codigo

Zero chamada de LLM. Tudo aqui e aritmetica sobre candles publicos.

## Pre-registro

Os votantes, os limiares e as variantes abaixo foram fixados ANTES de o
estudo rodar pela primeira vez, e todos os resultados sao reportados --
inclusive os ruins. Testar 17 configuracoes e escolher a melhor depois
de ver o numero e exatamente o vies de multiplos testes que faz backtest
mentir; por isso nada aqui e ajustado depois.

Votantes (7), cada um com o proprio estado comprado/fora:
  1. ema_cruzamento   comprado se EMA20 > EMA50                 (tendencia)
  2. acima_ema200     comprado se fechamento > EMA200           (filtro de regime)
  3. macd_histograma  comprado se histograma do MACD > 0        (momento)
  4. rsi_reversao     entra com RSI < 30, sai com RSI > 70      (reversao)
  5. donchian         entra rompendo a maxima de 20, sai perdendo a minima de 10
  6. bollinger_rev    entra abaixo da banda inferior (20, 2dp), sai na media
  7. momento_7d       comprado se fechamento > fechamento de 168h atras

Regra de votacao (a proposta do dono, lida literalmente):
  - fora: entra quando >= k votantes estao comprados
  - dentro: sai quando >= k votantes estao fora
  - entre os dois, mantem (histerese natural)
  k em {4, 5, 6} de 7.

Variantes:
  - "pura":        so a votacao
  - "stop":        votacao + stop 4x ATR e alvo 6x ATR (o horizonte "medio"
                   do Risk Engine atual), conferidos no fechamento
  - "stop+sinal":  igual a "stop", mas depois de uma saida por stop/alvo so
                   reentra quando a votacao cair abaixo de k e voltar -- ou
                   seja, exige um sinal NOVO. E a correcao classica para o
                   rodizio que o forward test mostrou no ETH.

## Reconstrucao do mapa de regimes

O estudo de regimes de 01/09 nao registrou ativos nem datas. Este usa, e
registra: 8 ativos, 8 janelas consecutivas de 91 dias terminando em
2026-09-01 00:00 UTC, rotulo pelo proprio ativo (alta > +10%, baixa < -10%,
lateral no meio). Os numeros NAO sao diretamente comparaveis aos daquele
estudo; a pergunta aqui e comparativa dentro deste mesmo conjunto.
"""

import argparse
import json
import statistics
import sys
import time
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backtest.engine import BUY, HOLD, NO_TRADE, SELL, rodar_backtest  # noqa: E402
from backtest.run_baseline import buscar_historico_com_cache  # noqa: E402
from features.feature_engine import CANDLES_NECESSARIOS, calcular_features  # noqa: E402

ATIVOS = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT", "LINKUSDT"]
FIM = datetime(2026, 9, 1, tzinfo=timezone.utc)
HORAS_JANELA = 91 * 24
N_JANELAS = 8
LIMIARES = (4, 5, 6)
VARIANTES = ("pura", "stop", "stop+sinal")
MULT_STOP, MULT_ALVO = 4.0, 6.0

SAIDA = Path(__file__).resolve().parent / "resultados" / "estudo_votacao.json"


# ---------------------------------------------------------------- votantes

class Votante:
    """Estado comprado/fora de uma regra, atualizado uma vez por candle."""

    nome = "votante"

    def __init__(self):
        self.comprado = False

    def atualizar(self, f: dict, candles: list[dict]) -> bool:
        raise NotImplementedError


class EmaCruzamento(Votante):
    nome = "ema_cruzamento"

    def atualizar(self, f, candles):
        e20, e50 = f["ema_20"], f["ema_50"]
        self.comprado = e20 is not None and e50 is not None and e20 > e50
        return self.comprado


class AcimaEma200(Votante):
    nome = "acima_ema200"

    def atualizar(self, f, candles):
        e = f["ema_200"]
        self.comprado = e is not None and candles[-1]["fechamento"] > e
        return self.comprado


class MacdHistograma(Votante):
    nome = "macd_histograma"

    def atualizar(self, f, candles):
        h = (f.get("macd") or {}).get("histograma")
        self.comprado = h is not None and h > 0
        return self.comprado


class RsiReversao(Votante):
    nome = "rsi_reversao"

    def atualizar(self, f, candles):
        rsi = f["rsi_14"]
        if rsi is not None:
            if not self.comprado and rsi < 30:
                self.comprado = True
            elif self.comprado and rsi > 70:
                self.comprado = False
        return self.comprado


class Donchian(Votante):
    nome = "donchian"

    def atualizar(self, f, candles):
        if len(candles) < 22:
            return self.comprado
        fech = candles[-1]["fechamento"]
        anteriores = candles[:-1]
        if not self.comprado and fech > max(c["maxima"] for c in anteriores[-20:]):
            self.comprado = True
        elif self.comprado and fech < min(c["minima"] for c in anteriores[-10:]):
            self.comprado = False
        return self.comprado


class BollingerReversao(Votante):
    nome = "bollinger_rev"

    def atualizar(self, f, candles):
        if len(candles) < 20:
            return self.comprado
        ult = [c["fechamento"] for c in candles[-20:]]
        media = sum(ult) / 20
        dp = statistics.pstdev(ult)
        fech = ult[-1]
        if not self.comprado and fech < media - 2 * dp:
            self.comprado = True
        elif self.comprado and fech > media:
            self.comprado = False
        return self.comprado


class Momento7d(Votante):
    nome = "momento_7d"

    def atualizar(self, f, candles):
        if len(candles) < 169:
            self.comprado = False
        else:
            self.comprado = candles[-1]["fechamento"] > candles[-169]["fechamento"]
        return self.comprado


VOTANTES = [EmaCruzamento, AcimaEma200, MacdHistograma, RsiReversao, Donchian, BollingerReversao, Momento7d]


# -------------------------------------------------------------- estrategias

class Isolada:
    """Um votante sozinho, operando pelo proprio estado."""

    def __init__(self, cls, tabela):
        self.v = cls()
        self.tabela = tabela
        self.__name__ = self.v.nome

    def __call__(self, ctx):
        quer = self.v.atualizar(self.tabela[ctx.candle_atual["abertura_em"]], ctx.candles)
        if ctx.posicao_aberta:
            return HOLD if quer else SELL
        return BUY if quer else NO_TRADE


class Votacao:
    """
    A proposta do dono: entra com >= k de 7 comprados, sai com >= k de 7 fora.
    Opcionalmente com stop/alvo por ATR e com exigencia de sinal novo.
    """

    def __init__(self, k, variante, tabela, registrar=False):
        self.k = k
        self.variante = variante
        self.tabela = tabela
        self.vs = [cls() for cls in VOTANTES]
        self.niveis = None
        self.pendentes = None
        self.bloqueado = False
        self.saidas_por_nivel = 0
        self.historico = [] if registrar else None
        self.__name__ = f"votacao_k{k}_{variante}"

    def __call__(self, ctx):
        f = self.tabela[ctx.candle_atual["abertura_em"]]
        estados = [v.atualizar(f, ctx.candles) for v in self.vs]
        if self.historico is not None:
            self.historico.append(estados)
        comprados = sum(estados)
        fora = len(estados) - comprados
        preco = ctx.preco_atual

        # sincroniza niveis com a posicao real (a ordem preenche no candle seguinte)
        if ctx.posicao_aberta:
            if self.pendentes is not None:
                self.niveis, self.pendentes = self.pendentes, None
        else:
            self.niveis = self.pendentes = None

        if ctx.posicao_aberta:
            if self.variante != "pura" and self.niveis:
                stop, alvo = self.niveis
                if preco <= stop or preco >= alvo:
                    self.saidas_por_nivel += 1
                    self.niveis = None
                    if self.variante == "stop+sinal":
                        self.bloqueado = True
                    return SELL
            if fora >= self.k:
                return SELL
            return HOLD

        if self.bloqueado:
            if comprados < self.k:
                self.bloqueado = False
            return NO_TRADE

        if comprados >= self.k:
            atr = f["atr_14"]
            if self.variante != "pura":
                if not atr:
                    return NO_TRADE
                self.pendentes = (preco - MULT_STOP * atr, preco + MULT_ALVO * atr)
            return BUY
        return NO_TRADE


def comprar_e_segurar(ctx):
    return HOLD if ctx.posicao_aberta else BUY


# -------------------------------------------------------------------- dados

def baixar(ativo: str) -> list[dict]:
    ini = int((FIM.timestamp() - N_JANELAS * HORAS_JANELA * 3600) * 1000)
    fim = int(FIM.timestamp() * 1000)
    return buscar_historico_com_cache(ativo, "1h", str(ini), str(fim))


def tabela_de_features(candles: list[dict]) -> dict:
    """
    Features de cada candle calculadas UMA vez, com a mesma janela que o
    motor da a estrategia (ultimos CANDLES_NECESSARIOS). Sem isto cada uma
    das 17 configuracoes recalcularia tudo, e o estudo levaria horas.
    """
    tabela = {}
    for i in range(len(candles)):
        ini = max(0, i + 1 - CANDLES_NECESSARIOS)
        tabela[candles[i]["abertura_em"]] = calcular_features(candles[ini : i + 1])
    return tabela


def rotulo(candles):
    r = (candles[-1]["fechamento"] / candles[0]["abertura"] - 1) * 100
    return ("alta" if r > 10 else "baixa" if r < -10 else "lateral"), r


def concordancia(historico):
    """% de candles em que cada par de votantes concorda."""
    nomes = [cls.nome for cls in VOTANTES]
    n = len(historico)
    out = {}
    for a, b in combinations(range(len(nomes)), 2):
        out[f"{nomes[a]}~{nomes[b]}"] = sum(1 for e in historico if e[a] == e[b]) / n
    return out


# ------------------------------------------------------------------- estudo

def rodar(ativos):
    linhas = []
    concords = []
    t0 = time.time()
    for ativo in ativos:
        serie = baixar(ativo)
        for j in range(N_JANELAS):
            candles = serie[j * HORAS_JANELA : (j + 1) * HORAS_JANELA]
            if len(candles) < HORAS_JANELA * 0.95:
                print(f"  {ativo} janela {j}: so {len(candles)} candles, pulada")
                continue
            reg, var = rotulo(candles)
            tabela = tabela_de_features(candles)

            configs = [("comprar_e_segurar", comprar_e_segurar)]
            configs += [(cls.nome, Isolada(cls, tabela)) for cls in VOTANTES]
            reg_hist = None
            for k in LIMIARES:
                for variante in VARIANTES:
                    est = Votacao(k, variante, tabela, registrar=(k == 4 and variante == "pura"))
                    if est.historico is not None:
                        reg_hist = est
                    configs.append((est.__name__, est))

            for nome, est in configs:
                m = rodar_backtest(candles, est, nome_estrategia=nome).metricas
                linhas.append({
                    "ativo": ativo, "janela": j, "regime": reg, "variacao_ativo": round(var, 2),
                    "config": nome, "retorno": m["retorno_total_pct"],
                    "drawdown": m["max_drawdown_pct"], "sharpe": m["sharpe"],
                    "trades": m["numero_trades"], "taxas": m["taxas_pagas"],
                })
            if reg_hist is not None:
                concords.append(concordancia(reg_hist.historico))
            print(f"  {ativo} j{j} {reg:<7} {var:+7.1f}%  ({time.time() - t0:.0f}s)", flush=True)
    return linhas, concords


def resumir(linhas, concords):
    configs = sorted({l["config"] for l in linhas}, key=lambda c: (c != "comprar_e_segurar", c))
    bh = {(l["ativo"], l["janela"]): l for l in linhas if l["config"] == "comprar_e_segurar"}
    resumo = {}
    for c in configs:
        L = [l for l in linhas if l["config"] == c]
        venceu_ret = sum(1 for l in L if l["retorno"] > bh[(l["ativo"], l["janela"])]["retorno"])
        venceu_dd = sum(1 for l in L if l["drawdown"] > bh[(l["ativo"], l["janela"])]["drawdown"])
        por_reg = {}
        for reg in ("alta", "lateral", "baixa"):
            R = [l for l in L if l["regime"] == reg]
            if R:
                por_reg[reg] = {
                    "n": len(R),
                    "retorno": round(statistics.mean(l["retorno"] for l in R), 2),
                    "vs_bh": round(statistics.mean(l["retorno"] - bh[(l["ativo"], l["janela"])]["retorno"] for l in R), 2),
                    "drawdown": round(statistics.mean(l["drawdown"] for l in R), 2),
                }
        resumo[c] = {
            "n": len(L),
            "retorno_medio": round(statistics.mean(l["retorno"] for l in L), 2),
            "retorno_mediano": round(statistics.median(l["retorno"] for l in L), 2),
            "drawdown_medio": round(statistics.mean(l["drawdown"] for l in L), 2),
            "trades_medio": round(statistics.mean(l["trades"] for l in L), 1),
            "taxas_medias": round(statistics.mean(l["taxas"] for l in L), 1),
            "vence_bh_retorno": f"{venceu_ret}/{len(L)}",
            "vence_bh_drawdown": f"{venceu_dd}/{len(L)}",
            "por_regime": por_reg,
        }
    conc = {}
    if concords:
        for par in concords[0]:
            conc[par] = round(statistics.mean(c[par] for c in concords) * 100, 1)
    return resumo, conc


def imprimir(resumo, conc):
    print()
    print(f"{'config':<24}{'ret':>8}{'med':>8}{'dd':>8}{'trades':>8}{'>bh ret':>9}{'>bh dd':>8}  "
          f"{'alta vs bh':>11}{'lat vs bh':>11}{'baixa vs bh':>12}")
    print("-" * 118)
    for c, r in resumo.items():
        pr = r["por_regime"]
        g = lambda k: f"{pr[k]['vs_bh']:+.2f}" if k in pr else "-"
        print(f"{c:<24}{r['retorno_medio']:>8.2f}{r['retorno_mediano']:>8.2f}{r['drawdown_medio']:>8.2f}"
              f"{r['trades_medio']:>8.1f}{r['vence_bh_retorno']:>9}{r['vence_bh_drawdown']:>8}  "
              f"{g('alta'):>11}{g('lateral'):>11}{g('baixa'):>12}")
    if conc:
        print("\nconcordancia media entre votantes (% dos candles em que concordam):")
        for par, v in sorted(conc.items(), key=lambda x: -x[1]):
            print(f"  {v:5.1f}%  {par}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rapido", action="store_true")
    args = ap.parse_args()
    ativos = ATIVOS[:2] if args.rapido else ATIVOS
    linhas, concords = rodar(ativos)
    resumo, conc = resumir(linhas, concords)
    imprimir(resumo, conc)
    SAIDA.parent.mkdir(parents=True, exist_ok=True)
    SAIDA.write_text(json.dumps({
        "gerado_em": datetime.now(timezone.utc).isoformat(),
        "ativos": ativos, "fim": FIM.isoformat(), "horas_janela": HORAS_JANELA,
        "n_janelas": N_JANELAS, "limiares": LIMIARES, "variantes": VARIANTES,
        "resumo": resumo, "concordancia": conc, "linhas": linhas,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nresultado completo em {SAIDA}")


if __name__ == "__main__":
    main()
