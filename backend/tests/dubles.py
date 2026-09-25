"""
Dubles compartilhados pelos testes das carteiras e do painel.

`BancoFiltrado` e um Supabase em memoria que aplica os filtros que o codigo
usa (eq, neq, lt, gte, is/not is, order, limit, caminho JSON `a->>b`) e as
restricoes de unicidade das tabelas -- incluindo o indice de idempotencia
`(carteira, symbol, candle_fechamento_em)` e, opcionalmente, o indice
ANTIGO `(symbol, candle_fechamento_em)`, para testar a guarda da migracao.
O duble antigo (`test_ciclo_ao_vivo.SupabaseDuble`) ignora filtros e foi
por isso que um bug de reivindicacao orfa passou pelos testes.
"""

import copy
import time

UMA_HORA = 3_600_000
UM_DIA = 24 * UMA_HORA

UNICOS = {
    "decisions": [("carteira", "symbol", "candle_fechamento_em")],
    "portfolio": [("carteira", "asset")],
    "patrimonio_diario": [("carteira", "asset", "dia_utc")],
    "painel_entradas": [("dia_utc", "simbolo", "prompt_versao")],
    "painel_veredito": [("dia_utc", "simbolo")],
    "carteiras": [("id",)],
}


class _Consulta:
    def __init__(self, banco, tabela):
        self.banco, self.tabela = banco, tabela
        self.filtros, self.ordens, self.limite = [], [], None
        self.op, self.reg, self.on_conflict, self.ignorar = "select", None, None, False
        self._negar = False

    @staticmethod
    def _valor(linha, coluna):
        if "->>" in coluna:
            base, chave = coluna.split("->>")
            v = (linha.get(base) or {}).get(chave)
            if v is None:
                return None
            return str(v).lower() if isinstance(v, bool) else str(v)
        return linha.get(coluna)

    def select(self, *_):
        return self

    def eq(self, c, v):
        esperado = (str(v).lower() if isinstance(v, bool) else str(v)) if "->>" in c else v
        self.filtros.append(lambda linha: _igual(self._valor(linha, c), esperado))
        return self

    def neq(self, c, v):
        self.filtros.append(lambda linha: not _igual(self._valor(linha, c), v))
        return self

    def lt(self, c, v):
        self.filtros.append(lambda linha: self._valor(linha, c) is not None and str(self._valor(linha, c)) < str(v))
        return self

    def gte(self, c, v):
        self.filtros.append(lambda linha: self._valor(linha, c) is not None and str(self._valor(linha, c)) >= str(v))
        return self

    @property
    def not_(self):
        self._negar = True
        return self

    def is_(self, c, _nulo):
        negar, self._negar = self._negar, False
        self.filtros.append(lambda linha: (self._valor(linha, c) is None) != negar)
        return self

    def order(self, c, desc=False):
        self.ordens.append((c, desc))
        return self

    def limit(self, n):
        self.limite = n
        return self

    def insert(self, r):
        self.op, self.reg = "insert", r
        return self

    def upsert(self, r, on_conflict=None, ignore_duplicates=False, **_):
        self.op, self.reg, self.on_conflict, self.ignorar = "upsert", r, on_conflict, ignore_duplicates
        return self

    def update(self, r):
        self.op, self.reg = "update", r
        return self

    def execute(self):
        linhas = self.banco.tabelas.setdefault(self.tabela, [])

        def resposta(dados):
            return type("R", (), {"data": copy.deepcopy(dados)})()

        if self.op == "select":
            sel = [linha for linha in linhas if all(f(linha) for f in self.filtros)]
            for c, desc in reversed(self.ordens):
                sel.sort(key=lambda linha: (linha.get(c) is None, str(linha.get(c) or "")), reverse=desc)
            return resposta(sel[: self.limite] if self.limite else sel)

        if self.op == "update" and self.banco.falhas_de_update:
            self.banco.falhas_de_update -= 1
            raise RuntimeError("503 Service Unavailable")

        registros = self.reg if isinstance(self.reg, list) else [self.reg]
        self.banco.escritas.append((self.tabela, self.op, copy.deepcopy(self.reg)))
        if self.op == "insert":
            saida = []
            for r in registros:
                nova = {"id": f"{self.tabela[:3]}{len(linhas) + 1}", **copy.deepcopy(r)}
                if self.tabela == "decisions":
                    nova.setdefault("created_at", _agora_iso(self.banco))
                self._conferir_unicos(nova, linhas)
                linhas.append(nova)
                saida.append(nova)
            return resposta(saida)
        if self.op == "upsert":
            chave = tuple((self.on_conflict or "id").split(","))
            saida = []
            for r in registros:
                existente = next((linha for linha in linhas if all(_igual(linha.get(k), r.get(k)) for k in chave)), None)
                if existente is not None:
                    if not self.ignorar:
                        existente.update(copy.deepcopy(r))
                    saida.append(existente)
                else:
                    nova = copy.deepcopy(r)
                    self._conferir_unicos(nova, linhas)
                    linhas.append(nova)
                    saida.append(nova)
            return resposta(saida)
        alvo = [linha for linha in linhas if all(f(linha) for f in self.filtros)]
        for linha in alvo:
            candidata = {**linha, **copy.deepcopy(self.reg)}
            self._conferir_unicos(candidata, [x for x in linhas if x is not linha])
            linha.update(copy.deepcopy(self.reg))
        return resposta(alvo)

    def _conferir_unicos(self, nova, linhas):
        indices = list(UNICOS.get(self.tabela, []))
        if self.tabela == "decisions" and self.banco.indice_antigo:
            indices.append(("symbol", "candle_fechamento_em"))
        if self.tabela == "painel_votos" and nova.get("json_valido") and nova.get("tipo", "painel") == "painel":
            for x in linhas:
                if x.get("json_valido") and x.get("tipo", "painel") == "painel" and all(
                        _igual(x.get(k), nova.get(k)) for k in ("dia_utc", "simbolo", "vaga")):
                    raise RuntimeError("23505 duplicate key painel_votos_um_voto_valido")
        for idx in indices:
            if any(nova.get(k) is None for k in idx):
                continue
            if any(all(_igual(x.get(k), nova.get(k)) for k in idx) for x in linhas):
                raise RuntimeError(f"23505 duplicate key value violates unique constraint {idx}")


def _igual(a, b):
    if a is None or b is None:
        return a is b
    return str(a)[:10] == str(b)[:10] if _parece_data(a, b) else a == b


def _parece_data(a, b):
    return isinstance(a, str) and isinstance(b, str) and len(a) >= 10 and len(b) >= 10 \
        and a[4:5] == "-" and b[4:5] == "-" and (len(a) == 10 or len(b) == 10)


def _agora_iso(banco):
    banco.relogio += 1
    return f"2026-09-25T00:00:{banco.relogio % 60:02d}.{banco.relogio:06d}+00:00"


class BancoFiltrado:
    def __init__(self, indice_antigo=False, falhas_de_update=0, **tabelas):
        self.tabelas = {k: copy.deepcopy(v) for k, v in tabelas.items()}
        self.escritas = []
        self.indice_antigo = indice_antigo
        self.falhas_de_update = falhas_de_update
        self.relogio = 0

    def table(self, nome):
        return _Consulta(self, nome)

    def linhas(self, tabela, **filtros):
        return [x for x in self.tabelas.get(tabela, []) if all(_igual(x.get(k), v) for k, v in filtros.items())]

    def conta(self, carteira, par="BTCUSDT"):
        achadas = self.linhas("portfolio", carteira=carteira, asset=par)
        return achadas[0] if achadas else None

    def decisoes(self, carteira, par="BTCUSDT"):
        return self.linhas("decisions", carteira=carteira, symbol=par)


# ------------------------------------------------------------------ mercado


def horarios(n=72, preco=80_000.0, agora_ms=None):
    """n candles de 1h alinhados na hora, o ultimo em curso."""
    agora_ms = agora_ms or int(time.time() * 1000)
    atual = agora_ms // UMA_HORA * UMA_HORA
    saida = []
    for i in range(n):
        ab = atual - (n - 1 - i) * UMA_HORA
        saida.append({"abertura_em": ab, "abertura": preco, "maxima": preco * 1.002, "minima": preco * 0.998,
                      "fechamento": preco, "volume": 1.0, "fechamento_em": ab + UMA_HORA - 1})
    return saida


def diarios(fechamentos, em_andamento=None, agora_ms=None, amplitude=0.02):
    """Dias fechados terminando ontem (UTC), mais o dia de hoje em andamento."""
    agora_ms = agora_ms or int(time.time() * 1000)
    hoje = agora_ms // UM_DIA * UM_DIA
    n = len(fechamentos)
    saida = []
    for i, f in enumerate(fechamentos):
        ab = hoje - (n - i) * UM_DIA
        anterior = fechamentos[i - 1] if i else f
        saida.append({"abertura_em": ab, "abertura": anterior, "maxima": max(f, anterior) * (1 + amplitude / 2),
                      "minima": min(f, anterior) * (1 - amplitude / 2), "fechamento": f, "volume": 1.0,
                      "fechamento_em": ab + UM_DIA - 1})
    f = em_andamento if em_andamento is not None else fechamentos[-1]
    saida.append({"abertura_em": hoje, "abertura": f, "maxima": f, "minima": f, "fechamento": f,
                  "volume": 1.0, "fechamento_em": hoje + UM_DIA - 1})
    return saida


class BinanceDuble:
    def __init__(self, diarios_, horarios_=None, preco=80_000.0, extras=None):
        self.diarios = diarios_
        self.horarios = horarios_ if horarios_ is not None else horarios(preco=preco)
        self.preco = preco
        self.extras = extras or {}
        self.pedidos = []

    def buscar_candles(self, simbolo, intervalo="1h", limite=100):
        self.pedidos.append((simbolo, intervalo, limite))
        if simbolo in self.extras:
            return self.extras[simbolo]
        return self.diarios if intervalo == "1d" else self.horarios

    def buscar_preco(self, simbolo):
        return self.preco


class ExplicadorDuble:
    def __init__(self, erro=False):
        self.erro = erro
        self.fatos = []

    def explicar(self, fatos):
        self.fatos.append(fatos)
        return (None, "RuntimeError: cota") if self.erro else ("frase de teste", None)


# Series de 300 dias prontas para as regras.
SUBINDO = [50_000.0 * (1.0015 ** i) for i in range(300)]          # 6 votos, sem rompimento forcado
CAINDO = [120_000.0 * (0.9985 ** i) for i in range(300)]          # 0 votos
