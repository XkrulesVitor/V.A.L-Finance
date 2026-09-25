"""
Estudo 3: as quatro carteiras de REGRA (T1, T2, G1, G2) -- o backtest
confirmatorio pre-registrado (`backtest/PRE_REGISTRO_6_CARTEIRAS.md`,
secao 12). Este arquivo e o harness: roda as simulacoes e grava os numeros
brutos. A estatistica (12.4), os criterios de leitura (12.5) e o relatorio
ficam em `analise_carteiras.py`.

    python backend/backtest/estudo_carteiras.py                # tudo: R0, R0b, R1, R1c, R2, R3
    python backend/backtest/estudo_carteiras.py --processos 1  # sem paralelismo
    python backend/backtest/analise_carteiras.py               # estatistica e relatorio

Zero chamada de LLM e zero download. So le o cache congelado de candles
(`backtest/.cache`), cujo manifesto e conferido contra o hash do
pre-registro antes de qualquer conta. Se um arquivo faltar, o script PARA:
tentar baixar seria bug (pre-registro, "Situacao", defesa 2).

## As carteiras (parametros congelados na secao 12.1; nada aqui os muda)

- T1 Reguas: 6 medias; entra com >= 4 votos, sai com <= 2.
- T2 Tartarugas: rompe a maxima de 55 dias; sai na minima de 20; stop 2N
  (piso de -20%).
- G1 Reguas com meta: entrada da T1; vende no alvo de 3 ATR14, na virada
  da tendencia ou no stop; depois do alvo, so recompra rearmada (recuo a
  <= 3 votos e volta a >= 4 num dia posterior).
- G2 Repique (RSI 2 de Connors): acima da SMA200 e RSI(2) < 10 compra;
  sai quando fecha acima da SMA5.

Todas com o stop de catastrofe de 20% e a execucao do motor (secao 2.6):
sinal diario do dia D lido no candle das 00:00 de D+1 e preenchido as
01:00; stop e alvo conferidos em cada fechamento de 1h e preenchidos na
abertura seguinte (x = 0).

## Correcoes da secao 16.4 aplicadas ao harness (itens de backtest)

1. Guarda de saida (2.5, item 4): a saida pela REGRA so olha dias D com
   `fechamento_em(D) > entrada_em` (o instante do preenchimento da compra).
   Na versao exploratoria a G2 podia comprar as 01:00 e vender as 02:00
   com o sinal do mesmo dia.
2. Janela diaria dos indicadores = os ultimos `min(300, disponiveis)` dias
   fechados (antes: janela crescente). "Disponivel" e o historico do cache
   congelado ate o dia: os arquivos dos 3 periodos sao fundidos por
   `abertura_em` (candles repetidos tem de ser identicos) e a janela usa
   300 dias sempre que o cache os tem.
3. `atr_pct` so a partir de 150 dias (`alvo.DIAS_MINIMOS`; antes, 14).
3b. O ATR so e exigido na entrada da G1 (a unica que usa alvo). A versao
   exploratoria exigia ATR na entrada das quatro. Nas janelas medidas nao
   muda nada (a guarda de aquecimento exige o RSI(2), que precisa de 220
   dias), mas a regra de T1, T2 e G2 nao tem ATR.

O item 4 da 16.4 (o que faltava no estudo) esta aqui e em
`analise_carteiras.py`: R0 e R0b automaticos, R1c, R3 com x em {0, 2, 6}
e decisao as 05:00, metricas da 12.3 e a estatistica da 12.4. A R0b roda
o harness tambem com cada correcao ligada sozinha, para atribuir cada
diferenca contra os logs exploratorios a uma correcao.

## O que roda (12.2)

- R0: a T1 daqui contra `efeito_stop_catastrofe.py` ("com stop"), janela a
  janela. |dif| <= 0,01 pt nas janelas comuns, senao PARA.
- R1: 8 ativos x 8 janelas de 91 dias x 3 periodos, cada janela comecando
  em caixa. Guarda de aquecimento: a janela so conta se as 4 carteiras tem
  sinal pronto no 1o dia; o mesmo conjunto vale para as 4.
- R1c: uma simulacao continua por ativo e periodo, recortada nas mesmas
  janelas. Comeca 91 dias antes da 1a janela valida quando o historico
  permite -- criterio fixado aqui: as 4 carteiras tem sinal pronto no 1o
  dia do aquecimento (a mesma guarda do R1). Senao comeca na 1a janela.
- R2: uma janela continua de 2 anos por ativo e periodo (o `--continuo`
  exploratorio), comecando em caixa.
- R3: o R1c com stop/alvo preenchidos em k+1+x (x em {0, 2, 6}) e com as
  decisoes diarias preenchidas as 01:00 ou as 05:00.
"""

import contextlib
import hashlib
import io
import json
import math
import sys
import time
from bisect import bisect_left
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import backtest.run_baseline as _rb  # noqa: E402
from backtest.engine import BUY, HOLD, NO_TRADE, SELL, rodar_backtest  # noqa: E402
from backtest.estudo_votacao import ATIVOS, HORAS_JANELA, N_JANELAS  # noqa: E402
from estrategia import alvo, rsi2, tartarugas  # noqa: E402
from estrategia import tendencia_diaria as reguas  # noqa: E402
from estrategia.indicadores import DIA_MS, atr, diarios_de_horarios  # noqa: E402


class _DownloadProibido:
    """O cache e congelado: qualquer tentativa de baixar candle e bug."""

    def __init__(self, *a, **k):
        raise RuntimeError("estudo_carteiras: tentativa de baixar candles -- o cache e congelado (pre-registro)")


# Vale tambem para quem chama `buscar_historico_com_cache` por dentro
# (o R0 usa o loader do estudo de tendencia, como o efeito_stop_catastrofe).
_rb.BinanceAdapter = _DownloadProibido

HORA_MS = 3_600_000
PERIODOS = ("2026-09-01", "2024-09-03", "2022-09-03")
AQUECIMENTO_DIAS = 260        # o do cache; o RSI(2) precisa de 220
AQUECIMENTO_R1C_DIAS = 91
JANELA_DIARIA = 300
CAPITAL = 10_000.0
TAXA = 0.001
PASTA = Path(__file__).resolve().parent / "resultados"
PASTA_CACHE = Path(__file__).resolve().parent / ".cache"
SAIDA = PASTA / "carteiras_confirmatorio.json"
# Pre-registro, "Situacao": sha256 do manifesto dos 83 .json do cache.
MANIFESTO_CACHE = "9b0b6bccc9033ff8df35d6f4c2f1278af3f41d37eb0ae1383252896a547d05dd"

# Codigo que o estudo usa; o sha256 de cada um vai para o bruto (auditoria contra o pre-registro).
ARQUIVOS_DE_CODIGO = (
    "backtest/estudo_carteiras.py", "backtest/engine.py", "backtest/efeito_stop_catastrofe.py",
    "estrategia/alvo.py", "estrategia/indicadores.py", "estrategia/rsi2.py", "estrategia/tartarugas.py",
    "estrategia/tendencia_diaria.py",
)

# (atraso x em candles de 1h para stop/alvo, hora UTC em que a decisao diaria e preenchida)
BASE = (0, 1)
VARIANTES_R3 = ((0, 1), (2, 1), (6, 1), (0, 5), (2, 5), (6, 5))

MOTIVO_STOP = "stop de catastrofe"
MOTIVO_STOP_2N = "stop 2N"
MOTIVO_ALVO = alvo.MOTIVO_ALVO          # "stop gain"
MOTIVO_TENDENCIA = "tendencia virou"
MOTIVO_REPIQUE = "repique"
MOTIVO_FIM = "fim de janela"

# (id, familia do sinal diario, com alvo)
CARTEIRAS = (
    ("T1", "reguas", False),
    ("T2", "tartarugas", False),
    ("G1", "reguas", True),
    ("G2", "rsi2", False),
)

# Configuracoes do harness para a R0b: a exploratoria (sem nenhuma correcao,
# tem de reproduzir os logs de antes do commit), cada correcao sozinha e a
# corrigida (todas; e a confirmatoria).
CONFIGS = {
    "exploratoria": {"tabela": "exploratoria", "guarda_saida": False, "atr_so_g1": False},
    "so_1_guarda": {"tabela": "exploratoria", "guarda_saida": True, "atr_so_g1": False},
    "so_2_janela300": {"tabela": "janela300", "guarda_saida": False, "atr_so_g1": False},
    "so_3_atr150": {"tabela": "atr150", "guarda_saida": False, "atr_so_g1": False},
    "so_3b_atr_so_g1": {"tabela": "exploratoria", "guarda_saida": False, "atr_so_g1": True},
    "corrigida": {"tabela": "corrigida", "guarda_saida": True, "atr_so_g1": True},
}


# ---------------------------------------------------------------- dados

def _ms(texto_data: str) -> int:
    return int(datetime.fromisoformat(texto_data).replace(tzinfo=timezone.utc).timestamp() * 1000)


def _iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()


def manifesto_do_cache() -> tuple[int, str]:
    arqs = sorted(p.name for p in PASTA_CACHE.glob("*.json"))
    linhas = "\n".join(f"{n} {hashlib.sha256((PASTA_CACHE / n).read_bytes()).hexdigest()}" for n in arqs)
    return len(arqs), hashlib.sha256(linhas.encode("utf-8")).hexdigest()


def _ler_cache(ativo: str, ini_ms: int, fim_ms: int) -> list[dict]:
    arq = PASTA_CACHE / f"{ativo}-1h-{ini_ms}-{fim_ms}.json"
    if not arq.exists():
        raise SystemExit(f"falta no cache congelado: {arq.name}. Baixar seria bug (pre-registro). Parei.")
    return json.loads(arq.read_text(encoding="utf-8"))


def limites(fim_txt: str) -> dict:
    fim_ms = _ms(fim_txt)
    ini_janelas = fim_ms - N_JANELAS * HORAS_JANELA * HORA_MS
    return {"fim": fim_ms, "janelas": ini_janelas, "cache": ini_janelas - AQUECIMENTO_DIAS * DIA_MS}


def serie_do_periodo(ativo: str, fim_txt: str) -> list[dict]:
    """O arquivo de 260 dias do periodo -- exatamente o que o estudo exploratorio leu."""
    L = limites(fim_txt)
    return _ler_cache(ativo, L["cache"], L["fim"])


def historico_fundido(ativo: str, fim_txt: str, desde_ms: int) -> tuple[list[dict], int]:
    """
    Todos os arquivos de 1h do cache dos 3 periodos (aquecimentos de 260,
    110 e 0 dias) para o ativo, fundidos por `abertura_em`, de `desde_ms`
    ate o fim do periodo (inclusive, como os arquivos). Um candle que aparece em dois arquivos
    tem de ser identico nos dois; devolve tambem quantos repetidos conferiu.
    """
    fim_ms = _ms(fim_txt)
    por_hora: dict[int, dict] = {}
    repetidos = 0
    for p in PERIODOS:
        L = limites(p)
        for aq in (AQUECIMENTO_DIAS, 110, 0):
            arq = PASTA_CACHE / f"{ativo}-1h-{L['janelas'] - aq * DIA_MS}-{L['fim']}.json"
            if not arq.exists():
                continue
            for c in json.loads(arq.read_text(encoding="utf-8")):
                t = c["abertura_em"]
                if t < desde_ms or t > fim_ms:   # o arquivo traz tambem o candle que abre no fim
                    continue
                if t in por_hora:
                    repetidos += 1
                    if por_hora[t] != c:
                        raise SystemExit(f"cache inconsistente: {ativo} {_iso(t)} difere entre arquivos")
                else:
                    por_hora[t] = c
    return [por_hora[t] for t in sorted(por_hora)], repetidos


# ---------------------------------------------------------------- sinais

def tabelas_por_dia(diarios: list[dict], janela_300: bool = True, atr_150: bool = True) -> dict:
    """
    dia UTC (inteiro) -> o que cada regra diz NO FECHAMENTO daquele dia.
    Quem usa consulta o dia ANTERIOR ao candle corrente.

    `janela_300=False` e `atr_150=False` reproduzem o estudo exploratorio
    (janela crescente; ATR a partir de 14 dias), para a R0b.
    """
    saida = {}
    for i, dia in enumerate(diarios):
        ini = max(0, i + 1 - JANELA_DIARIA) if janela_300 else 0
        janela = diarios[ini : i + 1]
        fech = [c["fechamento"] for c in janela[-max(reguas.LOOKBACKS):]]
        v = reguas.votos(fech)
        t = tartarugas.leitura(janela)
        r = rsi2.leitura(janela)
        if atr_150:
            a = alvo.atr_pct(janela)
        else:
            bruto = atr(janela, alvo.ATR_N)
            a = None if bruto is None else bruto / janela[-1]["fechamento"]
        saida[dia["abertura_em"] // DIA_MS] = {
            "votos": v,
            "reguas": None if v is None else (v >= reguas.ENTRA_COM, v <= reguas.SAI_COM),
            "tartarugas": (t["rompeu_alta"], t["rompeu_baixa"]) if t.get("pronta") else None,
            "n": t.get("n"),
            "rsi2": (r["em_alta_longa"] and r["queda_curta"], r["repicou"]) if r.get("pronta") else None,
            "atr_pct": a,
        }
    return saida


def prontas(tab: dict | None) -> bool:
    """Guarda de aquecimento: as 4 carteiras tem sinal (T1/G1, T2, G2 e o ATR da G1)."""
    return (tab is not None and tab["reguas"] is not None and tab["tartarugas"] is not None
            and tab["rsi2"] is not None and tab["atr_pct"] is not None)


# ---------------------------------------------------------------- carteira

class Carteira:
    """
    Uma carteira no motor de backtest. `familia` escolhe o sinal diario;
    `com_alvo` liga o stop gain de 3 ATR com rearme (G1).

    `atraso` (x) e `hora_decisao` sao a sensibilidade R3: stop/alvo
    disparados no fechamento do candle k preenchem na abertura de k+1+x, e
    a decisao diaria do dia D e tomada no candle das (hora_decisao - 1)h de
    D+1 e preenchida as hora_decisao h. O caso-base e x = 0 e 01:00.
    """

    def __init__(self, nome, familia, tabelas, com_alvo=False, *, guarda_saida=True,
                 atr_so_g1=True, atraso=0, hora_decisao=1):
        self.__name__ = nome
        self.familia = familia
        self.tabelas = tabelas
        self.com_alvo = com_alvo
        self.guarda_saida = guarda_saida
        self.atr_so_g1 = atr_so_g1
        self.atraso = atraso
        self.deslocamento = (hora_decisao - 1) * HORA_MS
        self.motivo_regra = MOTIVO_REPIQUE if familia == "rsi2" else MOTIVO_TENDENCIA
        self.ultima_saida = None     # gatilho_em da ultima saida (fechamento do candle que decidiu)
        self.motivo_saida = None
        self.stop = self.alvo = self.motivo_stop = None
        self.dia_da_entrada = None
        self.entrada_em = None       # abertura do candle em que a compra foi preenchida
        self.recuo_dia = None        # rearme da G1 depois do alvo
        self.pendente = None         # [motivo, candles que faltam] -- stop/alvo com atraso
        self.entradas = []           # dia do sinal de cada compra, em ordem
        self.saidas = []             # (motivo, gatilho_em) de cada venda pedida, em ordem

    def _vender(self, motivo, gatilho_em):
        self.saidas.append((motivo, gatilho_em))
        self.motivo_saida = motivo
        self.stop = self.alvo = self.motivo_stop = None
        self.entrada_em = self.pendente = self.recuo_dia = None
        return SELL

    def __call__(self, ctx):
        c = ctx.candle_atual
        fechou_em = c["abertura_em"] + HORA_MS
        dia = (c["abertura_em"] - self.deslocamento) // DIA_MS - 1
        tab = self.tabelas.get(dia)
        sinal = None if tab is None else tab[self.familia]

        if ctx.posicao_aberta:
            if self.stop is None:
                # Primeira hora depois do preenchimento: niveis fixos, com o
                # preco de entrada (a abertura em que o motor comprou) e os
                # indicadores do dia do sinal.
                self.entrada_em = c["abertura_em"]
                entrada = ctx.preco_de_entrada
                tab_e = self.tabelas[self.dia_da_entrada]
                if self.familia == "tartarugas":
                    self.stop = tartarugas.nivel_de_stop(entrada, tab_e["n"])
                    piso = entrada * (1.0 - tartarugas.PISO_DO_STOP)
                    self.motivo_stop = MOTIVO_STOP_2N if self.stop > piso else MOTIVO_STOP
                else:
                    self.stop = reguas.nivel_de_stop(entrada)
                    self.motivo_stop = MOTIVO_STOP
                if self.com_alvo:
                    self.alvo = alvo.nivel_de_alvo(entrada, tab_e["atr_pct"])
            if self.pendente is not None:
                self.pendente[1] -= 1
                if self.pendente[1] <= 0:
                    return self._vender(self.pendente[0], self.ultima_saida)
                return HOLD
            gatilho = None
            if ctx.preco_atual <= self.stop:
                gatilho = self.motivo_stop
            elif self.alvo is not None and ctx.preco_atual >= self.alvo:
                gatilho = MOTIVO_ALVO
            if gatilho is not None:
                self.ultima_saida = fechou_em
                if self.atraso == 0:
                    return self._vender(gatilho, fechou_em)
                self.pendente = [gatilho, self.atraso]
                return HOLD
            if sinal is not None and sinal[1]:
                # Guarda de saida (16.4-1): so um dia fechado depois da entrada.
                if not self.guarda_saida or (dia + 1) * DIA_MS - 1 > self.entrada_em:
                    self.ultima_saida = fechou_em
                    return self._vender(self.motivo_regra, fechou_em)
            return HOLD

        if sinal is None:
            return NO_TRADE
        # Trava: so entra com o sinal de um dia que fechou depois da ultima saida.
        if not reguas.voto_vale_para_entrada((dia + 1) * DIA_MS, self.ultima_saida):
            return NO_TRADE
        compra = sinal[0]
        if self.com_alvo and self.motivo_saida == MOTIVO_ALVO:
            # Rearme: um dia com votos <= 3 depois da saida, e so entao um
            # dia posterior com votos >= 4.
            if not compra:
                if self.recuo_dia is None:
                    self.recuo_dia = dia
                return NO_TRADE
            if self.recuo_dia is None or dia <= self.recuo_dia:
                return NO_TRADE
        if not compra:
            return NO_TRADE
        if (self.com_alvo or not self.atr_so_g1) and tab["atr_pct"] is None:
            return NO_TRADE
        self.dia_da_entrada = dia
        self.motivo_saida = None
        self.entradas.append(dia)
        return BUY


def rodar(candles, carteira):
    # janela_maxima=1: a carteira so olha o candle corrente; o resultado e o
    # mesmo do padrao (400), so mais rapido.
    return rodar_backtest(candles, carteira, capital_inicial=CAPITAL, taxa_por_operacao=TAXA,
                          janela_maxima=1, nome_estrategia=carteira.__name__)


def extrair(res, carteira, n):
    """
    Da rodada do motor: patrimonio marcado a mercado no fechamento de cada
    candle (SEM a liquidacao final), posicionado ou nao no fechamento de
    cada candle, e as operacoes de ida e volta com o motivo da saida.
    """
    ops = res.operacoes
    mtm = [p["patrimonio"] for p in res.curva_de_capital]
    if ops and ops[-1]["motivo"] == "liquidacao_final":
        mtm[-1] = ops[-1]["quantidade"] * ops[-1]["preco"]
    posicionado = bytearray(n)
    trades, aberta, caixa_antes, k_saida = [], None, CAPITAL, 0
    for op in ops:
        if op["lado"] == BUY:
            aberta = {"i_entrada": op["indice"], "p_entrada": op["preco"], "custo": caixa_antes,
                      "dia_sinal": carteira.entradas[len(trades)]}
            continue
        if op["motivo"] == "estrategia":
            motivo, gatilho = carteira.saidas[k_saida]
            k_saida += 1
            fim_pos = op["indice"]
        else:
            motivo, gatilho = MOTIVO_FIM, None
            fim_pos = op["indice"] + 1
        for h in range(aberta["i_entrada"], fim_pos):
            posicionado[h] = 1
        trades.append({
            **aberta,
            "i_saida": op["indice"], "p_saida": op["preco"], "motivo": motivo, "gatilho_em": gatilho,
            "ret": op["caixa_depois"] / aberta["custo"] - 1.0,
            "ret_preco": op["preco"] / aberta["p_entrada"] - 1.0,
        })
        caixa_antes = op["caixa_depois"]
        aberta = None
    assert k_saida == len(carteira.saidas), "saidas da carteira e do motor fora de sincronia"
    assert aberta is None and len(trades) == len(carteira.entradas), "compras da carteira e do motor fora de sincronia"
    ops_por_indice = [op["indice"] for op in ops]
    return mtm, posicionado, trades, ops_por_indice


def _drawdown(valores, pico):
    dd = 0.0
    for v in valores:
        if v > pico:
            pico = v
        dd = min(dd, v / pico - 1.0)
    return dd


def _resumo_trades(trades):
    """Campos por operacao que o relatorio usa (sem indices de candle)."""
    return [{"ret": t["ret"], "ret_preco": t["ret_preco"], "motivo": t["motivo"],
             "horas": t["i_saida"] - t["i_entrada"]} for t in trades]


def metricas_janela_isolada(res, carteira, candles):
    """R1: a janela e a simulacao inteira (comeca em caixa, liquida no fim)."""
    n = len(candles)
    mtm, pos, trades, ops = extrair(res, carteira, n)
    curva = [p["patrimonio"] for p in res.curva_de_capital]   # com a liquidacao, como o motor mede
    m = res.metricas
    return {
        "r": curva[-1] / CAPITAL - 1.0,
        "ret_pct": m["retorno_total_pct"],
        "dd": _drawdown(curva, curva[0]) * 100.0,
        "dd_motor": m["max_drawdown_pct"],
        "expo": sum(pos) / n,
        "ops": len(ops),
        "trades": _resumo_trades(trades),
    }


def metricas_recorte(mtm, pos, trades, ops, w_ini, w_fim):
    """R1c/R3: recorte [w_ini, w_fim) de uma simulacao continua."""
    v0 = mtm[w_ini - 1] if w_ini > 0 else CAPITAL
    v1 = mtm[w_fim - 1]
    fechadas = [t for t in trades if w_ini <= t["i_saida"] < w_fim]
    return {
        "r": v1 / v0 - 1.0,
        "dd": _drawdown(mtm[w_ini:w_fim], v0) * 100.0,
        "expo": sum(pos[w_ini:w_fim]) / (w_fim - w_ini),
        "ops": sum(1 for i in ops if w_ini <= i < w_fim),
        "posicionada_no_inicio": bool(w_ini > 0 and pos[w_ini - 1]),
        "trades": _resumo_trades(fechadas),
    }


# ---------------------------------------------------------------- referencias

def grade_bh(candles, passos=200):
    """
    b&h de fracao f para f em 0, 0,5%, ..., 100%: (retorno %, drawdown %),
    a mesma conta de `benchmark_exposicao.curva_bh` (compra f na abertura
    do 1o candle, marca nos fechamentos, liquida no ultimo), vetorizada.
    """
    import numpy as np
    p0 = candles[0]["abertura"]
    fech = np.array([c["fechamento"] for c in candles], dtype=float)
    f = np.arange(passos + 1, dtype=float)[:, None] / passos
    v = (1.0 - f) + (f * (1.0 - TAXA) / p0) * fech[None, :]
    pico = np.maximum.accumulate(v, axis=1)
    dd = (v / pico - 1.0).min(axis=1)
    final = (1.0 - f[:, 0]) + f[:, 0] * (1.0 - TAXA) / p0 * fech[-1] * (1.0 - TAXA)
    return [[round(float((a - 1.0) * 100.0), 6), round(float(b * 100.0), 6)] for a, b in zip(final, dd)]


# ---------------------------------------------------------------- faixa da sorte (13.4)

def _multiset_perms(itens):
    """Permutacoes distintas de um multiconjunto (so usado com poucos arranjos)."""
    cont = {}
    for x in itens:
        cont[x] = cont.get(x, 0) + 1
    chaves, atual, n = sorted(cont), [], len(itens)

    def rec():
        if len(atual) == n:
            yield tuple(atual)
            return
        for k in chaves:
            if cont[k]:
                cont[k] -= 1
                atual.append(k)
                yield from rec()
                atual.pop()
                cont[k] += 1

    yield from rec()


def _arranjos(duracoes):
    n = math.factorial(len(duracoes))
    for k in {d: duracoes.count(d) for d in duracoes}.values():
        n //= math.factorial(k)
    return n


def faixa_da_sorte(fech, posicionado, semente_txt, sorteios=5000):
    """
    Permutacao dos periodos comprados sobre a serie horaria (13.4): embaralha
    as duracoes dos blocos de 1 entre si e as dos blocos de 0 entre si,
    mantendo a alternancia. Retorno de um sorteio = produto de C_h/C_{h-1}
    nas horas com s = 1, vezes 0,999^2 por ida e volta. O observado sai da
    mesma formula. Devolve (percentil, arranjos, log-retorno observado,
    log-retornos sorteados).
    """
    import numpy as np
    lr = np.zeros(len(fech))
    lr[1:] = np.diff(np.log(np.asarray(fech, dtype=float)))
    P = np.concatenate([[0.0], np.cumsum(lr)])
    blocos = []
    for h, s in enumerate(posicionado):
        if blocos and blocos[-1][0] == s:
            blocos[-1][1] += 1
        else:
            blocos.append([s, 1])
    tipos = [b[0] for b in blocos]
    d1 = [b[1] for b in blocos if b[0] == 1]
    d0 = [b[1] for b in blocos if b[0] == 0]
    idas = len(d1)
    custo = 2 * idas * math.log(1.0 - TAXA)

    def retorno(seq1, seq0):
        i1 = i0 = 0
        pos, total = 0, 0.0
        for t in tipos:
            if t == 1:
                d = seq1[i1]; i1 += 1
                total += P[pos + d] - P[pos]
            else:
                d = seq0[i0]; i0 += 1
            pos += d
        return total + custo

    observado = retorno(d1, d0)
    arranjos = _arranjos(d1) * _arranjos(d0) if idas else 1
    if arranjos <= sorteios:
        amostra = [retorno(a, b) for a in _multiset_perms(d1) for b in _multiset_perms(d0)]
    else:
        semente = int.from_bytes(hashlib.sha256(semente_txt.encode("utf-8")).digest()[:8], "big")
        rng = np.random.default_rng(semente)
        a1, a0 = np.array(d1), np.array(d0)
        amostra = [retorno(rng.permutation(a1), rng.permutation(a0)) for _ in range(sorteios)]
    amostra = np.array(amostra)
    percentil = float((amostra < observado).mean() * 100.0)
    return percentil, arranjos, float(observado), amostra


# ---------------------------------------------------------------- R0: efeito_stop_catastrofe

def r0_efeito_stop(fim_txt, ativo):
    """
    Retorno "com stop" do `efeito_stop_catastrofe.py`, janela a janela,
    chamando as funcoes dele (o script so imprime a media). Mesmo loader,
    mesmos votos, mesma guarda.
    """
    import backtest.efeito_stop_catastrofe as esc
    import backtest.estudo_tendencia_diaria as etd
    etd.FIM = datetime.fromisoformat(fim_txt).replace(tzinfo=timezone.utc)
    with contextlib.redirect_stdout(io.StringIO()):
        serie = etd.baixar_com_aquecimento(ativo)
    votos = etd.votos_por_dia(serie)
    inicio = int((etd.FIM.timestamp() - N_JANELAS * HORAS_JANELA * 3600) * 1000)
    base = next(i for i, c in enumerate(serie) if c["abertura_em"] >= inicio)
    saida = {}
    for j in range(N_JANELAS):
        candles = serie[base + j * HORAS_JANELA : base + (j + 1) * HORAS_JANELA]
        if len(candles) < HORAS_JANELA * 0.95:
            continue
        if votos.get(candles[0]["abertura_em"] // etd.DIA_MS - 1) is None:
            continue
        e = esc.BinariaComStop(votos)
        com = rodar_backtest(candles, e, nome_estrategia="com").metricas
        saida[j] = {"com": com["retorno_total_pct"], "inicio": candles[0]["abertura_em"], "stops": e.stops}
    return saida


# ---------------------------------------------------------------- o trabalho de um ativo x periodo

def _nova(nome, familia, com_alvo, tabelas, cfg, atraso=0, hora=1):
    return Carteira(nome, familia, tabelas, com_alvo, guarda_saida=cfg["guarda_saida"],
                    atr_so_g1=cfg["atr_so_g1"], atraso=atraso, hora_decisao=hora)


def estudar(tarefa):
    fim_txt, ativo = tarefa
    t0 = time.time()
    L = limites(fim_txt)
    H = HORAS_JANELA
    serie260 = serie_do_periodo(ativo, fim_txt)
    desde = L["janelas"] - (AQUECIMENTO_R1C_DIAS + JANELA_DIARIA + 2) * DIA_MS
    longa, repetidos = historico_fundido(ativo, fim_txt, desde)
    tempos = [c["abertura_em"] for c in longa]
    # A serie longa tem de conter a de 260 dias sem tirar nem por (senao os
    # recortes das janelas mudariam).
    k260 = bisect_left(tempos, serie260[0]["abertura_em"])
    assert longa[k260:] == serie260, f"{ativo} {fim_txt}: serie fundida difere do arquivo de 260 dias"

    d_longa = diarios_de_horarios(longa)
    d_260 = diarios_de_horarios(serie260)
    tabelas = {
        "corrigida": tabelas_por_dia(d_longa, True, True),
        "exploratoria": tabelas_por_dia(d_260, False, False),
        "janela300": tabelas_por_dia(d_longa, True, False),
        "atr150": tabelas_por_dia(d_260, False, True),
    }
    tab_c = tabelas["corrigida"]
    base = bisect_left(tempos, L["janelas"])

    saida = {"periodo": fim_txt, "ativo": ativo,
             "dados": {"candles_arquivo_260": len(serie260), "candles_fundidos": len(longa),
                       "inicio_fundido": _iso(longa[0]["abertura_em"]), "repetidos_conferidos": repetidos,
                       "dias_disponiveis_na_1a_janela": (L["janelas"] - longa[0]["abertura_em"]) // DIA_MS}}

    # ---- janelas e guarda de aquecimento
    janelas = []
    for j in range(N_JANELAS):
        a, b = base + j * H, base + (j + 1) * H
        candles = longa[a:b]
        info = {"j": j, "i_ini": a, "i_fim": min(b, len(longa)), "valida": False, "motivo_fora": None}
        if len(candles) < H * 0.95:
            info["motivo_fora"] = "menos de 95% dos candles"
        else:
            primeiro_dia = candles[0]["abertura_em"] // DIA_MS - 1
            info["inicio"] = _iso(candles[0]["abertura_em"])
            info["var_pct"] = (candles[-1]["fechamento"] / candles[0]["abertura"] - 1) * 100
            info["regime"] = "alta" if info["var_pct"] > 10 else "baixa" if info["var_pct"] < -10 else "lateral"
            info["guarda_exploratoria"] = prontas(tabelas["exploratoria"].get(primeiro_dia))
            if prontas(tab_c.get(primeiro_dia)):
                info["valida"] = True
                info["bh"] = grade_bh(candles)
            else:
                info["motivo_fora"] = "historico curto (sinal nao pronto no 1o dia)"
        janelas.append(info)
    saida["janelas"] = [{k: v for k, v in w.items() if k not in ("i_ini", "i_fim")} for w in janelas]
    validas = [w for w in janelas if w["valida"]]
    saida["diagnostico_correcoes"] = _diagnostico(tabelas, L, longa, validas)

    # ---- R0
    saida["r0"] = r0_efeito_stop(fim_txt, ativo)

    # ---- R1 (todas as configs para a R0b; detalhes so na corrigida)
    r1 = {nome: {} for nome in CONFIGS}
    r1_det = {}
    for w in janelas:
        if w["motivo_fora"] == "menos de 95% dos candles":
            continue
        candles = longa[w["i_ini"] : w["i_fim"]]
        for nome_cfg, cfg in CONFIGS.items():
            tb = tabelas[cfg["tabela"]]
            primeiro_dia = candles[0]["abertura_em"] // DIA_MS - 1
            if not prontas(tb.get(primeiro_dia)):
                continue
            r1[nome_cfg][w["j"]] = {}
            for cid, fam, com_alvo in CARTEIRAS:
                cart = _nova(cid, fam, com_alvo, tb, cfg)
                res = rodar(candles, cart)
                r1[nome_cfg][w["j"]][cid] = res.metricas["retorno_total_pct"]
                if nome_cfg == "corrigida":
                    r1_det.setdefault(w["j"], {})[cid] = metricas_janela_isolada(res, cart, candles)
    saida["r1"] = r1
    saida["r1_det"] = r1_det

    # ---- R1c e R3
    r1c = {"inicio_sim": None, "aquecimento_dias": 0, "variantes": {}}
    if validas:
        w0 = validas[0]
        t_ini_jan = longa[w0["i_ini"]]["abertura_em"]
        t_aq = t_ini_jan - AQUECIMENTO_R1C_DIAS * DIA_MS
        s_aq = bisect_left(tempos, t_aq)
        ha_candles = longa[0]["abertura_em"] <= t_aq
        # "Quando o historico permite": as 4 prontas no 1o dia do aquecimento.
        permite = ha_candles and prontas(tab_c.get(longa[s_aq]["abertura_em"] // DIA_MS - 1))
        s0 = s_aq if permite else w0["i_ini"]
        r1c["aquecimento_motivo"] = ("91 dias" if permite else
                                     "sem aquecimento: no 1o dia dele nem todas as regras teriam sinal" if ha_candles
                                     else "sem aquecimento: o cache nao cobre 91 dias antes da 1a janela")
        fim_sim = validas[-1]["i_fim"]
        r1c["inicio_sim"] = _iso(longa[s0]["abertura_em"])
        r1c["aquecimento_dias"] = (t_ini_jan - longa[s0]["abertura_em"]) / DIA_MS
        cont = longa[s0:fim_sim]
        cfg = CONFIGS["corrigida"]
        corridas = {}
        for x, hora in VARIANTES_R3:
            chave = f"x{x}_h{hora:02d}"
            r1c["variantes"][chave] = {}
            for cid, fam, com_alvo in CARTEIRAS:
                cart = _nova(cid, fam, com_alvo, tab_c, cfg, atraso=x, hora=hora)
                res = rodar(cont, cart)
                mtm, pos, trades, ops = extrair(res, cart, len(cont))
                if (x, hora) == BASE:
                    corridas[cid] = (mtm, pos, trades, ops)
                for w in validas:
                    m = metricas_recorte(mtm, pos, trades, ops, w["i_ini"] - s0, w["i_fim"] - s0)
                    if (x, hora) != BASE:
                        m.pop("trades")
                        m["motivos"] = {}
                        for t in trades:
                            if w["i_ini"] - s0 <= t["i_saida"] < w["i_fim"] - s0:
                                m["motivos"][t["motivo"]] = m["motivos"].get(t["motivo"], 0) + 1
                    r1c["variantes"][chave].setdefault(w["j"], {})[cid] = m
        r1c["extra"] = _extras_r1c(corridas, cont, longa, s0, validas)

        # Aquecimento parcial (so descritivo): onde o historico nao permite os
        # 91 dias com as 4 prontas, a simulacao comeca mesmo assim 91 dias
        # antes; quem nao esta pronta fica em caixa ate estar.
        if not permite and ha_candles:
            cont_p = longa[s_aq:fim_sim]
            parcial = {}
            for cid, fam, com_alvo in CARTEIRAS:
                cart = _nova(cid, fam, com_alvo, tab_c, cfg)
                res = rodar(cont_p, cart)
                mtm, pos, trades, ops = extrair(res, cart, len(cont_p))
                for w in validas:
                    m = metricas_recorte(mtm, pos, trades, ops, w["i_ini"] - s_aq, w["i_fim"] - s_aq)
                    m.pop("trades")
                    parcial.setdefault(w["j"], {})[cid] = m
            r1c["parcial"] = {"inicio_sim": _iso(longa[s_aq]["abertura_em"]), "janelas": parcial}
    saida["r1c"] = r1c

    # ---- R2 (o --continuo exploratorio: 2 anos seguidos, comeca em caixa na 1a janela)
    r2 = {"configs": {}, "valida": False}
    cont2 = longa[base : base + N_JANELAS * H]
    if len(cont2) >= N_JANELAS * H * 0.95:
        primeiro_dia = cont2[0]["abertura_em"] // DIA_MS - 1
        r2["var_pct"] = (cont2[-1]["fechamento"] / cont2[0]["abertura"] - 1) * 100
        for nome_cfg, cfg in CONFIGS.items():
            tb = tabelas[cfg["tabela"]]
            if not prontas(tb.get(primeiro_dia)):
                continue
            r2["configs"][nome_cfg] = {}
            for cid, fam, com_alvo in CARTEIRAS:
                cart = _nova(cid, fam, com_alvo, tb, cfg)
                res = rodar(cont2, cart)
                r2["configs"][nome_cfg][cid] = res.metricas["retorno_total_pct"]
                if nome_cfg == "corrigida":
                    r2["valida"] = True
                    det = metricas_janela_isolada(res, cart, cont2)
                    mtm, pos, trades, ops = extrair(res, cart, len(cont2))
                    fech = [c["fechamento"] for c in cont2]
                    semente = f"VAL-6c-{fim_txt}{cid}{ativo}"
                    pct, arr, obs, amostra = faixa_da_sorte(fech, pos, semente)
                    det["sorte"] = {"percentil": pct, "arranjos_log10": round(math.log10(arr), 2) if arr > 0 else None,
                                    "sem_resolucao": arr < 125, "log_obs": obs}
                    if ativo in ("BTCUSDT", "ETHUSDT"):
                        det["sorte"]["amostra"] = [round(float(v), 6) for v in amostra]
                    det["diario"] = _serie_diaria(cont2, mtm)
                    r2.setdefault("det", {})[cid] = det
        if r2["valida"]:
            r2["bh"] = grade_bh(cont2)
            r2["bh_diario"] = _serie_diaria(cont2, [c["fechamento"] for c in cont2])
    saida["r2"] = r2
    saida["segundos"] = round(time.time() - t0, 1)
    return saida


def _diagnostico(tabelas, L, longa, validas):
    """
    Onde as correcoes 16.4-1 a 16.4-3 podem mexer, dia a dia, para a R0b
    explicar tambem as celulas que NAO mudaram: sinais diferentes entre a
    tabela exploratoria e a corrigida, maior diferenca relativa de ATR e de
    N, e dias em que a G2 teria compra e saida no mesmo dia (o unico caso
    em que a guarda de saida morde).
    """
    te, tc = tabelas["exploratoria"], tabelas["corrigida"]
    dias_medidos = set()
    for w in validas:
        a = longa[w["i_ini"]]["abertura_em"] // DIA_MS - 1
        b = longa[w["i_fim"] - 1]["abertura_em"] // DIA_MS
        dias_medidos.update(range(a, b))
    d0 = (L["janelas"] - AQUECIMENTO_R1C_DIAS * DIA_MS) // DIA_MS - 1
    out = {"dias_comparados": 0, "sinais_diferentes": 0, "sinais_diferentes_em_janela_medida": 0,
           "sinal_pronto_so_numa": 0, "sinal_pronto_so_numa_em_janela_medida": 0,
           "sinal_oposto_com_as_duas_prontas": 0, "sinal_oposto_com_as_duas_prontas_em_janela_medida": 0,
           "atr_disponivel_so_numa": 0, "atr_disponivel_so_numa_em_janela_medida": 0,
           "max_dif_rel_atr": 0.0, "max_dif_rel_n": 0.0, "g2_compra_e_saida_no_mesmo_dia": 0}
    chaves = ("reguas", "tartarugas", "rsi2")
    for d, x in tc.items():
        if d < d0:
            continue
        if x["rsi2"] is not None and x["rsi2"][0] and x["rsi2"][1]:
            out["g2_compra_e_saida_no_mesmo_dia"] += 1
        y = te.get(d)
        if y is None:
            continue
        out["dias_comparados"] += 1
        medido = d in dias_medidos
        if any(x[k] != y[k] for k in chaves):
            out["sinais_diferentes"] += 1
            out["sinais_diferentes_em_janela_medida"] += medido
            # Separa "uma tabela ainda nao tem historico" (a exploratoria so
            # tem o arquivo de 260 dias) de "as duas prontas e sinal oposto".
            if any((x[k] is None) != (y[k] is None) for k in chaves):
                out["sinal_pronto_so_numa"] += 1
                out["sinal_pronto_so_numa_em_janela_medida"] += medido
            if any(x[k] is not None and y[k] is not None and x[k] != y[k] for k in chaves):
                out["sinal_oposto_com_as_duas_prontas"] += 1
                out["sinal_oposto_com_as_duas_prontas_em_janela_medida"] += medido
        if (x["atr_pct"] is None) != (y["atr_pct"] is None):
            out["atr_disponivel_so_numa"] += 1
            out["atr_disponivel_so_numa_em_janela_medida"] += d in dias_medidos
        for k, nome in (("atr_pct", "max_dif_rel_atr"), ("n", "max_dif_rel_n")):
            if x[k] and y[k]:
                out[nome] = max(out[nome], abs(x[k] / y[k] - 1.0))
    return out


def _serie_diaria(candles, valores):
    """Valor no fechamento do ultimo candle de cada dia UTC: [(dia, valor)]."""
    out = []
    for i, c in enumerate(candles):
        d = c["abertura_em"] // DIA_MS
        if i + 1 == len(candles) or candles[i + 1]["abertura_em"] // DIA_MS != d:
            out.append([d, round(float(valores[i]), 6)])
    return out


def _extras_r1c(corridas, cont, longa, s0, validas):
    """
    So no caso-base do R1c, so nas janelas medidas:
    - G1: ganho deixado na mesa (preco 10 e 30 dias depois de cada saida
      pelo alvo) e a decomposicao de cada saida pelo alvo contra a T1 (12.3);
    - T2 x T1: horas em que so a T1 esta comprada e o que ela ganha nelas;
    - perda realizada nas saidas por stop (vem das operacoes, no relatorio).
    """
    medidas = [(w["j"], w["i_ini"] - s0, w["i_fim"] - s0) for w in validas]

    def janela_de(i):
        for j, a, b in medidas:
            if a <= i < b:
                return j
        return None

    _, pos_t1, trades_t1, _ = corridas["T1"]
    _, pos_g1, trades_g1, _ = corridas["G1"]
    abre = [c["abertura"] for c in longa]
    decomposicao, mesa = [], []
    for k, t in enumerate(trades_g1):
        if t["motivo"] != MOTIVO_ALVO:
            continue
        j = janela_de(t["i_saida"])
        if j is None:
            continue
        a = t["i_saida"]                  # indice (na simulacao) do preenchimento da venda no alvo
        p_alvo = t["p_saida"]
        g = s0 + a                        # indice na serie longa
        item = {"j": j, "p_alvo": p_alvo}
        for dias in (10, 30):
            gi = g + dias * 24
            item[f"var_{dias}d"] = (abre[gi] / p_alvo - 1.0) if gi < len(abre) else None
        mesa.append(item)
        # a operacao da T1 que contem o instante da venda da G1
        t1 = next((x for x in trades_t1 if x["i_entrada"] <= a <= x["i_saida"]), None)
        recompra = trades_g1[k + 1] if k + 1 < len(trades_g1) else None
        if t1 is None:
            decomposicao.append({"j": j, "tipo": "T1 fora", "custo_log": None})
        elif recompra is not None and recompra["i_entrada"] < t1["i_saida"]:
            decomposicao.append({"j": j, "tipo": "recomprou",
                                 "custo_log": math.log(recompra["p_entrada"] / p_alvo) + 2 * TAXA})
        else:
            decomposicao.append({"j": j, "tipo": "nao recomprou",
                                 "custo_log": math.log(t1["p_saida"] / p_alvo)})

    _, pos_t2, _, _ = corridas["T2"]
    fech = [c["fechamento"] for c in cont]
    t2t1 = {}
    for j, a, b in medidas:
        so_t1 = ambas = so_t2 = 0
        lr_so_t1 = 0.0
        for h in range(a, b):
            if pos_t1[h] and not pos_t2[h]:
                so_t1 += 1
                if h > 0:
                    lr_so_t1 += math.log(fech[h] / fech[h - 1])
            elif pos_t1[h] and pos_t2[h]:
                ambas += 1
            elif pos_t2[h]:
                so_t2 += 1
        t2t1[j] = {"horas": b - a, "so_t1": so_t1, "ambas": ambas, "so_t2": so_t2, "lr_so_t1": lr_so_t1}
    return {"decomposicao": decomposicao, "mesa": mesa, "t2_t1": t2t1}


# ---------------------------------------------------------------- R0 e principal

def conferir_r0(resultados):
    """A T1 (R1, corrigida) contra o efeito_stop "com stop", nas janelas comuns."""
    comuns, falhas, maior = 0, [], 0.0
    for r in resultados:
        for j, e in r["r0"].items():
            t1 = r["r1"]["corrigida"].get(j, {}).get("T1")
            if t1 is None:
                continue
            comuns += 1
            dif = abs(t1 - e["com"])
            maior = max(maior, dif)
            if dif > 0.01 + 1e-9:
                falhas.append((r["periodo"], r["ativo"], j, t1, e["com"]))
    return {"janelas_comuns": comuns, "maior_dif": round(maior, 4), "falhas": falhas, "ok": not falhas and comuns > 0}


def main():
    import argparse
    from multiprocessing import Pool
    ap = argparse.ArgumentParser()
    ap.add_argument("--processos", type=int, default=4)
    ap.add_argument("--periodos", nargs="*", default=list(PERIODOS))
    ap.add_argument("--ativos", nargs="*", default=list(ATIVOS))
    ap.add_argument("--saida", default=str(SAIDA))
    args = ap.parse_args()

    n, h = manifesto_do_cache()
    print(f"cache: {n} arquivos .json, manifesto {h[:16]}... "
          f"{'confere com o pre-registro' if h == MANIFESTO_CACHE else 'DIFERE do pre-registro'}")
    if h != MANIFESTO_CACHE:
        raise SystemExit("o cache mudou depois do pre-registro; parei")

    tarefas = [(p, a) for p in args.periodos for a in args.ativos]
    t0 = time.time()
    resultados = []
    if args.processos > 1:
        with Pool(args.processos) as pool:
            for r in pool.imap_unordered(estudar, tarefas):
                resultados.append(r)
                print(f"  {r['periodo']} {r['ativo']}: {r['segundos']} s", flush=True)
    else:
        for t in tarefas:
            r = estudar(t)
            resultados.append(r)
            print(f"  {r['periodo']} {r['ativo']}: {r['segundos']} s", flush=True)
    ordem = {(p, a): i for i, (p, a) in enumerate(tarefas)}
    resultados.sort(key=lambda r: ordem[(r["periodo"], r["ativo"])])
    print(f"simulacoes em {time.time() - t0:.0f} s")

    r0 = conferir_r0(resultados)
    print(f"\nR0: T1 do harness x efeito_stop_catastrofe ('com stop'): {r0['janelas_comuns']} janelas comuns, "
          f"maior |dif| {r0['maior_dif']:.4f} pt -> {'REPRODUZ' if r0['ok'] else 'NAO REPRODUZ'}")
    Path(args.saida).parent.mkdir(parents=True, exist_ok=True)
    raiz = Path(__file__).resolve().parent.parent
    codigo = {n: hashlib.sha256((raiz / n).read_bytes()).hexdigest() for n in ARQUIVOS_DE_CODIGO}
    Path(args.saida).write_text(json.dumps({
        "gerado_em": datetime.now(timezone.utc).isoformat(),
        "manifesto_cache": h, "periodos": args.periodos, "ativos": args.ativos, "sha256_codigo": codigo,
        "variantes_r3": [f"x{x}_h{hr:02d}" for x, hr in VARIANTES_R3],
        "r0": r0, "resultados": resultados,
    }, ensure_ascii=False), encoding="utf-8")
    print(f"resultado bruto em {args.saida}")
    if not r0["ok"]:
        for f in r0["falhas"][:20]:
            print("   falha:", f)
        raise SystemExit("R0 falhou: o harness mudou a regra da T1. PARE -- nada deste estudo pode ser lido.")


if __name__ == "__main__":
    main()
