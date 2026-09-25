"""
Estatistica e leitura do backtest confirmatorio das carteiras de regra
(`backtest/PRE_REGISTRO_6_CARTEIRAS.md`, secoes 12.2 a 12.5).

    python backend/backtest/estudo_carteiras.py     # antes: gera o bruto
    python backend/backtest/analise_carteiras.py    # le o bruto e escreve o relatorio

Le `resultados/carteiras_confirmatorio.json` e os 6 logs exploratorios de
antes do commit do pre-registro (`resultados/logs_exploratorios/`, cada um
conferido pelo sha256 registrado no pre-registro). Escreve
`resultados/relatorio_carteiras.md` e `resultados/analise_carteiras.json`.

Nada aqui escolhe parametro. As decisoes de leitura que a especificacao
deixa em aberto estao fixadas e escritas no relatorio (secao "Convencoes
desta leitura"), antes das tabelas.

Precisa de scipy (so no ambiente local; o CI nao roda este estudo).
"""

import hashlib
import json
import math
import re
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from scipy import stats

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backtest.estudo_carteiras import (  # noqa: E402
    BASE, CARTEIRAS, MOTIVO_ALVO, MOTIVO_FIM, MOTIVO_REPIQUE, MOTIVO_STOP, MOTIVO_STOP_2N,
    MOTIVO_TENDENCIA, PASTA, PERIODOS, SAIDA, TAXA,
)

RELATORIO = PASTA / "relatorio_carteiras.md"
ANALISE = PASTA / "analise_carteiras.json"
PASTA_LOGS = PASTA / "logs_exploratorios"
# Pre-registro, "Situacao": sha256 dos 6 logs exploratorios.
HASHES_LOGS = {
    "carteiras_2026-09-01.log": "1a03d5322fe75eb887b38e43ee2202a3a02c1060136162a8fc9c228ce5b958a2",
    "carteiras_2026-09-01_continuo.log": "3b99a57a00b88bec349a8d7a2a3c0006533f2aee1d57dab25acd1339de7fa358",
    "carteiras_2024-09-03.log": "1112d8dc60471fdb6ee28d04604b2a908df25647a147a888a5b4bab4960355d5",
    "carteiras_2024-09-03_continuo.log": "f599ebf92960b22fc4d1b5632175abbb8d86f2e3a5612935262ae1903768fbbc",
    "carteiras_2022-09-03.log": "d4708624bb09f2e563dadebe2d525f03c64c8c6723e9f118611e14c5350ef956",
    "carteiras_2022-09-03_continuo.log": "daecc0ff0063937bb29cb94d265a6af852a84948547a2ac0ca3b36da82a44a24",
}
# Pre-registro, "Situacao": sha256 do codigo congelado no commit.
HASHES_CODIGO_PREREG = {
    "backtest/estudo_carteiras.py": "c98e327993e2fe96e726b6a47ce2f6b953180b0693f6a1043767180582ef9dda",
    "estrategia/alvo.py": "1437c7f3831a3a5f7b581f25085741684985255394ed1f3228a2e1334a180794",
    "estrategia/indicadores.py": "855e01f06cd364d411f323536a53aa2def88e40573fcde0e32422ab6e867416f",
    "estrategia/rsi2.py": "63bc8a4434bd5dcc55ac908fb99ae38bec9726f6b28a6fbe5dee181dba4b70db",
    "estrategia/tartarugas.py": "855b1e7053535616eb3fafd0f71e49411adc92e6895e662c9fac385581adb674",
}
NOTA_HASH = {
    "backtest/estudo_carteiras.py": "esperado; é o harness com as correções da 16.4 e o que faltava (R0, R0b, R1c, R3). "
                                    "A configuração \"exploratória\" dele reproduz os 6 logs (seção 4)",
    "estrategia/alvo.py": "o arquivo foi alterado às 16:43 de 24/09, depois do cálculo do hash, e não há cópia da versão "
                          "registrada para comparar linha a linha. A mudança esperada é a 16.4-3 (`DIAS_MINIMOS = 150` em `atr_pct`). "
                          "O resto do que o harness usa dele (`ALVO_EM_ATR`, `ATR_N`, `nivel_de_alvo`, `MOTIVO_ALVO`) se comporta como "
                          "na versão exploratória: a G1 da configuração exploratória reproduz os logs (seção 4)",
}
NOTA_HASH["estrategia/tendencia_diaria.py"] = ("é versionado (a regra da T1). Em 25/09 a cópia de trabalho diferia do último commit só numa "
                                               "linha de docstring; a regra é conferida a cada rodada pelo R0")
NOTA_HASH["backtest/engine.py"] = "é versionado (o motor) e, em 25/09, igual ao último commit"
NOTA_HASH["backtest/efeito_stop_catastrofe.py"] = "é versionado (a referência do R0) e, em 25/09, igual ao último commit"
IDS = [c[0] for c in CARTEIRAS]
NOMES = {"T1": "Réguas", "T2": "Tartarugas", "G1": "Réguas com meta", "G2": "Repique"}
GRADE = [i / 200 for i in range(201)]
ANOS_JANELA = 91 / 365.25
ALFA = 0.05
PIOR = "x6_h05"
X2 = "x2_h01"
BASE_TXT = f"x{BASE[0]}_h{BASE[1]:02d}"
ROTULO_VAR = {"x0_h01": "base (x = 0, 01:00)", "x2_h01": "x = 2, 01:00", "x6_h01": "x = 6, 01:00",
              "x0_h05": "x = 0, 05:00", "x2_h05": "x = 2, 05:00", "x6_h05": "x = 6, 05:00 (pior caso)"}
CORRECOES = {
    "so_1_guarda": "16.4-1 (guarda de saída)",
    "so_2_janela300": "16.4-2 (janela de 300 dias)",
    "so_3_atr150": "16.4-3 (ATR só com 150 dias)",
    "so_3b_atr_so_g1": "3b (ATR exigido só na G1)",
}
# (id, descricao, carteira, referencia, lado)
HIPOTESES = (
    ("H1", "T2 > b&h f_dd", "T2", "bhf", "maior"),
    ("H2", "G2 > b&h f_dd", "G2", "bhf", "maior"),
    ("H3", "G1 ≠ T1", "G1", "T1", "bicaudal"),
    ("H4", "G2 ≠ T1", "G2", "T1", "bicaudal"),
)
FRASE_ACASO = "sob acaso, 50% das estratégias sem vantagem passam neste critério"


# ---------------------------------------------------------------- formatacao

def f(x, casas=2, sinal=True):
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "—"
    s = f"{x:+.{casas}f}" if sinal else f"{x:.{casas}f}"
    return s.replace("-", "−").replace(".", ",")


def pct(x, casas=0):
    return "—" if x is None else f"{x * 100:.{casas}f}%".replace(".", ",")


def pv(p):
    if p is None or (isinstance(p, float) and math.isnan(p)):
        return "—"
    return f"{p:.4f}".replace(".", ",") if p >= 0.0001 else "< 0,0001"


def tabela(cab, linhas):
    out = ["| " + " | ".join(cab) + " |", "|" + "|".join("---" for _ in cab) + "|"]
    out += ["| " + " | ".join(str(c) for c in l) + " |" for l in linhas]
    return "\n".join(out)


# ---------------------------------------------------------------- dados

def carregar():
    dados = json.loads(SAIDA.read_text(encoding="utf-8"))
    if not dados["r0"]["ok"]:
        raise SystemExit("R0 falhou no bruto: nada deste estudo pode ser lido (secao 12.2).")
    return dados


def registros(dados, fonte, variante=BASE_TXT):
    """Uma linha por (periodo, ativo, janela, carteira), com a grade do b&h da janela."""
    out = []
    for r in dados["resultados"]:
        jv = {w["j"]: w for w in r["janelas"] if w["valida"]}
        if fonte == "R1":
            tab = r["r1_det"]
        elif fonte == "R1c":
            tab = r["r1c"]["variantes"].get(variante, {})
        elif fonte == "R1c_parcial":
            tab = r["r1c"].get("parcial", {}).get("janelas", {})
        else:
            raise ValueError(fonte)
        for js, por in tab.items():
            j = int(js)
            for c, m in por.items():
                out.append({"p": r["periodo"], "a": r["ativo"], "j": j, "c": c, **m, "bh": jv[j]["bh"],
                            "regime": jv[j]["regime"]})
    return out


class Leitura:
    """Registros de uma rodada (R1, R1c, uma variante do R3) com as referencias por periodo."""

    def __init__(self, regs):
        self.regs = regs
        self.idx = {(l["p"], l["a"], l["j"], l["c"]): l for l in regs}
        self.k_dd, self.k_expo = {}, {}
        for p in PERIODOS:
            for c in IDS:
                L = self.de(c, p)
                if not L:
                    continue
                dd = statistics.mean(l["dd"] for l in L)
                self.k_dd[(p, c)] = min(range(len(GRADE)),
                                        key=lambda k: abs(statistics.mean(l["bh"][k][1] for l in L) - dd))
                expo = statistics.mean(l["expo"] for l in L)
                self.k_expo[(p, c)] = round(expo * 200)

    def de(self, c, p=None):
        return [l for l in self.regs if l["c"] == c and (p is None or l["p"] == p)]

    def blocos(self):
        b = defaultdict(set)
        for l in self.regs:
            b[(l["p"], l["j"])].add(l["a"])
        return {k: sorted(v) for k, v in sorted(b.items(), key=lambda kv: (PERIODOS.index(kv[0][0]), kv[0][1]))}

    def ret_ref(self, l, ref, c):
        """Retorno (fracao) da referencia na janela da linha l."""
        if ref == "bhf":
            return l["bh"][self.k_dd[(l["p"], c)]][0] / 100
        if ref == "bhexpo":
            return l["bh"][self.k_expo[(l["p"], c)]][0] / 100
        if ref == "bh100":
            return l["bh"][200][0] / 100
        return self.idx[(l["p"], l["a"], l["j"], ref)]["r"]

    def deltas(self, c, ref):
        """
        Por bloco (periodo, janela): Delta = 100 [ln(1 + r_c) - ln(1 + r_ref)],
        com os retornos medios dos ativos do bloco. Devolve tambem a
        diferenca simples em % por bloco.
        """
        out = []
        for (p, j), ativos in self.blocos().items():
            L = [self.idx[(p, a, j, c)] for a in ativos if (p, a, j, c) in self.idx]
            if not L:
                continue
            rc = statistics.mean(l["r"] for l in L)
            rr = statistics.mean(self.ret_ref(l, ref, c) for l in L)
            out.append({"p": p, "j": j, "n": len(L), "log": 100 * (math.log1p(rc) - math.log1p(rr)),
                        "simples": 100 * (rc - rr)})
        return out

    def regua_antiga(self, c, ref, p=None):
        """Media por janela (ativo x janela) da diferenca simples em %: a regua da T1."""
        L = self.de(c, p)
        return statistics.mean(100 * (l["r"] - self.ret_ref(l, ref, c)) for l in L) if L else None

    def por_regime(self, c, ref):
        """Media por janela (ativo x janela) da diferenca simples em % contra a referencia, por regime do ativo na janela."""
        out = {}
        for reg in ("alta", "lateral", "baixa"):
            L = [l for l in self.de(c) if l["regime"] == reg]
            if L:
                difs = [100 * (l["r"] - self.ret_ref(l, ref, c)) for l in L]
                out[reg] = {"n": len(L), "dif": statistics.mean(difs), "mediana": statistics.median(difs)}
        return out

    def janelas_iguais(self, c1, c2):
        L = self.de(c1)
        iguais = sum(1 for l in L if l["r"] == self.idx[(l["p"], l["a"], l["j"], c2)]["r"])
        return iguais, len(L)


# ---------------------------------------------------------------- testes (12.4)

def testar(d, lado):
    d = np.asarray(d, dtype=float)
    alt = "greater" if lado == "maior" else "two-sided"
    n = len(d)
    media = float(d.mean())
    dp = float(d.std(ddof=1))
    ep = dp / math.sqrt(n)
    tq = stats.t.ppf(0.95, n - 1)
    zeros = int((d == 0).sum())
    ties = len(np.unique(np.abs(d[d != 0]))) < int((d != 0).sum())
    if zeros == n:
        pw = float("nan")
    else:
        pw = float(stats.wilcoxon(d, zero_method="pratt", alternative=alt, method="auto").pvalue)
    pt = float(stats.ttest_1samp(d, 0.0, alternative=alt).pvalue) if dp > 0 else float("nan")
    pos, neg = int((d > 0).sum()), int((d < 0).sum())
    ps = float(stats.binomtest(pos, pos + neg, 0.5, alternative=alt).pvalue) if pos + neg else float("nan")
    return {
        "n": n, "media": media, "ic90": [media - tq * ep, media + tq * ep], "mediana": float(np.median(d)),
        "aparada5": float(stats.trim_mean(d, 0.05)), "dp": dp, "p_wilcoxon": pw, "p_t": pt,
        "p": max(pw, pt) if not (math.isnan(pw) or math.isnan(pt)) else float("nan"),
        "metodo_wilcoxon": "exato" if zeros == 0 and not ties else "normal com ajuste de Pratt",
        "zeros": zeros, "positivos": pos, "negativos": neg, "p_sinal": ps,
    }


def holm(ps, alfa=ALFA):
    """Holm-Bonferroni: {h: (rejeita, p ajustado)}."""
    ordem = sorted(ps, key=lambda h: ps[h])
    m = len(ordem)
    saida, parou, acum = {}, False, 0.0
    for i, h in enumerate(ordem):
        acum = max(acum, min(1.0, (m - i) * ps[h]))
        rej = not parou and ps[h] <= alfa / (m - i)
        if not rej:
            parou = True
        saida[h] = (rej, acum)
    return saida


def por_periodo(deltas):
    out = {}
    for p in PERIODOS:
        v = [d["log"] for d in deltas if d["p"] == p]
        if v:
            out[p] = {"mediana": float(np.median(v)), "media": float(np.mean(v)), "n": len(v)}
    return out


# ---------------------------------------------------------------- R0b

PADRAO_LINHA = re.compile(r"^\s+(\w+USDT) j(\d) (\w+)\s+b&h\s+([+-]?\d+\.\d)%\s+T1\s+([+-]?\d+\.\d+)\s+T2\s+"
                          r"([+-]?\d+\.\d+)\s+G1\s+([+-]?\d+\.\d+)\s+G2\s+([+-]?\d+\.\d+)")
PADRAO_FORA = re.compile(r"^\s+(\w+USDT) j(\d) fora")


def ler_log(nome):
    arq = PASTA_LOGS / nome
    bruto = arq.read_bytes()
    h = hashlib.sha256(bruto).hexdigest()
    if h != HASHES_LOGS[nome]:
        raise SystemExit(f"{nome}: sha256 {h} difere do pre-registro; nao da para usar na R0b")
    valores, fora = {}, set()
    for linha in bruto.decode("utf-8").splitlines():
        m = PADRAO_LINHA.match(linha)
        if m:
            valores[(m.group(1), int(m.group(2)))] = {c: float(m.group(5 + i)) for i, c in enumerate(IDS)}
            continue
        m = PADRAO_FORA.match(linha)
        if m:
            fora.add((m.group(1), int(m.group(2))))
    return valores, fora


def r0b(dados):
    """Compara o harness (exploratorio e corrigido) com os logs e atribui cada diferenca."""
    saida = {"celulas": 0, "exploratoria_reproduz": 0, "exploratoria_difere": [], "diferencas": [],
             "sem_explicacao": 0, "janelas_log": 0, "janelas_fora_log": 0, "janelas_divergentes": []}
    for p in PERIODOS:
        for modo in ("janelas", "continuo"):
            nome = f"carteiras_{p}{'_continuo' if modo == 'continuo' else ''}.log"
            valores, fora = ler_log(nome)
            if modo == "janelas":
                saida["janelas_log"] += len(valores)
                saida["janelas_fora_log"] += len(fora)
            for r in dados["resultados"]:
                if r["periodo"] != p:
                    continue
                a = r["ativo"]
                if modo == "janelas":
                    cfgs = {k: {int(j): v for j, v in r["r1"][k].items()} for k in r["r1"]}
                    js = range(8)
                else:
                    cfgs = {k: {0: v} for k, v in r["r2"]["configs"].items()}
                    js = [0]
                corr = cfgs.get("corrigida", {})
                for j in js:
                    no_log = (a, j) in valores
                    no_fora = (a, j) in fora
                    no_corr = j in corr
                    if (no_log or no_fora or no_corr) and not ((no_log and no_corr) or (no_fora and not no_corr)):
                        saida["janelas_divergentes"].append((p, modo, a, j, no_log, no_corr))
                    if not (no_log and no_corr):
                        continue
                    for c in IDS:
                        saida["celulas"] += 1
                        v_log = valores[(a, j)][c]
                        v_exp = cfgs["exploratoria"][j][c]
                        v_cor = cfgs["corrigida"][j][c]
                        if abs(v_exp - v_log) < 0.005:
                            saida["exploratoria_reproduz"] += 1
                        else:
                            saida["exploratoria_difere"].append((p, modo, a, j, c, v_log, v_exp))
                        if abs(v_cor - v_log) < 0.005:
                            continue
                        mudam = [k for k in CORRECOES if abs(cfgs[k][j][c] - v_exp) >= 0.005]
                        reproduz = [k for k in mudam if abs(cfgs[k][j][c] - v_cor) < 0.005]
                        if reproduz:
                            causa = " ou ".join(CORRECOES[k] for k in reproduz)
                        elif mudam:
                            causa = "interação de " + " + ".join(CORRECOES[k] for k in mudam)
                        else:
                            causa = "SEM EXPLICAÇÃO"
                            saida["sem_explicacao"] += 1
                        saida["diferencas"].append({"periodo": p, "modo": modo, "ativo": a, "j": j, "carteira": c,
                                                    "log": v_log, "confirmatorio": v_cor, "causa": causa})
    return saida


# ---------------------------------------------------------------- metricas descritivas (12.3)

def resumo_carteira(leit, c, p=None, com_trades=True):
    L = leit.de(c, p)
    if not L:
        return None
    r = {
        "n": len(L),
        "ret_medio": statistics.mean(100 * l["r"] for l in L),
        "ret_mediano": statistics.median(100 * l["r"] for l in L),
        "log_medio": statistics.mean(100 * math.log1p(l["r"]) for l in L),
        "dd_medio": statistics.mean(l["dd"] for l in L),
        "expo": statistics.mean(l["expo"] for l in L),
        "ops_ano": statistics.mean(l["ops"] for l in L) / ANOS_JANELA,
    }
    r["custo_ano_pct"] = r["ops_ano"] * TAXA * 100
    ref = {}
    for nome in ("bh100", "bhf", "bhexpo"):
        ref[nome] = leit.regua_antiga(c, nome, p)
    r["vs"] = ref
    if p is not None:
        r["f_dd"] = GRADE[leit.k_dd[(p, c)]]
        r["f_expo"] = GRADE[leit.k_expo[(p, c)]]
    if com_trades and "trades" in L[0]:
        T = [t for l in L for t in l["trades"]]
        r["trades_janela"] = len(T) / len(L)
        r["trades_ano"] = r["trades_janela"] / ANOS_JANELA
        if T:
            rets = [t["ret"] * 100 for t in T]
            gan = [x for x in rets if x > 0]
            per = [x for x in rets if x <= 0]
            r["acerto"] = len(gan) / len(T)
            r["expectativa_media"] = statistics.mean(rets)
            r["expectativa_mediana"] = statistics.median(rets)
            r["ganho_medio"] = statistics.mean(gan) if gan else None
            r["perda_media"] = statistics.mean(per) if per else None
            mot = defaultdict(int)
            for t in T:
                mot[t["motivo"]] += 1
            r["motivos"] = dict(mot)
            stops = [t["ret_preco"] * 100 for t in T if t["motivo"] in (MOTIVO_STOP, MOTIVO_STOP_2N)]
            cat = [t["ret_preco"] * 100 for t in T if t["motivo"] == MOTIVO_STOP]
            r["stop_perda_media"] = statistics.mean(cat) if cat else None
            r["stop_perda_p90"] = float(np.percentile(cat, 10)) if cat else None
            s2n = [t["ret_preco"] * 100 for t in T if t["motivo"] == MOTIVO_STOP_2N]
            r["stop2n_perda_media"] = statistics.mean(s2n) if s2n else None
            r["stop2n_perda_p90"] = float(np.percentile(s2n, 10)) if s2n else None
            r["stops_todos"] = len(stops)
    else:
        mot = defaultdict(int)
        for l in L:
            for k, v in l.get("motivos", {}).items():
                mot[k] += v
        r["motivos"] = dict(mot)
    return r


# ---------------------------------------------------------------- analise principal

def avaliar(leituras, rot):
    """Testes, Holm, reguas e robustez para H1-H4 sobre o R1c (ou outra rodada em `rot`)."""
    base = leituras[rot]
    res = {}
    for h, desc, c, ref, lado in HIPOTESES:
        dl = base.deltas(c, ref)
        t = testar([d["log"] for d in dl], lado)
        t["por_periodo"] = por_periodo(dl)
        t["simples_media_blocos"] = statistics.mean(d["simples"] for d in dl)
        t["regua_antiga"] = base.regua_antiga(c, ref)
        t["regua_antiga_por_periodo"] = {p: base.regua_antiga(c, ref, p) for p in PERIODOS}
        t["deltas"] = dl
        if ref == "T1":
            t["janelas_iguais"] = base.janelas_iguais(c, "T1")
        rob = {}
        for v, lv in leituras.items():
            if v in (rot, "R1", "R1c_parcial") or not v.startswith("x"):
                continue
            dv = lv.deltas(c, ref)
            rob[v] = {"por_periodo": por_periodo(dv), "media": statistics.mean(d["log"] for d in dv),
                      "mediana": float(np.median([d["log"] for d in dv]))}
        t["r3"] = rob
        res[h] = t
    hl = holm({h: res[h]["p"] for h in res})
    for h in res:
        res[h]["holm_rejeita"], res[h]["p_holm"] = hl[h]
    return res


def sinais_no_periodo(rob_var, sentido):
    """Em quantos periodos a mediana dos 8 blocos da variante tem o sinal pedido."""
    return sum(1 for p, v in rob_var["por_periodo"].items() if (v["mediana"] > 0 if sentido > 0 else v["mediana"] < 0))


def classificar(h, lado, t):
    """
    Criterios da 12.5, na ordem da tabela. Devolve (resposta, [por que]).
    As condicoes de "Sim" e de "Nao, custa dinheiro" sao as mesmas, com o
    sentido trocado; quando nenhuma das duas fecha, a lista diz o que faltou
    no sentido para onde a media aponta.
    """
    if t["mediana"] == 0:
        return "Sem efeito detectável", [f"a mediana dos blocos é exatamente 0 ({t['zeros']} de {t['n']} blocos com Δ = 0)"]
    if lado == "maior" and not t["holm_rejeita"]:
        return "Sem evidência de vantagem", [f"o Holm não rejeita (p = {pv(t['p'])}; p ajustado = {pv(t['p_holm'])})"]

    def falhas_no_sentido(s):
        nome = "a favor da carteira" if s > 0 else "contra a carteira"
        out = []
        if not t["holm_rejeita"]:
            out.append(f"o Holm não rejeita (p = {pv(t['p'])}; p ajustado = {pv(t['p_holm'])})")
        if not t["media"] * s > 0:
            out.append(f"a média dos blocos ({f(t['media'])}) aponta o outro sentido")
        if not t["mediana"] * s > 0:
            out.append(f"a mediana dos blocos ({f(t['mediana'])}) aponta o outro sentido")
        if not (t["ic90"][0] * s > 0 and t["ic90"][1] * s > 0):
            out.append(f"o IC 90% [{f(t['ic90'][0])}; {f(t['ic90'][1])}] contém o zero")
        if not t["regua_antiga"] * s > 0:
            out.append(f"a régua antiga ({f(t['regua_antiga'])}) aponta o outro sentido")
        k_pior = sinais_no_periodo(t["r3"][PIOR], s)
        if k_pior < 2:
            out.append(f"no pior caso do R3 (x = 6, 05:00) o sinal se mantém em só {k_pior} de 3 períodos")
        if h == "H3":
            k_x2 = sinais_no_periodo(t["r3"][X2], s)
            if k_x2 < 2:
                out.append(f"com x = 2 o sinal se mantém em só {k_x2} de 3 períodos")
        return nome, out

    nome, fav = falhas_no_sentido(+1)
    if not fav:
        return "Sim", ["todas as condições da 12.5 a favor da carteira"]
    if lado == "bicaudal":
        nome_c, contra = falhas_no_sentido(-1)
        if not contra:
            return "Não, custa dinheiro", ["todas as condições da 12.5 no sentido contrário"]
        if t["media"] < 0:
            nome, fav = nome_c, contra
    return "Inconclusivo", [f"a média aponta {nome}, mas falta: " + "; ".join(fav)]


def extras_g1(dados):
    dec = defaultdict(lambda: defaultdict(list))
    mesa = defaultdict(lambda: {"10": [], "30": []})
    t2t1 = defaultdict(lambda: {"horas": 0, "so_t1": 0, "ambas": 0, "so_t2": 0, "lr": [], "t1_pos": 0})
    for r in dados["resultados"]:
        e = r["r1c"].get("extra")
        if not e:
            continue
        p = r["periodo"]
        for d in e["decomposicao"]:
            dec[p][d["tipo"]].append(d["custo_log"])
        for m in e["mesa"]:
            for k in ("10", "30"):
                if m[f"var_{k}d"] is not None:
                    mesa[p][k].append(m[f"var_{k}d"] * 100)
        for j, x in e["t2_t1"].items():
            z = t2t1[p]
            z["horas"] += x["horas"]
            z["so_t1"] += x["so_t1"]
            z["ambas"] += x["ambas"]
            z["so_t2"] += x["so_t2"]
            z["t1_pos"] += x["so_t1"] + x["ambas"]
            z["lr"].append(x["lr_so_t1"] * 100)
    return dec, mesa, t2t1


def sorte_combinada(dados):
    """Faixa da sorte (13.4) sobre o R2: por ativo e BTC+ETH combinados."""
    out = {}
    for p in PERIODOS:
        for c in IDS:
            por = {}
            for r in dados["resultados"]:
                if r["periodo"] == p and r["r2"].get("valida"):
                    por[r["ativo"]] = r["r2"]["det"][c]["sorte"]
            comb = None
            if "BTCUSDT" in por and "ETHUSDT" in por:
                b, e = por["BTCUSDT"], por["ETHUSDT"]
                if b["sem_resolucao"] or e["sem_resolucao"]:
                    comb = {"percentil": None, "nota": "sem resolução"}
                elif len(b["amostra"]) != len(e["amostra"]):
                    comb = {"percentil": None, "nota": "arranjos enumerados; não combinável"}
                else:
                    obs = (b["log_obs"] + e["log_obs"]) / 2
                    am = (np.array(b["amostra"]) + np.array(e["amostra"])) / 2
                    comb = {"percentil": float((am < obs).mean() * 100), "log_obs": obs}
            out[(p, c)] = {"por_ativo": {a: v["percentil"] for a, v in por.items()}, "combinado": comb}
    return out


def sigma_par(dados, sorteios=10000, bloco=30):
    """
    sigma do par T1 - G1 por ano: bootstrap em blocos moveis de 30 dias sobre a
    diferenca diaria de log-patrimonio do R2 (13.4), por ativo (BTC, ETH) e com
    BTC e ETH combinados (media dos dois, a unidade da leitura ao vivo).
    """
    series = defaultdict(list)
    for r in dados["resultados"]:
        if not r["r2"].get("valida") or r["ativo"] not in ("BTCUSDT", "ETHUSDT"):
            continue
        t1 = np.log([v for _, v in r["r2"]["det"]["T1"]["diario"]])
        g1 = np.log([v for _, v in r["r2"]["det"]["G1"]["diario"]])
        series[(r["periodo"], r["ativo"])] = np.diff(t1 - g1)
    out = {}
    semente = int.from_bytes(hashlib.sha256(b"VAL-6c-sigma_par").digest()[:8], "big")
    for nome, chaves in (("BTCUSDT", [k for k in series if k[1] == "BTCUSDT"]),
                         ("ETHUSDT", [k for k in series if k[1] == "ETHUSDT"]),
                         ("BTC+ETH", None)):
        if chaves is None:
            difs = [ (series[(p, "BTCUSDT")] + series[(p, "ETHUSDT")]) / 2
                     for p in PERIODOS if (p, "BTCUSDT") in series and (p, "ETHUSDT") in series]
        else:
            difs = [series[k] for k in chaves]
        blocos = [s[i:i + bloco] for s in difs for i in range(len(s) - bloco + 1)]
        rng = np.random.default_rng(semente)
        n_bl = math.ceil(365 / bloco)
        somas = np.empty(sorteios)
        for i in range(sorteios):
            esc = rng.integers(0, len(blocos), n_bl)
            somas[i] = np.concatenate([blocos[k] for k in esc])[:365].sum()
        diarios = np.concatenate(difs)
        out[nome] = {"sigma_ano_pts": float(somas.std(ddof=1) * 100),
                     "sigma_iid_ano_pts": float(diarios.std(ddof=1) * math.sqrt(365) * 100),
                     "media_ano_pts": float(diarios.mean() * 365 * 100), "dias": int(len(diarios))}
    return out


# ---------------------------------------------------------------- relatorio

def main():
    dados = carregar()
    leituras = {"R1": Leitura(registros(dados, "R1"))}
    for v in dados["variantes_r3"]:
        leituras[v] = Leitura(registros(dados, "R1c", v))
    # R1c com aquecimento parcial em 2022 (descritivo): troca so os blocos de 2022.
    parc = registros(dados, "R1c_parcial")
    base_regs = [l for l in leituras[BASE_TXT].regs if l["p"] not in {x["p"] for x in parc}]
    leituras["R1c_parcial"] = Leitura(base_regs + parc) if parc else None

    b = r0b(dados)
    conf = avaliar(leituras, BASE_TXT)
    desc_r1 = avaliar({"R1": leituras["R1"]}, "R1")
    parcial = avaliar({"R1c_parcial": leituras["R1c_parcial"]}, "R1c_parcial") if parc else None
    for h, _, c, ref, lado in HIPOTESES:
        conf[h]["resposta"], conf[h]["porque"] = classificar(h, lado, conf[h])

    dec, mesa, t2t1 = extras_g1(dados)
    sorte = sorte_combinada(dados)
    sig = sigma_par(dados)

    L = []
    w = L.append
    base = leituras[BASE_TXT]
    rs = {c: resumo_carteira(base, c) for c in IDS}
    w("# Backtest confirmatório das carteiras de regra (T1, T2, G1, G2)")
    w("")
    w(f"Gerado em {datetime.now(timezone.utc).strftime('%d/%m/%Y %H:%M UTC')} por `backend/backtest/analise_carteiras.py`, "
      f"a partir de `resultados/carteiras_confirmatorio.json` (gerado em {dados['gerado_em'][:16].replace('T', ' ')} UTC por "
      "`backend/backtest/estudo_carteiras.py`). Pré-registro: `backend/backtest/PRE_REGISTRO_6_CARTEIRAS.md`, seção 12. "
      "Nenhum parâmetro de regra foi mudado (12.1). Sem LLM e sem download: só o cache congelado.")
    w("")

    # ---------- respostas
    w("## 1. Respostas")
    w("")
    linhas = []
    for h, desc, c, ref, lado in HIPOTESES:
        t = conf[h]
        linhas.append([f"**{h}**", desc, f"**{t['resposta']}**", f(t["media"]), f"[{f(t['ic90'][0])}; {f(t['ic90'][1])}]",
                       f(t["mediana"]), pv(t["p"]), pv(t["p_holm"]), "sim" if t["holm_rejeita"] else "não"])
    w(tabela(["Hipótese", "Pergunta", "Resposta", "Média Δ (log, pts/janela)", "IC 90%", "Mediana Δ", "p (maior de Wilcoxon-Pratt e t)",
              "p ajustado (Holm)", "Holm rejeita a 5%?"], linhas))
    w("")
    w("Δ é a diferença por bloco de tempo (média dos ativos numa janela de 91 dias; 24 blocos) em pontos de log: "
      "`100·[ln(1+r_carteira) − ln(1+r_referência)]`, sobre o **R1c** (contínuo recortado nas janelas). "
      "Referência de H1 e H2: comprar-e-segurar de fração fixa `f_dd` (uma por período, a que iguala o drawdown médio da carteira). "
      "Referência de H3 e H4: a T1.")
    w("")
    for h, desc, c, ref, lado in HIPOTESES:
        t = conf[h]
        pp = "; ".join(f"{p[:4]}: {f(t['por_periodo'][p]['mediana'])}" for p in PERIODOS if p in t["por_periodo"])
        w(f"- **{h} ({desc}) — {t['resposta']}.** Média {f(t['media'])} pts por janela (IC 90% {f(t['ic90'][0])} a {f(t['ic90'][1])}), "
          f"mediana {f(t['mediana'])}, média aparada {f(t['aparada5'])}; mediana por período (fim do período) {pp}. "
          f"Régua antiga (média por janela, em %): {f(t['regua_antiga'])}. "
          f"Pior caso do R3 (x = 6, 05:00): média {f(t['r3'][PIOR]['media'])}, mediana {f(t['r3'][PIOR]['mediana'])}"
          + (f"; com x = 2: média {f(t['r3'][X2]['media'])}" if h == "H3" else "")
          + f". Por que esta resposta: {'; '.join(t['porque'])}."
          + (f" As réguas discordam no sinal (antiga {f(t['regua_antiga'])}; mediana nova {f(t['mediana'])}): pela 12.4 isso "
             "também levaria a \"inconclusivo\"; as duas leituras dizem a mesma coisa, que não há vantagem demonstrada."
             if lado == "maior" and t["resposta"] == "Sem evidência de vantagem" and (t["regua_antiga"] > 0) != (t["mediana"] > 0) else ""))
    w("")
    w("Em palavras:")
    w("")
    w(_em_palavras(conf, rs, base))
    w("")

    # ---------- convencoes
    w("## 2. Convenções desta leitura")
    w("")
    w("A especificação deixa alguns detalhes em aberto. Eles foram fechados assim, e valem para as 4 hipóteses. "
      "Nenhum deles mexe em regra de carteira (12.1); o que foi acrescentado depois de ver os números está marcado.")
    w("")
    w("1. **Aquecimento do R1c.** \"Quando o histórico permite\" = no 1º dia do aquecimento (91 dias antes da 1ª janela válida do ativo) "
      "as 4 carteiras já têm sinal pronto — a mesma guarda do R1. O cache congelado tem os arquivos dos 3 períodos, "
      "fundidos por `abertura_em` (cada candle repetido foi conferido idêntico entre arquivos). Em 2024-26 e 2022-24 há 393 dias antes da 1ª janela: "
      "aquecimento de 91 dias. Em 2020-22 o cache começa em 20/12/2019 (260 dias antes da 1ª janela): no 1º dia do aquecimento só haveria 169 dias, "
      "e o RSI(2) precisa de 220. Pela regra da 12.2, **o R1c de 2020-22 começa na 1ª janela** (a janela 0 de 2020-22 sai igual à do R1). "
      "Uma leitura descritiva com aquecimento parcial (começa 91 dias antes e a G2 fica em caixa até ter 220 dias) está na seção 8.")
    w("2. **Retorno de uma janela no R1c** = patrimônio marcado a mercado no fechamento do último candle da janela ÷ o do fechamento do candle anterior "
      "ao 1º da janela (sem liquidar; a última janela também é marcada a mercado). Drawdown medido dentro da janela, com o pico começando no patrimônio de entrada. "
      "A referência b&h de cada janela é a mesma do R1 (compra na abertura do 1º candle, vende no fechamento do último, 0,1% por ponta). "
      "Isso dá à carteira do R1c uma vantagem de até 0,2·f pt por janela contra o b&h-f (não paga a entrada nem a saída quando atravessa a fronteira comprada); "
      "com f entre 0,2 e 0,6, é no máximo 0,12 pt, muito abaixo de qualquer efeito que os 24 blocos detectam (seção 6).")
    w("3. **Régua antiga** (a da T1): média, sobre as janelas (ativo × janela), da diferença simples em % contra a referência. "
      "Em H1 e H2 a referência é o b&h de fração fixa `f_dd` do período; em H3 e H4 é a T1 (diferença simples G1 − T1 ou G2 − T1). "
      "\"Concorda\" = a média das janelas dos 3 períodos tem o mesmo sinal pedido. **Régua nova** = Δ em log por bloco; o pré-registro "
      "(\"Situação\", defesa 3) a descreve como a mediana em log, e a 12.5 pede média **e** mediana no sentido da resposta. "
      "*Nota acrescentada depois de ver os números:* numa hipótese unilateral em que o Holm não rejeita, a resposta é "
      "\"Sem evidência de vantagem\" (a linha da tabela da 12.5 que cobre esse caso), mesmo que as réguas discordem no sinal; "
      "a discordância é escrita junto da resposta, porque pela 12.4 ela levaria a \"inconclusivo\". As duas respostas dizem o mesmo: "
      "nenhuma vantagem demonstrada.")
    w("4. **Robustez do R3.** \"O sinal se mantém\" num período = a mediana dos 8 blocos daquele período, na variante, tem o sinal pedido "
      "(o estimador por período da 12.4). Em H1 e H2 o `f_dd` é recalculado com o drawdown da variante. Pior caso = stop/alvo com x = 6 e decisões às 05:00; "
      "em H3 também x = 2 (decisões às 01:00).")
    w("5. **Testes.** Wilcoxon de postos sinalizados com tratamento de Pratt para zeros (`scipy.stats.wilcoxon(zero_method='pratt', method='auto')`: "
      "exato sem zeros nem empates; com zeros, aproximação normal com o ajuste de Pratt/Cureton), t de uma amostra com 23 graus de liberdade, "
      "vale o maior p. H1 e H2 unilaterais (> 0); H3 e H4 bicaudais. Holm-Bonferroni com α familiar de 5% sobre H1–H4. Teste do sinal relatado como complementar.")
    w("6. **b&h 100%** = a grade do b&h com f = 1 (compra na abertura do 1º candle). O `f_dd` sai da grade de 0 a 100% em passos de 0,5%, como no estudo 2.")
    w("7. **Perda realizada no stop** = preço de saída ÷ preço de entrada − 1, só nas saídas por \"stop de catastrofe\"; p90 = o 10º percentil (a cauda ruim).")
    w("")

    # ---------- o que rodou
    w("## 3. O que rodou")
    w("")
    n_val = {p: sum(1 for r in dados["resultados"] if r["periodo"] == p for wj in r["janelas"] if wj["valida"]) for p in PERIODOS}
    n_fora = {p: [(r["ativo"], wj["j"], wj["motivo_fora"]) for r in dados["resultados"] if r["periodo"] == p for wj in r["janelas"] if not wj["valida"]] for p in PERIODOS}
    w(f"- Cache: manifesto `{dados['manifesto_cache']}` — **confere** com o hash do pré-registro. Nenhum download (o adaptador da Binance foi trocado por um que falha).")
    w(f"- Janelas válidas (R1 = R1c = R3): " + "; ".join(f"{p[:4]}: {n_val[p]}" for p in PERIODOS) + f"; total {sum(n_val.values())}. "
      "Excluídas pela guarda de aquecimento: " + (", ".join(f"{a} j{j} ({p[:4]})" for p in PERIODOS for a, j, _ in n_fora[p]) or "nenhuma") + ".")
    w(f"- Blocos de tempo: {len(base.blocos())} (3 períodos × 8 janelas).")
    partes = []
    for p in PERIODOS:
        R = [r for r in dados["resultados"] if r["periodo"] == p and r["r1c"]["inicio_sim"]]
        grupos = defaultdict(list)
        for r in R:
            grupos[(r["r1c"]["inicio_sim"][:10], round(r["r1c"]["aquecimento_dias"]), r["r1c"].get("aquecimento_motivo", ""))].append(r["ativo"][:-4])
        partes.append(f"fim {p}: " + "; ".join(
            f"{ini} ({aq} dias de aquecimento{'' if aq else ' — ' + mot}; {'todos os ativos' if len(ats) == len(R) else ', '.join(ats)})"
            for (ini, aq, mot), ats in sorted(grupos.items())).replace("1o dia", "1º dia"))
    w("- Início da simulação do R1c: " + " | ".join(partes) + ".")
    w("- R2: uma janela contínua de 2 anos por ativo e período, começando em caixa na 1ª janela (SOL fica de fora em 2020-22, como no exploratório).")
    w("- R3: " + ", ".join(ROTULO_VAR[v] for v in dados["variantes_r3"]) + ".")
    w("")
    cod = dados.get("sha256_codigo", {})
    if cod:
        w("Código usado (sha256 no momento da rodada) contra os hashes do pré-registro:")
        w("")
        linhas = []
        for nome, h in cod.items():
            reg = HASHES_CODIGO_PREREG.get(nome)
            if reg is None:
                sit = "não está na tabela de hashes do pré-registro" + (": " + NOTA_HASH[nome] if nome in NOTA_HASH else "")
            elif reg == h:
                sit = "**igual**"
            else:
                sit = "difere: " + NOTA_HASH.get(nome, "sem explicação registrada")
            linhas.append([f"`backend/{nome}`", f"`{h[:16]}…`", f"`{reg[:16]}…`" if reg else "—", sit])
        w(tabela(["Arquivo", "sha256 agora", "sha256 no pré-registro", "situação"], linhas))
        w("")

    # ---------- R0 e R0b
    w("## 4. Conferências R0 e R0b")
    w("")
    r0 = dados["r0"]
    w(f"**R0 — a T1 do harness reproduz o `efeito_stop_catastrofe.py` (\"com stop\")?** Sim. {r0['janelas_comuns']} janelas comuns, "
      f"maior |diferença| = {f(r0['maior_dif'], 4, False)} pt (limite 0,01). O harness não mudou a regra da T1.")
    w("")
    w(f"**R0b — comparação com os 6 logs exploratórios** (sha256 de cada log conferido com o pré-registro).")
    w("")
    w(f"- O harness com **todas as correções desligadas** reproduz os logs em {b['exploratoria_reproduz']} de {b['celulas']} células "
      f"(carteira × janela, R1 e contínuo) com |dif| < 0,005"
      + (f"; diferem {len(b['exploratoria_difere'])}: {b['exploratoria_difere'][:5]}" if b["exploratoria_difere"] else "") + ". "
      "Ou seja: fora das correções, o harness novo é o mesmo que gerou os logs.")
    w(f"- Janelas: os logs têm {b['janelas_log']} janelas medidas e {b['janelas_fora_log']} excluídas; o conjunto confirmatório "
      + ("é o mesmo." if not b["janelas_divergentes"] else f"diverge em {b['janelas_divergentes']}."))
    w(f"- Com as correções (a versão confirmatória), {len(b['diferencas'])} células mudam em relação aos logs. "
      f"Sem explicação: **{b['sem_explicacao']}**.")
    if b["diferencas"]:
        w("")
        w(tabela(["Período", "Rodada", "Ativo", "Janela", "Carteira", "Log (%)", "Confirmatório (%)", "Causa (correção que, sozinha, reproduz a mudança)"],
                 [[d["periodo"][:4], "R1" if d["modo"] == "janelas" else "R2 (contínuo)", d["ativo"], d["j"], d["carteira"],
                   f(d["log"]), f(d["confirmatorio"]), d["causa"]] for d in b["diferencas"]]))
    w("")
    dg = defaultdict(float)
    for r in dados["resultados"]:
        for k, v in r["diagnostico_correcoes"].items():
            dg[k] = max(dg[k], v) if k.startswith("max_") else dg[k] + v
    w(("**Por que as correções não mudaram nenhuma célula medida**" if not b["diferencas"] else "**Onde as correções podem mexer**")
      + " (comparação dia a dia das tabelas de sinal exploratória e corrigida, "
      f"8 ativos × 3 períodos, {int(dg['dias_comparados'])} dias desde o início do aquecimento do R1c):")
    w("")
    w(f"- 16.4-1 (guarda de saída): dias em que a G2 teria compra **e** saída no mesmo dia: **{int(dg['g2_compra_e_saida_no_mesmo_dia'])}**. "
      "Sem esse dia, a guarda não tem o que bloquear (na T1, T2 e G1 ela não pode morder: a entrada e a saída pela regra são mutuamente exclusivas no mesmo dia).")
    w(f"- 16.4-2 (janela de 300 dias): dias em que as duas tabelas têm o sinal pronto e ele difere (compra/venda de Réguas, Tartarugas ou RSI(2)): "
      f"**{int(dg['sinal_oposto_com_as_duas_prontas'])}**, dos quais **{int(dg['sinal_oposto_com_as_duas_prontas_em_janela_medida'])}** em janela medida. "
      f"Outros {int(dg['sinal_pronto_so_numa'])} dias diferem só porque uma tabela ainda não tem histórico "
      f"(a exploratória lê só o arquivo de 260 dias; esses dias ficam no aquecimento do R1c, que o exploratório não tinha), "
      f"dos quais {int(dg['sinal_pronto_so_numa_em_janela_medida'])} em janela medida. "
      f"Maior diferença relativa do ATR: {f(dg['max_dif_rel_atr'] * 1e6, 1, False)}×10⁻⁶; do N das Tartarugas: {f(dg['max_dif_rel_n'] * 1e4, 1, False)}×10⁻⁴. "
      "Os níveis de stop 2N e de alvo mudam nessa ordem de grandeza, sem virar nenhum cruzamento nas janelas medidas.")
    w(f"- 16.4-3 (ATR com 150 dias): dias em que o ATR existe numa tabela e não na outra: {int(dg['atr_disponivel_so_numa'])}, "
      f"dos quais **{int(dg['atr_disponivel_so_numa_em_janela_medida'])}** em janela medida (são os primeiros meses da SOL em 2020-21, nas janelas "
      "que a guarda do RSI(2) já exclui).")
    w("- 3b (ATR só na G1): nas janelas medidas o ATR sempre existe, então exigir ou não exigir ATR na T1, T2 e G2 não muda nada.")
    w("")
    w("Como a atribuição foi feita: além da versão exploratória e da confirmatória, o harness roda R1 e R2 com cada correção ligada sozinha. "
      "Uma diferença é atribuída à correção que, ligada sozinha, leva a célula exatamente ao valor confirmatório.")
    w("")

    # ---------- tabelas por carteira
    w("## 5. Resultados por carteira — R1c (leitura principal)")
    w("")
    _tabela_carteiras(w, base, "R1c")
    w("")
    w("## 6. Hipóteses em detalhe (R1c, 24 blocos)")
    w("")
    linhas = []
    for h, desc, c, ref, lado in HIPOTESES:
        t = conf[h]
        linhas.append([h, t["n"], f(t["media"]), f"[{f(t['ic90'][0])}; {f(t['ic90'][1])}]", f(t["mediana"]), f(t["aparada5"]),
                       f(t["simples_media_blocos"]), f(t["regua_antiga"]), f"{t['positivos']}/{t['negativos']}/{t['zeros']}",
                       pv(t["p_wilcoxon"]) + f" ({t['metodo_wilcoxon']})", pv(t["p_t"]), pv(t["p_sinal"]), pv(t["p_holm"])])
    w(tabela(["H", "blocos", "média Δ log", "IC 90%", "mediana", "média aparada 5%", "média Δ simples (%)", "régua antiga (%/janela)",
              "blocos +/−/0", "p Wilcoxon-Pratt", "p t (23 gl)", "p sinal", "p Holm"], linhas))
    w("")
    w("Por período (mediana dos 8 blocos, em pts de log; entre parênteses a média; e a régua antiga do período):")
    w("")
    linhas = []
    for h, desc, c, ref, lado in HIPOTESES:
        t = conf[h]
        linhas.append([h] + [f"{f(t['por_periodo'][p]['mediana'])} ({f(t['por_periodo'][p]['media'])}); {f(t['regua_antiga_por_periodo'][p])}"
                             for p in PERIODOS])
    w(tabela(["H"] + [f"até {p}" for p in PERIODOS], linhas))
    w("")
    w("**As duas réguas lado a lado** (mesmo peso): régua antiga = média por janela da diferença em % contra o b&h de fração fixa (H1, H2) ou contra a T1 (H3, H4); "
      "régua nova = Δ em log por bloco (média e mediana).")
    w("")
    linhas = []
    for h, desc, c, ref, lado in HIPOTESES:
        t = conf[h]
        s_ant = t["regua_antiga"] > 0
        linhas.append([h, f(t["regua_antiga"]), f(t["media"]), f(t["mediana"]),
                       "mesmo sinal" if s_ant == (t["media"] > 0) else "**sinal oposto**",
                       "mesmo sinal" if s_ant == (t["mediana"] > 0) else "**sinal oposto**"])
    w(tabela(["H", "régua antiga (%/janela)", "régua nova: média (log/bloco)", "régua nova: mediana",
              "antiga × média nova", "antiga × mediana nova"], linhas))
    w("")
    w("Poder observado: o desvio-padrão dos 24 blocos e o erro-padrão da média (a 12.4 supunha ≈ 1,04 pt de erro-padrão no par G1 × T1):")
    w("")
    w(tabela(["H", "desvio-padrão dos blocos (pts)", "erro-padrão da média (pts)", "efeito mínimo detectável aprox. (pts, 80% de poder, α de Holm no pior passo)"],
             [[h, f(conf[h]["dp"], 1, False), f(conf[h]["dp"] / math.sqrt(conf[h]["n"]), 2, False),
               f(mde(conf[h], lado), 1, False)]
              for h, desc, c, ref, lado in HIPOTESES]))
    w("")

    # ---------- R3
    w("## 7. Sensibilidade de execução (R3, sobre o R1c)")
    w("")
    linhas = []
    for v in dados["variantes_r3"]:
        lin = [ROTULO_VAR[v]]
        for h, desc, c, ref, lado in HIPOTESES:
            if v == BASE_TXT:
                t = conf[h]
                pp = t["por_periodo"]
                lin.append(f"{f(t['media'])} / {f(t['mediana'])} · " + " ".join(f(pp[p]["mediana"], 1) for p in PERIODOS))
            else:
                rv = conf[h]["r3"][v]
                lin.append(f"{f(rv['media'])} / {f(rv['mediana'])} · " + " ".join(f(rv["por_periodo"][p]["mediana"], 1) for p in PERIODOS))
        linhas.append(lin)
    w(tabela(["Variante"] + [f"{h} média / mediana · medianas por período (26, 24, 22)" for h, *_ in HIPOTESES], linhas))
    w("")
    linhas = []
    for v in dados["variantes_r3"]:
        lv = leituras[v]
        lin = [ROTULO_VAR[v]]
        for c in IDS:
            rv = resumo_carteira(lv, c, com_trades=(v == BASE_TXT))
            lin.append(f"{f(rv['ret_medio'])} (dd {f(rv['dd_medio'], 1)})")
        linhas.append(lin)
    w("Retorno médio por janela e ativo (%), e drawdown médio, por variante:")
    w("")
    w(tabela(["Variante"] + IDS, linhas))
    w("")

    # ---------- R1, R2, parcial
    w("## 8. Leituras descritivas: R1, R2 e o R1c de 2020-22 com aquecimento parcial")
    w("")
    w("### R1 — janelas que começam em caixa (comparável ao histórico da T1; não decide nada)")
    w("")
    _tabela_carteiras(w, leituras["R1"], "R1")
    w("")
    linhas = []
    for h, desc, c, ref, lado in HIPOTESES:
        t = desc_r1[h]
        linhas.append([h, f(t["media"]), f"[{f(t['ic90'][0])}; {f(t['ic90'][1])}]", f(t["mediana"]), f(t["regua_antiga"]), pv(t["p"]),
                       " ".join(f(t["por_periodo"][p]["mediana"], 1) for p in PERIODOS)])
    w(tabela(["H (no R1)", "média Δ log", "IC 90%", "mediana", "régua antiga", "p", "medianas por período"], linhas))
    w("")
    ig_r1, n_r1 = leituras["R1"].janelas_iguais("G1", "T1")
    ig_c, n_c = base.janelas_iguais("G1", "T1")
    zb_r1 = sum(1 for d in desc_r1["H3"]["deltas"] if d["log"] == 0)
    zb_c = sum(1 for d in conf["H3"]["deltas"] if d["log"] == 0)
    w(f"**Proporção de janelas com Δ = 0 exato no par G1 × T1:** R1 {ig_r1}/{n_r1} ({pct(ig_r1 / n_r1)}) das janelas, {zb_r1}/24 blocos; "
      f"R1c {ig_c}/{n_c} ({pct(ig_c / n_c)}) das janelas, {zb_c}/24 blocos.")
    w("")
    w("### R2 — contínuo de 2 anos por ativo (começa em caixa)")
    w("")
    linhas = []
    for p in PERIODOS:
        R = [r for r in dados["resultados"] if r["periodo"] == p and r["r2"].get("valida")]
        bh = statistics.mean(r["r2"]["bh"][200][0] for r in R)
        lin = [p[:4], len(R), f(bh)]
        for c in IDS:
            rets = [r["r2"]["det"][c]["r"] * 100 for r in R]
            dds = [r["r2"]["det"][c]["dd"] for r in R]
            lin.append(f"{f(statistics.mean(rets))} / {f(statistics.median(rets))} (dd {f(statistics.mean(dds), 1)})")
        linhas.append(lin)
    w(tabela(["Período", "ativos", "b&h 100% médio"] + [f"{c} média / mediana (dd médio)" for c in IDS], linhas))
    w("")
    if parcial:
        w("### R1c de 2020-22 com aquecimento parcial (descritivo)")
        w("")
        w("A simulação de 2020-22 começa 91 dias antes da 1ª janela mesmo sem o RSI(2) pronto (a G2 fica em caixa até ter 220 dias). "
          "Só os 8 blocos de 2020-22 mudam; os outros 16 são os do R1c.")
        w("")
        linhas = []
        for h, desc, c, ref, lado in HIPOTESES:
            a, bb = conf[h]["por_periodo"]["2022-09-03"], parcial[h]["por_periodo"]["2022-09-03"]
            linhas.append([h, f(a["mediana"]), f(bb["mediana"]), f(a["media"]), f(bb["media"]), f(conf[h]["media"]), f(parcial[h]["media"]),
                           pv(conf[h]["p"]), pv(parcial[h]["p"])])
        w(tabela(["H", "mediana 2020-22 (sem aquec.)", "idem (parcial)", "média 2020-22 (sem)", "idem (parcial)",
                  "média 24 blocos (sem)", "idem (parcial)", "p (sem)", "p (parcial)"], linhas))
        w("")

    # ---------- G1
    w("## 9. G1: o que o stop gain faz (12.3, só descritivo)")
    w("")
    alvo_g = [t["ret_preco"] * 100 for l in base.de("G1") for t in l["trades"] if t["motivo"] == MOTIVO_ALVO]
    alvo_btc = [t["ret_preco"] * 100 for l in base.de("G1") if l["a"] == "BTCUSDT" for t in l["trades"] if t["motivo"] == MOTIVO_ALVO]
    alvo_eth = [t["ret_preco"] * 100 for l in base.de("G1") if l["a"] == "ETHUSDT" for t in l["trades"] if t["motivo"] == MOTIVO_ALVO]
    stops_cat = [t["ret_preco"] * 100 for c in ("T1", "G1", "G2") for l in base.de(c) for t in l["trades"] if t["motivo"] == MOTIVO_STOP]
    perda = -statistics.mean(stops_cat) / 100 if stops_cat else 0.20

    def equil(g, l_):
        return (l_ + 2 * TAXA) / (g + l_)

    w("**Acerto de equilíbrio (seção 6), recalculado com a perda média realizada nos stops.** "
      f"Stops de catástrofe no R1c (T1, G1 e G2 juntas): {len(stops_cat)}, perda média {f(-perda * 100)}%, "
      f"p90 {f(float(np.percentile(stops_cat, 10)) if stops_cat else None)}%. "
      f"Ganho médio realizado nas saídas pelo alvo da G1: {f(statistics.mean(alvo_g))}% (BTC {f(statistics.mean(alvo_btc)) if alvo_btc else '—'}%, "
      f"ETH {f(statistics.mean(alvo_eth)) if alvo_eth else '—'}%; {len(alvo_g)} saídas).")
    w("")
    linhas = []
    for nome, g in (("todos os ativos", alvo_g), ("BTC", alvo_btc), ("ETH", alvo_eth)):
        if g:
            gm = statistics.mean(g) / 100
            linhas.append([nome, f(gm * 100), pct(equil(gm, 0.20), 1), pct(equil(gm, perda), 1)])
    w(tabela(["Ativos", "ganho médio no alvo (%)", "acerto de equilíbrio com perda de 20%", "com a perda média realizada"], linhas))
    mot = rs["G1"]["motivos"]
    n_alvo, n_stop = mot.get(MOTIVO_ALVO, 0), mot.get(MOTIVO_STOP, 0)
    w("")
    w(f"Na G1, das saídas que terminaram no alvo ou no stop ({n_alvo + n_stop}), {pct(n_alvo / (n_alvo + n_stop) if n_alvo + n_stop else None, 1)} foram no alvo. "
      f"Saídas da G1 por motivo: {_motivos(mot)}.")
    w("")
    w("**Ganho deixado na mesa** (variação do preço depois de cada saída pelo alvo, a partir do preço de saída):")
    w("")
    linhas = []
    for p in PERIODOS:
        m10, m30 = mesa[p]["10"], mesa[p]["30"]
        linhas.append([p[:4], len(m10), f(statistics.mean(m10)) if m10 else "—", f(statistics.median(m10)) if m10 else "—",
                       f(statistics.mean(m30)) if m30 else "—", f(statistics.median(m30)) if m30 else "—"])
    w(tabela(["Período", "saídas pelo alvo", "10 dias: média (%)", "10 dias: mediana", "30 dias: média (%)", "30 dias: mediana"], linhas))
    w("")
    w("**Decomposição de cada saída pelo alvo** contra a T1 (custo em pts de log; positivo = custou à G1). "
      "Se a G1 recomprou antes de a T1 sair da mesma tendência: `ln(P_recompra/P_alvo) + 0,2%`; se não recomprou: `ln(P_saída_T1/P_alvo)`. Soma por período, não é critério.")
    w("")
    linhas = []
    for p in PERIODOS:
        d = dec[p]
        rec = [x * 100 for x in d.get("recomprou", [])]
        nao = [x * 100 for x in d.get("nao recomprou", [])]
        fora = len(d.get("T1 fora", []))
        linhas.append([p[:4], len(rec), f(sum(rec)), len(nao), f(sum(nao)), fora, f(sum(rec) + sum(nao))])
    w(tabela(["Período", "recomprou (n)", "custo das reentradas (soma)", "não recomprou (n)", "custo de sair antes da T1 (soma)", "T1 fora (n)", "total"], linhas))
    w("")
    w("A soma é sobre todas as saídas pelo alvo dos 8 ativos nas janelas medidas; dividida pelo número de janelas-ativo do período, dá a ordem de grandeza por janela.")
    w("")

    # ---------- T2 x T1
    w("## 10. T2 × T1 (descritivo)")
    w("")
    linhas = []
    for p in PERIODOS:
        z = t2t1[p]
        linhas.append([p[:4], pct(z["t1_pos"] / z["horas"]), pct((z["ambas"] + z["so_t2"]) / z["horas"]),
                       pct(z["so_t1"] / z["horas"]), pct(z["so_t1"] / z["t1_pos"] if z["t1_pos"] else None), pct(z["so_t2"] / (z["ambas"] + z["so_t2"]) if z["ambas"] + z["so_t2"] else None, 1),
                       f(statistics.mean(z["lr"])), f(statistics.median(z["lr"]))])
    w(tabela(["Período", "horas com a T1 comprada", "horas com a T2 comprada", "horas com só a T1 comprada", "das horas da T1, só ela comprada",
              "das horas da T2, só ela comprada", "log-retorno da T1 nessas horas (média por janela-ativo, pts)", "mediana"], linhas))
    w("")

    # ---------- faixa da sorte e sigma
    w("## 11. Faixa da sorte (13.4) e σ do par (sobre o R2)")
    w("")
    w("Percentil do retorno de cada carteira na permutação dos próprios períodos comprados (5.000 sorteios, semente `sha256(\"VAL-6c-\" + fim do período + carteira + par)`). "
      "Descritivo: no backtest não há categoria; a 13.4 vale para o ao vivo.")
    w("")
    linhas = []
    for p in PERIODOS:
        for c in IDS:
            s = sorte[(p, c)]
            comb = s["combinado"]
            pa = s["por_ativo"]
            linhas.append([p[:4], c, f(pa.get("BTCUSDT"), 1, False), f(pa.get("ETHUSDT"), 1, False),
                           f(comb["percentil"], 1, False) if comb and comb.get("percentil") is not None else (comb or {}).get("nota", "—"),
                           f(statistics.median(pa.values()), 1, False), sum(1 for v in pa.values() if v >= 99.2)])
    w(tabela(["Período", "Carteira", "BTC", "ETH", "BTC+ETH", "mediana dos ativos", "ativos ≥ 99,2"], linhas))
    w("")
    w("**σ do par T1 − G1** (bootstrap em blocos móveis de 30 dias sobre a diferença diária de log-patrimônio do R2; 10.000 sorteios de 365 dias):")
    w("")
    linhas = [[k, f(v["sigma_ano_pts"], 1, False), f(v["sigma_iid_ano_pts"], 1, False), f(v["media_ano_pts"], 1), v["dias"],
               f(v["sigma_ano_pts"] * math.sqrt(91 / 365), 1, False), f(1.64 * v["sigma_ano_pts"] * math.sqrt(2), 1, False)]
              for k, v in sig.items()]
    w(tabela(["Par", "σ_par (pts/ano, blocos)", "σ sem blocos (iid)", "média da diferença (pts/ano)", "dias", "σ por janela de 91 dias",
              "faixa ±1,64·σ·√2 (24 meses)"], linhas))
    w("")
    w("A especificação usava σ_par ≈ 10,2 pts/ano (simulação sintética). Este é o número que substitui aquele na leitura de 24 meses (13.4).")
    w("")

    # ---------- previsoes e rotulo
    w("## 12. Previsões registradas × resultado, e o rótulo de continuidade")
    w("")
    k = {c: sum(1 for p in PERIODOS if _mediana_periodo(base, c, p) > 0) for c in IDS}
    w("**Rótulo descritivo de continuidade** (R1c; mediana de Δ contra o b&h f_dd > 0 no período). "
      f"Sempre com a frase fixa: *{FRASE_ACASO}*. Não decide nada.")
    w("")
    w(tabela(["Carteira", "passa na régua em", "medianas por período (log)"],
             [[f"{c} {NOMES[c]}", f"{k[c]} de 3 períodos", " ".join(f(_mediana_periodo(base, c, p), 1) for p in PERIODOS)] for c in IDS]))
    w("")
    t3 = conf["H3"]
    per_neg = sum(1 for p in PERIODOS if t3["por_periodo"][p]["mediana"] < 0)
    ida_g1 = rs["G1"]["trades_janela"] - rs["T1"]["trades_janela"]
    alta_t2 = base.por_regime("T2", "T1").get("alta")
    sim_nao = lambda ok: "sim" if ok else "**não**"
    dd_dif = rs["G1"]["dd_medio"] - rs["T1"]["dd_medio"]
    w(tabela(["Pergunta", "Previsão registrada (12.5)", "Resultado", "Confere?"], [
        ["H1 T2 passa na régua?", "\"sem evidência de vantagem\" (poder baixo)", f"{conf['H1']['resposta']}",
         sim_nao(conf["H1"]["resposta"] == "Sem evidência de vantagem")],
        ["", "abaixo da T1 em alta forte", (f"T2 − T1 nas {alta_t2['n']} janelas de alta (> +10%): {f(alta_t2['dif'])} pts percentuais por janela"
                                            if alta_t2 else "—"), sim_nao(alta_t2 is not None and alta_t2["dif"] < 0)],
        ["H2 G2 passa na régua?", "\"sem evidência de vantagem\"; empate ou derrota",
         f"{conf['H2']['resposta']} (média {f(conf['H2']['media'])}, mediana {f(conf['H2']['mediana'])})",
         sim_nao(conf["H2"]["resposta"] == "Sem evidência de vantagem")],
        ["H3 G1 × T1", "\"Não, custa dinheiro\" ou \"inconclusivo\"", f"{conf['H3']['resposta']}",
         sim_nao(conf["H3"]["resposta"] in ("Não, custa dinheiro", "Inconclusivo"))],
        ["", "estimativa < 0 em ≥ 2 de 3 períodos", f"{per_neg} de 3 períodos com mediana < 0", sim_nao(per_neg >= 2)],
        ["", "G1 com +1 a +3 idas e voltas por janela", f"{f(ida_g1)} por janela ({f(rs['G1']['trades_janela'])} contra {f(rs['T1']['trades_janela'])} da T1)",
         sim_nao(1 <= ida_g1 <= 3)],
        ["", "drawdown médio a no máximo 3 pts do da T1", f"G1 {f(rs['G1']['dd_medio'])} × T1 {f(rs['T1']['dd_medio'])} (diferença {f(dd_dif)} pts)",
         sim_nao(abs(dd_dif) <= 3) + ("" if abs(dd_dif) <= 3 else " (a G1 caiu menos que o previsto)" if dd_dif > 0 else "")],
        ["", "taxa de acerto maior que a da T1", f"G1 {pct(rs['G1']['acerto'])} × T1 {pct(rs['T1']['acerto'])}",
         sim_nao(rs["G1"]["acerto"] > rs["T1"]["acerto"])],
        ["H4 G2 × T1", "descritivo, sem previsão de sinal", f"{conf['H4']['resposta']}", "—"],
    ]))
    w("")
    w("**Deflated Sharpe Ratio:** só se aplica a carteira que saia \"Sim\". "
      + ("Nenhuma saiu \"Sim\"; não calculado." if not any(conf[h]["resposta"] == "Sim" for h in conf) else "ATENÇÃO: há \"Sim\"; o DSR precisa ser calculado antes de publicar."))
    w("")
    w("## 13. Ressalvas")
    w("")
    w("- **Multiplicidade do projeto:** 5 configurações novas (T2, G1, G2, T3, G3) somadas às 18 do bloco anterior = 23. O Holm controla só a família H1–H4.")
    w("- **Grau de liberdade do pesquisador:** a régua nova (Δ em log por bloco) foi escolhida depois de se conhecerem a T1 e o DOGE; por isso as duas réguas saem lado a lado.")
    w("- **Os logs exploratórios foram vistos antes do commit do pré-registro.** A R0b mostra que as diferenças para eles vêm só das correções da 16.4.")
    w("- **2020-22 sem aquecimento no R1c** (o cache congelado não cobre 220 + 91 dias). A seção 8 mostra o efeito de um aquecimento parcial.")
    w("- **Wilcoxon com zeros usa aproximação normal** (com o ajuste de Pratt); como vale o maior p entre Wilcoxon e t, isso não afrouxa a decisão.")
    w(f"- **Poder do par G1 × T1 muito abaixo do suposto.** A 12.4 contava com erro-padrão de ≈ 1,04 pt por bloco (σ_par sintética de 10,2 pts/ano); "
      f"o observado foi {f(conf['H3']['dp'] / math.sqrt(conf['H3']['n']), 2, False)} pt, e o σ_par por bootstrap do R2 (BTC+ETH) deu "
      f"{f(sig['BTC+ETH']['sigma_ano_pts'], 1, False)} pts/ano. O \"Inconclusivo\" da H3 é, em boa parte, falta de poder: "
      "a diferença se concentra em poucas janelas de alta forte, e 24 blocos não bastam para separá-la do acaso.")
    w("- **Uma nota de leitura foi escrita depois de ver os números** (convenção 3: réguas discordantes numa unilateral que já é "
      "\"Sem evidência de vantagem\"). Ela só afeta a H2, que sairia \"Inconclusivo\" pela frase da 12.4 e sai \"Sem evidência de vantagem\" "
      "pela tabela da 12.5; as duas respostas dizem que não há vantagem demonstrada.")
    w("- O backtest **não decide** se a carteira vai ao ar (12.5). Decide o que se pode dizer sobre cada uma.")
    w("")

    RELATORIO.write_text("\n".join(L) + "\n", encoding="utf-8")
    ANALISE.write_text(json.dumps({
        "gerado_em": datetime.now(timezone.utc).isoformat(),
        "hipoteses": {h: {k: v for k, v in conf[h].items() if k != "deltas"} | {"deltas": conf[h]["deltas"]} for h in conf},
        "r1_descritivo": {h: {k: v for k, v in desc_r1[h].items() if k != "deltas"} for h in desc_r1},
        "r0b": b, "sigma_par": sig,
        "sorte": {f"{p}|{c}": v for (p, c), v in sorte.items()},
        "resumo_r1c": {c: resumo_carteira(base, c) for c in IDS},
        "resumo_r1c_por_periodo": {p: {c: resumo_carteira(base, c, p) for c in IDS} for p in PERIODOS},
    }, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(f"relatorio em {RELATORIO}")
    for h, desc, *_ in HIPOTESES:
        t = conf[h]
        print(f"{h} {desc:<14} {t['resposta']:<26} media {t['media']:+.2f} IC90 [{t['ic90'][0]:+.2f}; {t['ic90'][1]:+.2f}] "
              f"mediana {t['mediana']:+.2f} p {t['p']:.4f} holm {t['p_holm']:.4f}")


def _mediana_periodo(leit, c, p):
    v = [d["log"] for d in leit.deltas(c, "bhf") if d["p"] == p]
    return float(np.median(v))


def _motivos(m):
    ordem = (MOTIVO_TENDENCIA, MOTIVO_REPIQUE, MOTIVO_STOP, MOTIVO_STOP_2N, MOTIVO_ALVO, MOTIVO_FIM)
    return ", ".join(f"{k} {m[k]}" for k in ordem if m.get(k)) or "—"


def _tabela_carteiras(w, leit, rot):
    linhas = []
    for c in IDS:
        r = resumo_carteira(leit, c)
        linhas.append([f"{c} {NOMES[c]}", r["n"], f(r["ret_medio"]), f(r["ret_mediano"]), f(r["log_medio"]), f(r["dd_medio"]),
                       pct(r["expo"]), f(r.get("trades_ano"), 1, False), f(r["custo_ano_pct"], 1, False), pct(r.get("acerto")),
                       f"{f(r.get('expectativa_media'))} / {f(r.get('expectativa_mediana'))}", f"{f(r.get('ganho_medio'))} / {f(r.get('perda_media'))}",
                       f"{f(r.get('stop_perda_media'))} / {f(r.get('stop_perda_p90'))}"
                       + (f"; 2N: {f(r.get('stop2n_perda_media'))} / {f(r.get('stop2n_perda_p90'))}" if r.get("stop2n_perda_media") is not None else ""),
                       _motivos(r["motivos"])])
    w(tabela(["Carteira", "janelas", "retorno médio (%)", "mediano", "log médio (pts)", "drawdown médio", "exposição", "idas e voltas/ano",
              "custo em taxa (% do capital/ano)", "acerto", "expectativa por operação: média / mediana (%)", "ganho / perda médios (%)",
              "perda no stop: média / p90 (%)", "saídas por motivo"], linhas))
    w("")
    w(f"Contra as referências ({rot}; média por janela da diferença simples em pontos percentuais; `f_dd` e `f_expo` são do período e da carteira):")
    w("")
    linhas = []
    for c in IDS:
        for p in PERIODOS:
            r = resumo_carteira(leit, c, p, com_trades=False)
            linhas.append([f"{c} {NOMES[c]}", p, r["n"], f(r["ret_medio"]), f(r["vs"]["bh100"]), pct(r["f_dd"], 1), f(r["vs"]["bhf"]),
                           pct(r["f_expo"], 1), f(r["vs"]["bhexpo"])])
    w(tabela(["Carteira", "período (fim)", "janelas", "retorno médio (%)", "vs b&h 100%", "f_dd", "vs b&h f_dd", "f_expo", "vs b&h f_expo"], linhas))


def mde(t, lado):
    """Efeito minimo detectavel aprox. (80% de poder, alfa do pior passo do Holm) com a dispersao observada."""
    z = stats.norm.ppf(1 - ALFA / 4 / (1 if lado == "maior" else 2)) + stats.norm.ppf(0.8)
    return z * t["dp"] / math.sqrt(t["n"])


def _txt_regime(pr, c, ref):
    """Frase com a diferenca media por janela (em %) de c contra ref, por regime do ativo na janela."""
    nomes = {"alta": "de alta (> +10%)", "lateral": "laterais", "baixa": "de baixa (< −10%)"}
    partes = [f"{f(v['dif'], 1)} (mediana {f(v['mediana'], 1)}) nas {v['n']} janelas {nomes[k]}" for k, v in pr.items()]
    return (f"Por regime do ativo na janela (variação do preço na janela), a diferença {c} − {ref} por janela, em pontos percentuais, "
            f"teve média de " + "; ".join(partes) + ". ")


def _em_palavras(conf, rs, base):
    """O resumo para leigo. Todo numero vem de `conf` (R1c, 24 blocos) e de `rs` (R1c por carteira)."""
    P = PERIODOS
    frases = []

    def peso_do_pior_periodo(t):
        m = [t["por_periodo"][p]["media"] for p in P]
        k = min(range(3), key=lambda i: m[i] * (1 if t["media"] < 0 else -1))
        return P[k], m[k], (m[k] / (3 * t["media"]) if t["media"] else float("nan"))

    t = conf["H3"]
    p_pior, m_pior, peso = peso_do_pior_periodo(t)
    frases.append(
        f"- **O stop gain ganha dinheiro? (G1 × T1, H3) — {t['resposta']}.** "
        f"Na média, vender na meta {'custou' if t['media'] < 0 else 'rendeu'}: por janela de 91 dias a G1 ficou {f(t['media'])} pts de log "
        f"{'acima' if t['media'] > 0 else 'abaixo'} da T1 (IC 90% {f(t['ic90'][0])} a {f(t['ic90'][1])}). "
        + _txt_regime(base.por_regime("G1", "T1"), "G1", "T1") +
        f"O período até {p_pior} responde por {pct(peso)} da média (média do período {f(m_pior)}); "
        f"na janela típica a diferença é de {f(t['mediana'])} (mediana dos blocos; a G1 ficou à frente em {t['positivos']} dos {t['n']} blocos). "
        f"O teste de postos, que olha a janela típica, dá p = {pv(t['p_wilcoxon'])}; com o Holm, p ajustado = {pv(t['p_holm'])}. "
        + ("Pelo critério pré-registrado, não dá para dizer \"custa dinheiro\" nem \"ganha dinheiro\". "
           if t["resposta"] not in ("Sim", "Não, custa dinheiro") else "")
        + f"Descritivo (R1c, média por janela e ativo): a G1 rendeu {f(rs['G1']['ret_medio'])}% contra {f(rs['T1']['ret_medio'])}% da T1, "
        f"com queda máxima média de {f(rs['G1']['dd_medio'], 1)}% contra {f(rs['T1']['dd_medio'], 1)}%, "
        f"e acertou {pct(rs['G1']['acerto'])} das operações contra {pct(rs['T1']['acerto'])} da T1. "
        + (f"O teste tinha bem menos poder do que a especificação supunha: o erro-padrão da média foi {f(t['dp'] / math.sqrt(t['n']), 2, False)} pt "
           f"(a 12.4 supunha ≈ 1,04), e o menor efeito que ele detectaria com 80% de chance é de ≈ {f(mde(t, 'bicaudal'), 0, False)} pts por janela, "
           f"e não 3,7." if t["dp"] / math.sqrt(t["n"]) > 1.04 * 1.5 else
           f"Erro-padrão da média: {f(t['dp'] / math.sqrt(t['n']), 2, False)} pt (a 12.4 supunha ≈ 1,04)."))
    t = conf["H1"]
    frases.append(
        f"- **As Tartarugas batem o comprar-e-segurar de mesmo risco? (T2, H1) — {t['resposta']}.** "
        f"A T2 ficou {'à frente' if t['media'] > 0 else 'atrás'} na média ({f(t['media'])} pts por janela, mediana {f(t['mediana'])}), "
        f"com mediana positiva em {sum(1 for p in P if t['por_periodo'][p]['mediana'] > 0)} de 3 períodos; "
        f"p = {pv(t['p'])} e, corrigido para as 4 perguntas (Holm), {pv(t['p_holm'])}. "
        + (f"O efeito observado é menor que o mínimo que 24 blocos detectam com a dispersão observada (≈ {f(mde(t, 'maior'), 1, False)} pts). "
           if abs(t["media"]) < mde(t, "maior") else "")
        + _txt_regime(base.por_regime("T2", "T1"), "T2", "T1")
        + ("Foi o que a especificação previu." if t["resposta"] == "Sem evidência de vantagem" else ""))
    t = conf["H2"]
    frases.append(
        f"- **O Repique bate o comprar-e-segurar de mesmo risco? (G2, H2) — {t['resposta']}.** "
        f"Na média a G2 ficou {'atrás' if t['media'] < 0 else 'à frente'} ({f(t['media'])} pts por janela); "
        f"na janela típica, {'empate' if abs(t['mediana']) < 1 else ('à frente' if t['mediana'] > 0 else 'atrás')} (mediana {f(t['mediana'])}); p = {pv(t['p'])}. "
        f"Ela fica comprada só {pct(rs['G2']['expo'])} do tempo. "
        + ("Empate ou derrota, como a especificação previu." if t["resposta"] == "Sem evidência de vantagem" and t["media"] <= 0 else ""))
    t = conf["H4"]
    p_pior, m_pior, peso = peso_do_pior_periodo(t)
    frases.append(
        f"- **O Repique difere das Réguas? (G2 × T1, H4) — {t['resposta']}.** "
        f"Na média a G2 ganhou {'menos' if t['media'] < 0 else 'mais'} que a T1 ({f(t['media'])} pts por janela); "
        f"na janela típica, mediana {f(t['mediana'])}. "
        + _txt_regime(base.por_regime("G2", "T1"), "G2", "T1")
        + f"O período até {p_pior} responde por {pct(peso)} da média. "
        + ("Média e mediana apontam lados opostos. " if (t["media"] > 0) != (t["mediana"] > 0) else "")
        + f"p = {pv(t['p'])}; p ajustado (Holm) = {pv(t['p_holm'])}.")
    nenhuma = not any(conf[h]["resposta"] in ("Sim", "Não, custa dinheiro") for h in conf)
    if nenhuma:
        frases.append("")
        frases.append("Nenhuma das 4 perguntas teve resposta firme. Isso não quer dizer que as carteiras são iguais: quer dizer que 24 blocos "
                      "de 91 dias, com a régua combinada antes, não separam essas diferenças do acaso. As diferenças de comportamento "
                      "(quanto cada uma fica comprada, quanto cai, quantas vezes opera) estão nas seções 5, 9 e 10, e são descritivas.")
    return "\n".join(frases)


if __name__ == "__main__":
    main()
