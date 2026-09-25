"""
Conferencia do painel de IAs (T3 e G3) contra a secao 9 do pre-registro.

    cd backend && PYTHONIOENCODING=utf-8 .venv/Scripts/python tests/test_painel.py

Sem rede e sem LLM: os provedores sao `Falso` (um por modelo da cadeia,
com um roteiro de respostas), o Supabase e o `BancoFiltrado` de
`dubles.py` com os defaults do banco real (`inicio default now()`) e a
reordenacao de chaves do jsonb, e o relogio do prazo e injetado.

## O que mais importa aqui

- **resposta invalida nunca vira SIDEWAYS**: conta como nao-resposta.
- **a entrada e a mesma para todos**: montada uma vez por (dia, par),
  gravada, e reutilizada byte a byte em todas as vagas e ciclos.
- **o congelamento nao depende da hora do cron**: V=2 espera as 04:00 de
  D+1; V<2 vira sem_quorum as 18:00 (ou no teto); depois de congelado,
  ninguem e chamado.
- **o teto conta toda tentativa**, inclusive a interrompida (linha
  `em_andamento` gravada ANTES da requisicao).
"""

import json
import math
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from xml.sax.saxutils import escape

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from brain.provedores import ErroDoProvedor, RespostaBruta  # noqa: E402
from dubles import UM_DIA, BancoFiltrado, _Consulta, diarios  # noqa: E402
from live import painel as modulo  # noqa: E402
from live.mercado import Mercado  # noqa: E402
from live.painel import (  # noqa: E402
    FEEDS, SISTEMA, VAGAS, Painel, VotoDoPainel, _sha, agregar, buscar_manchetes, compras_do_painel_desde,
    montar_entrada, numeros_sem_origem, validar_voto,
)

# D = ultimo dia fechado. Datas no passado de proposito: o painel chama
# `somente_fechados` com o relogio real da maquina para o ETHBTC.
D_DT = datetime(2026, 9, 10, tzinfo=timezone.utc)
D = D_DT.date().isoformat()
D_MS = int(D_DT.timestamp() * 1000)
ONTEM = (D_DT - timedelta(days=1)).date().isoformat()   # D-1


def em(hora, minuto=0, dias=1):
    """Instante UTC de D+dias (padrao D+1)."""
    return D_DT + timedelta(days=dias, hours=hora, minutes=minuto)


AGORA = em(0, 17)   # 1o ciclo depois da virada; 11/09 e o dia 254 do ano (par): BTC primeiro

CADEIA = {v.id: v.cadeia for v in VAGAS}
PROVEDOR = {v.id: v.provedor for v in VAGAS}
PRINCIPAL = {v.id: v.cadeia[0] for v in VAGAS}

# Series de 300 dias (a janela do Mercado).
SERIE_BTC = [60_000.0 + 4_000.0 * math.sin(i / 9.0) + 35.0 * i for i in range(300)]
SERIE_ETH = [2_500.0 + 300.0 * math.cos(i / 7.0) + 2.0 * i for i in range(300)]


# ------------------------------------------------------------------ dubles


def _como_jsonb(x):
    """O jsonb do Postgres NAO guarda a ordem das chaves: ordena por tamanho e depois por bytes."""
    if isinstance(x, dict):
        itens = sorted(x.items(), key=lambda kv: (len(kv[0].encode()), kv[0].encode()))
        return {k: _como_jsonb(v) for k, v in itens}
    if isinstance(x, list):
        return [_como_jsonb(v) for v in x]
    return x


class _ConsultaPainel(_Consulta):
    """Os defaults que o banco real aplica e o duble generico nao conhece."""

    def insert(self, r):
        registros = r if isinstance(r, list) else [r]
        ajustados = []
        for x in registros:
            x = dict(x)
            if self.tabela == "painel_votos":
                x.setdefault("tipo", "painel")
                x.setdefault("inicio", self.banco.agora.isoformat())   # default now()
            if self.tabela == "painel_entradas" and "entrada_json" in x:
                x["entrada_json"] = _como_jsonb(x["entrada_json"])
            ajustados.append(x)
        return super().insert(ajustados if isinstance(r, list) else ajustados[0])


class BancoPainel(BancoFiltrado):
    def __init__(self, agora=AGORA, **tabelas):
        super().__init__(**tabelas)
        self.agora = agora

    def table(self, nome):
        return _ConsultaPainel(self, nome)

    def votos(self, vaga=None, par="BTCUSDT", dia=D):
        return [v for v in self.linhas("painel_votos", simbolo=par, dia_utc=dia) if vaga is None or v["vaga"] == vaga]


class Falso:
    """
    Provedor falso de UM modelo. `roteiro` e uma lista de passos consumida
    em ordem (o ultimo se repete). Passo: RespostaBruta, uma excecao (que
    e levantada) ou uma funcao(chamada) -> RespostaBruta.
    """

    def __init__(self, vaga, modelo, roteiro, registro):
        self.vaga, self.modelo, self.roteiro, self.registro = vaga, modelo, list(roteiro), registro

    def chamar_bruto(self, sistema, usuario, forma="sistema", schema=None, temperature=0.2, max_tokens=4000,
                     json_objeto=True):
        chamada = {"vaga": self.vaga, "modelo": self.modelo, "sistema": sistema, "usuario": usuario, "forma": forma,
                   "schema": schema, "temperature": temperature, "max_tokens": max_tokens,
                   "json_objeto": json_objeto, "par": _par_do_texto(usuario), "dia": _dia_do_texto(usuario)}
        self.registro.append(chamada)
        passo = self.roteiro.pop(0) if len(self.roteiro) > 1 else self.roteiro[0]
        if callable(passo) and not isinstance(passo, RespostaBruta):
            passo = passo(chamada)
        if isinstance(passo, BaseException):
            raise passo
        return passo


def _par_do_texto(usuario):
    return "BTCUSDT" if '"asset": "BTCUSDT"' in usuario else "ETHUSDT" if '"asset": "ETHUSDT"' in usuario else "?"


def _dia_do_texto(usuario):
    i = usuario.find('"last_closed_day_utc": "')
    return usuario[i + 24:i + 34] if i >= 0 else "?"


def falsos(roteiros=None):
    """
    Um Falso por modelo das 3 cadeias. `roteiros` aceita chave por modelo
    ou por vaga ('G', 'N', 'C'); quem nao tem roteiro vota UP.
    """
    roteiros = roteiros or {}
    registro = []
    provs = {}
    for vaga in VAGAS:
        for modelo in vaga.cadeia:
            passos = roteiros.get(modelo) or roteiros.get(vaga.id) or [votar("UP")]
            provs[(vaga.provedor, modelo)] = Falso(vaga.id, modelo, passos, registro)
    return provs, registro


def texto_voto(trend="UP", confidence=0.6, **extra):
    return json.dumps({"case_for_up": "o retorno de 30 dias foi positivo", "case_for_down": "a volatilidade subiu",
                       "trend_call": trend, "confidence": confidence,
                       "resumo_pt": "Os numeros mostram alta moderada.", **extra})


def votar(trend="UP"):
    return lambda ch: RespostaBruta(True, texto=texto_voto(trend), http_status=200,
                                    modelo_efetivo=ch["modelo"], id_geracao="gen-teste",
                                    tokens_entrada=900, tokens_saida=300)


FALHA_503 = RespostaBruta(False, http_status=503, erro="503 Service Unavailable", tipo_erro="transitoria")
UPSTREAM_429 = RespostaBruta(False, http_status=429, limit_source="upstream_provider_shared_pool",
                             erro='{"error":{"message":"qwen is temporarily rate-limited upstream"}}',
                             tipo_erro="transitoria", retry_after=35.0)
CONTA_429 = RespostaBruta(False, http_status=429, erro="Rate limit exceeded: free-models-per-day",
                          tipo_erro="conta_diaria")
MODELO_404 = RespostaBruta(False, http_status=404, erro='{"error":{"message":"model not found"}}', tipo_erro="modelo")
GEMMA_400 = RespostaBruta(False, http_status=400, tipo_erro="modelo",
                          erro="ClientError: 400 INVALID_ARGUMENT. Developer instruction is not enabled for "
                               "models/gemma-4-31b-it")
POLITICA_404 = RespostaBruta(False, http_status=404, tipo_erro="configuracao",
                             erro='{"error":{"message":"No endpoints found matching your data policy"}}')
CHAVE_403 = RespostaBruta(False, http_status=403, erro="PERMISSION_DENIED: API key not valid",
                          tipo_erro="configuracao")


def mercado(par="BTCUSDT", fechamentos=None, dia=D_DT):
    fech = fechamentos or (SERIE_BTC if par == "BTCUSDT" else SERIE_ETH)
    agora_ms = int((dia + timedelta(days=1, minutes=17)).timestamp() * 1000)
    fechados = diarios(fech, agora_ms=agora_ms)[:-1]   # descarta o dia em andamento
    return Mercado(par=par, horarios=[], fechados_h=[], diarios=fechados, preco=fech[-1])


def mercados(*pares):
    return {p: mercado(p) for p in (pares or ("BTCUSDT",))}


def ciclo(banco, agora, provs, pares=("BTCUSDT",), prazo=1e9, relogio=None, http=None, binance=None):
    banco.agora = agora
    esperas = []
    p = Painel(banco, provedores=provs, http=http, agora=agora, relogio=relogio or (lambda: 0.0),
               esperar=esperas.append)
    res = p.rodar(mercados(*pares), prazo, binance=binance)
    return res, esperas


_seq = [0]


def linha_voto(vaga, trend=None, par="BTCUSDT", dia=D, modelo=None, erro=None, http_status=None,
               limit_source=None, inicio=None):
    """Uma tentativa ja gravada. Com `trend` e voto valido; sem, falha (ou em_andamento)."""
    _seq[0] += 1
    valido = trend is not None
    return {"id": f"semente-{_seq[0]}", "tipo": "painel", "dia_utc": dia, "simbolo": par, "vaga": vaga,
            "modelo_pedido": modelo or PRINCIPAL[vaga], "provedor": PROVEDOR[vaga], "tentativa": 1,
            "forma_prompt": "sistema", "inicio": inicio or f"{dia}T00:00:00+00:00",
            "http_status": 200 if valido else http_status, "limit_source": limit_source,
            "erro": None if valido else (erro or "503 Service Unavailable"), "json_valido": valido,
            "trend_call": trend}


def modelos_chamados(registro, vaga, desde=0, par=None):
    return [c["modelo"] for c in registro[desde:] if c["vaga"] == vaga and (par is None or c["par"] == par)]


class RespostaHttp:
    def __init__(self, status, conteudo=b"", dados=None):
        self.status_code, self.content, self._dados = status, conteudo, dados

    def json(self):
        return self._dados


class HttpFalso:
    def __init__(self, rotas):
        self.rotas, self.pedidos = rotas, []

    def get(self, url, timeout=None, headers=None):
        self.pedidos.append(url)
        r = self.rotas.get(url, ConnectionError(f"sem rota para {url}"))
        if isinstance(r, BaseException):
            raise r
        return r


URL_FNG = "https://api.alternative.me/fng/?limit=10"


def rss(itens):
    corpo = "".join(f"<item><title>{escape(t)}</title><pubDate>{format_datetime(q)}</pubDate></item>"
                    for t, q in itens)
    return f'<?xml version="1.0"?><rss><channel>{corpo}</channel></rss>'.encode()


def fng_item(dia_dt, valor):
    return {"value": str(valor), "value_classification": "x", "timestamp": str(int(dia_dt.timestamp()))}


# ================================================================== agregar


def test_agregar_exemplos_da_tabela_9_5():
    casos = [
        ({"G": "UP", "N": "UP", "C": "SIDEWAYS"}, (2, 3, "compra")),
        ({"G": "UP", "N": "UP", "C": "DOWN"}, (1, 3, "neutro")),
        ({"G": "DOWN", "N": "SIDEWAYS", "C": "SIDEWAYS"}, (-1, 3, "venda")),
        ({"G": "UP", "N": "SIDEWAYS", "C": "DOWN"}, (0, 3, "neutro")),
        ({"G": "DOWN", "N": "SIDEWAYS", "C": None}, (-1, 2, "venda")),
    ]
    for votos, esperado in casos:
        assert agregar(votos) == esperado, f"{votos}: {agregar(votos)} != {esperado}"


def test_agregar_com_v2_exige_unanimidade_para_comprar():
    assert agregar({"G": "UP", "N": "UP", "C": None}) == (2, 2, "compra")
    assert agregar({"G": "UP", "N": "SIDEWAYS", "C": None}) == (1, 2, "neutro")
    assert agregar({"G": None, "N": "DOWN", "C": "UP"}) == (0, 2, "neutro")
    assert agregar({"G": "UP", "N": "UP", "C": "UP"}) == (3, 3, "compra")
    assert agregar({"G": "DOWN", "N": "DOWN", "C": "DOWN"}) == (-3, 3, "venda")


def test_agregar_quorum_minimo_de_2():
    assert agregar({"G": "UP", "N": None, "C": None})[1:] == (1, "sem_quorum")
    assert agregar({"G": None, "N": "DOWN", "C": None})[1:] == (1, "sem_quorum")
    assert agregar({"G": None, "N": None, "C": None}) == (0, 0, "sem_quorum")
    # So os 3 valores validos contam como voto.
    assert agregar({"G": "UP", "N": "up", "C": "BUY"})[1:] == (1, "sem_quorum")


# ================================================================== validar_voto


def test_validar_voto_aceita_json_em_bloco_de_codigo():
    texto = "Claro! Aqui esta:\n```json\n" + texto_voto("DOWN", 0.3) + "\n```\nEspero ter ajudado."
    voto = validar_voto(texto)
    assert voto is not None and voto.trend_call == "DOWN" and voto.confidence == 0.3


def test_validar_voto_normaliza_trend_call_minusculo_e_com_espaco():
    assert validar_voto(texto_voto(" up ")).trend_call == "UP"
    assert validar_voto(texto_voto("sideways")).trend_call == "SIDEWAYS"
    assert validar_voto(texto_voto("Down\n")).trend_call == "DOWN"


def test_validar_voto_recusa_trend_call_fora_dos_3_valores():
    for ruim in ("BULLISH", "NEUTRAL", "UP/SIDEWAYS", "", 1, None):
        assert validar_voto(texto_voto(ruim)) is None, ruim


def test_validar_voto_confidence_tem_de_estar_em_0_1():
    assert validar_voto(texto_voto(confidence=1.2)) is None
    assert validar_voto(texto_voto(confidence=-0.1)) is None
    assert validar_voto(texto_voto(confidence="alta")) is None
    assert validar_voto(texto_voto(confidence=0)).confidence == 0
    assert validar_voto(texto_voto(confidence=1)).confidence == 1


def test_validar_voto_json_invalido_vira_none_nunca_sideways():
    ruins = [None, "", "UP", "Minha resposta: SIDEWAYS", "{trend_call: UP}", "[1, 2, 3]",
             '{"trend_call": "UP", "confidence": 0.5}',            # faltam campos
             '{"case_for_up": "a", "case_for_down": "b", "trend_call": "UP", "confidence": 0.5, "resumo_pt": ']
    for texto in ruins:
        assert validar_voto(texto) is None, f"{texto!r} deveria ser nao-resposta"


def test_validar_voto_ignora_chaves_extras_e_corta_textos():
    voto = validar_voto(texto_voto(extra_key="x", case_for_up="a" * 500, case_for_down="b" * 500,
                                   resumo_pt="c" * 900))
    assert voto is not None
    assert (len(voto.case_for_up), len(voto.case_for_down), len(voto.resumo_pt)) == (300, 300, 400)


# ================================================================== numeros_sem_origem

ENTRADA_FIXA = {
    "asset": "BTCUSDT", "last_closed_day_utc": D,
    "return_pct": {"1d": 2.5, "7d": -4.1, "30d": 12.3, "90d": 30.8},
    "distance_from_moving_average_pct": {"10d": 1.2, "20d": 3.4, "30d": 5.6, "50d": 7.7, "70d": 9.8, "100d": 14.0},
    "volatility_30d_annualized_pct": 41.7,
    "distance_from_90d_high_pct": -8.6,
    "market": {"fear_greed_index_today": 55, "fear_greed_index_7d_ago": "unavailable",
               "eth_vs_btc_return_30d_pct": -3.2},
    "headlines_last_24h": ["Bitcoin passa de 112000 dolares"],
}


def _voto(resumo, up="sem numeros", down="sem numeros"):
    return VotoDoPainel(case_for_up=up, case_for_down=down, trend_call="UP", confidence=0.5, resumo_pt=resumo)


def test_numeros_sem_origem_numero_da_entrada_nao_conta():
    v = _voto("Subiu 2,5% no dia, caiu 4.1% na semana e 12.3% no mes; medo em 55; volatilidade de 41,7%.",
              up="o preco passou de 112000", down="esta -8.6% abaixo da maxima e o ETH/BTC caiu 3,2%")
    assert numeros_sem_origem(v, ENTRADA_FIXA) == 0
    assert numeros_sem_origem(_voto("alta de 12.35%"), ENTRADA_FIXA) == 0    # tolerancia de 0,1


def test_numeros_sem_origem_numero_so_na_chave_da_entrada_nao_conta():
    # "90 dias" e "100 dias" estao na entrada (chaves `90d`, `100d`) e no prompt.
    assert numeros_sem_origem(_voto("o retorno de 90 dias foi 30,8% e a media de 100 dias ficou 14% abaixo"),
                              ENTRADA_FIXA) == 0


def test_numeros_sem_origem_inteiro_de_0_a_10_nao_conta():
    assert numeros_sem_origem(_voto("Nas proximas 2 a 4 semanas, 3 sinais; nota 10 de 10, 0 alertas."),
                              ENTRADA_FIXA) == 0


def test_numeros_sem_origem_numero_inventado_conta():
    assert numeros_sem_origem(_voto("O preco deve ir a 95000 em breve."), ENTRADA_FIXA) == 1
    assert numeros_sem_origem(_voto("alta de 10.5% e 11 dias"), ENTRADA_FIXA) == 2
    assert numeros_sem_origem(_voto("alta de 12.5%"), ENTRADA_FIXA) == 1     # 0,2 longe do 12.3


# ================================================================== montar_entrada


def _serie_simples():
    f = [100.0] * 300
    f[-1], f[-8], f[-31], f[-60], f[-91] = 110.0, 88.0, 125.0, 137.5, 200.0
    return f


def test_montar_entrada_campos_e_uma_casa_decimal():
    e = montar_entrada(mercado("BTCUSDT", _serie_simples()), None, None, {"titulos": None})
    assert set(e) == {"asset", "last_closed_day_utc", "return_pct", "distance_from_moving_average_pct",
                      "volatility_30d_annualized_pct", "distance_from_90d_high_pct", "market",
                      "headlines_last_24h"}, sorted(e)
    assert e["asset"] == "BTCUSDT" and e["last_closed_day_utc"] == D
    # 110 contra 100 (1d), 88 (7d), 125 (30d), 200 (90d).
    assert e["return_pct"] == {"1d": 10.0, "7d": 25.0, "30d": -12.0, "90d": -45.0}
    # SMA10 = 99,8; SMA20 = 99,9; SMA30 = 99,93; SMA50 = 100,46; SMA70 = 100,86; SMA100 = 101,605.
    assert e["distance_from_moving_average_pct"] == {"10d": 10.2, "20d": 10.1, "30d": 10.1, "50d": 9.5,
                                                     "70d": 9.1, "100d": 8.3}
    # Desvio populacional dos 30 ultimos retornos (-0,2; -0,12; +0,136; +0,1 e 26 zeros) x raiz(365).
    assert e["volatility_30d_annualized_pct"] == 100.3
    # Maxima de D-89..D e 137,5 (o 200 esta em D-90, fora da janela).
    assert e["distance_from_90d_high_pct"] == -20.0
    assert e["market"] == {"fear_greed_index_today": "unavailable", "fear_greed_index_7d_ago": "unavailable",
                           "eth_vs_btc_return_30d_pct": "unavailable"}
    assert e["headlines_last_24h"] == "unavailable"


def test_montar_entrada_arredonda_tudo_com_1_casa():
    e = montar_entrada(mercado("BTCUSDT"), None, None, {"titulos": []})
    numeros = list(e["return_pct"].values()) + list(e["distance_from_moving_average_pct"].values()) + \
        [e["volatility_30d_annualized_pct"], e["distance_from_90d_high_pct"]]
    for n in numeros:
        assert isinstance(n, float) and round(n, 1) == n and len(repr(n).split(".")[1]) == 1, n
    assert e["headlines_last_24h"] == []     # feeds responderam, sem manchete no dia


def test_montar_entrada_fear_greed_pelo_timestamp_nao_pela_posicao():
    # Como a API devolve (mais novo primeiro), com o dia de HOJE (D+1) ja publicado em data[0].
    fng = [fng_item(D_DT + timedelta(days=1), 80)] + \
          [fng_item(D_DT - timedelta(days=k), 55 if k == 0 else 30 if k == 7 else 40 + k) for k in range(9)]
    e = montar_entrada(mercado(), None, fng, {"titulos": None})
    assert e["market"]["fear_greed_index_today"] == 55, e["market"]
    assert e["market"]["fear_greed_index_7d_ago"] == 30, e["market"]
    # Qualquer ordem da lista da o mesmo resultado.
    e2 = montar_entrada(mercado(), None, list(reversed(fng)), {"titulos": None})
    assert e2["market"] == e["market"]
    # Sem o item de D-7: "unavailable" (e nunca o vizinho).
    sem_7d = [x for x in fng if x["timestamp"] != str(int((D_DT - timedelta(days=7)).timestamp()))]
    e3 = montar_entrada(mercado(), None, sem_7d, {"titulos": None})
    assert e3["market"]["fear_greed_index_7d_ago"] == "unavailable"
    assert e3["market"]["fear_greed_index_today"] == 55


def test_montar_entrada_ethbtc_30d_pela_data():
    def candle(dias_antes, fech):
        ab = D_MS - dias_antes * UM_DIA
        return {"abertura_em": ab, "fechamento": fech, "fechamento_em": ab + UM_DIA - 1}
    velas = [candle(k, 0.050 if k == 0 else 0.040 if k == 30 else 0.9) for k in range(31, -1, -1)]
    e = montar_entrada(mercado(), velas, None, {"titulos": None})
    assert e["market"]["eth_vs_btc_return_30d_pct"] == 25.0
    # Sem a vela de D-30: indisponivel (nao pega a vizinha).
    e2 = montar_entrada(mercado(), [v for v in velas if v["abertura_em"] != D_MS - 30 * UM_DIA], None,
                        {"titulos": None})
    assert e2["market"]["eth_vs_btc_return_30d_pct"] == "unavailable"


def test_buscar_manchetes_dia_d_mais_novo_primeiro_sem_duplicata():
    longo = "L" * 300
    cointelegraph = rss([("Nova de amanha", D_DT + timedelta(days=1, minutes=5)),
                         ("A", D_DT + timedelta(hours=20)), (longo, D_DT + timedelta(hours=15)),
                         ("B", D_DT + timedelta(hours=10)), ("Velha", D_DT - timedelta(hours=1))])
    decrypt = rss([("A", D_DT + timedelta(hours=20)), ("C", D_DT + timedelta(hours=12)),
                   ("Velha 2", D_DT - timedelta(hours=3))])
    http = HttpFalso({FEEDS["cointelegraph"]: RespostaHttp(200, cointelegraph),
                      FEEDS["decrypt"]: RespostaHttp(200, decrypt)})
    m = buscar_manchetes(http, D_DT)
    assert m["titulos"] == ["A", "L" * 200, "C", "B"], m["titulos"]
    assert m["estado"] == "ok" and m["status"] == {"cointelegraph": 200, "decrypt": 200}
    assert m["itens"] == {"cointelegraph": 5, "decrypt": 3}

    # Um feed fora: segue com o outro, marcado 'partial'.
    http2 = HttpFalso({FEEDS["cointelegraph"]: RespostaHttp(200, cointelegraph),
                       FEEDS["decrypt"]: RespostaHttp(403, b"cloudflare")})
    m2 = buscar_manchetes(http2, D_DT)
    assert m2["estado"] == "partial" and m2["titulos"][0] == "A"

    # Mais de 10 no dia: os 10 mais novos.
    muitos = rss([(f"T{h:02d}", D_DT + timedelta(hours=h)) for h in range(12)])
    http3 = HttpFalso({FEEDS["cointelegraph"]: RespostaHttp(200, muitos), FEEDS["decrypt"]: RespostaHttp(200, rss([]))})
    assert buscar_manchetes(http3, D_DT)["titulos"] == [f"T{h:02d}" for h in range(11, 1, -1)]


def test_manchetes_e_fear_greed_indisponiveis_nao_impedem_o_painel():
    http = HttpFalso({FEEDS["cointelegraph"]: RespostaHttp(403, b"cloudflare"),
                      FEEDS["decrypt"]: RespostaHttp(503, b""), URL_FNG: TimeoutError("fng fora")})
    banco = BancoPainel()
    provs, registro = falsos()
    res, _ = ciclo(banco, AGORA, provs, http=http)
    [e] = banco.linhas("painel_entradas", simbolo="BTCUSDT")
    assert e["entrada_json"]["headlines_last_24h"] == "unavailable"
    assert e["entrada_json"]["market"]["fear_greed_index_today"] == "unavailable"
    assert e["headlines_estado"] == "unavailable"
    assert e["rss_status"] == {"cointelegraph": 403, "decrypt": 503}
    assert e["fng_hoje_ts"] is None and e["fng_7d_ts"] is None
    assert len(registro) == 3 and res.vereditos["BTCUSDT"]["veredito"] == "compra"


# ================================================================== a entrada e uma so


def test_entrada_montada_uma_vez_e_reutilizada_por_vagas_e_ciclos():
    fng = [fng_item(D_DT - timedelta(days=k), 50 + k) for k in range(10)]
    manchetes = rss([("Bitcoin sobe", D_DT + timedelta(hours=9))])
    http = HttpFalso({URL_FNG: RespostaHttp(200, dados={"data": fng}),
                      FEEDS["cointelegraph"]: RespostaHttp(200, manchetes), FEEDS["decrypt"]: RespostaHttp(200, rss([]))})
    banco = BancoPainel()
    provs, registro = falsos({"C": [FALHA_503]})
    ciclo(banco, AGORA, provs, pares=("BTCUSDT", "ETHUSDT"), http=http)

    assert len(banco.linhas("painel_entradas")) == 2
    pedidos_c1 = len(http.pedidos)
    assert pedidos_c1 == 2 * 3, http.pedidos     # F&G + 2 feeds, uma vez por par
    for par in ("BTCUSDT", "ETHUSDT"):
        [e] = banco.linhas("painel_entradas", simbolo=par)
        chamadas = [c for c in registro if c["par"] == par]
        assert {c["vaga"] for c in chamadas} == {"G", "N", "C"}
        assert {_sha(c["usuario"]) for c in chamadas} == {e["sha256_usuario"]}, par
        assert {c["usuario"] for c in chamadas} == {e["prompt_texto"]}
        assert all(c["sistema"] == SISTEMA and _sha(c["sistema"]) == e["sha256_sistema"] for c in chamadas)
        assert all(c["forma"] == "sistema" and c["temperature"] == 0.2 and c["max_tokens"] == 4000
                   for c in chamadas)
        assert e["fng_hoje_ts"] == int(D_DT.timestamp())

    # Ciclo seguinte: F&G e RSS mudaram, mas a entrada NAO e remontada, e o
    # texto enviado e o mesmo (o jsonb devolve as chaves em outra ordem).
    http.rotas[URL_FNG] = RespostaHttp(200, dados={"data": [fng_item(D_DT, 99)]})
    antes = len(registro)
    ciclo(banco, em(1, 10), provs, pares=("BTCUSDT", "ETHUSDT"), http=http)
    novas = registro[antes:]
    assert novas and {c["vaga"] for c in novas} == {"C"}
    assert len(http.pedidos) == pedidos_c1, "a entrada foi remontada no 2o ciclo"
    assert len(banco.linhas("painel_entradas")) == 2
    for c in novas:
        [e] = banco.linhas("painel_entradas", simbolo=c["par"])
        assert _sha(c["usuario"]) == e["sha256_usuario"], "texto do usuario mudou entre ciclos"


def test_entrada_ja_gravada_por_outra_execucao_e_usada_como_esta():
    # Outra execucao congelou a entrada de D (com F&G disponivel); esta
    # execucao, sem http, montaria uma entrada diferente -- e nao pode.
    gravada = montar_entrada(mercado(), None, [fng_item(D_DT, 61), fng_item(D_DT - timedelta(days=7), 20)],
                             {"titulos": ["Manchete gravada"]})
    usuario = modulo.textos_do_prompt(gravada)[1]
    banco = BancoPainel(painel_entradas=[{
        "id": "ent-1", "dia_utc": D, "simbolo": "BTCUSDT", "prompt_versao": "painel-v1",
        "sha256_sistema": _sha(SISTEMA), "sha256_usuario": _sha(usuario), "sha256_embutido": "x",
        "entrada_json": _como_jsonb(gravada), "prompt_texto": usuario}])
    provs, registro = falsos()
    ciclo(banco, AGORA, provs)
    assert len(banco.linhas("painel_entradas")) == 1
    assert len(registro) == 3 and {c["usuario"] for c in registro} == {usuario}


# ================================================================== congelamento


def test_v3_congela_na_hora():
    banco = BancoPainel()
    provs, registro = falsos({"C": [votar("SIDEWAYS")]})
    res, _ = ciclo(banco, AGORA, provs)
    v = res.vereditos["BTCUSDT"]
    assert v is not None and v["veredito"] == "compra" and v["motivo_congelamento"] == "V=3"
    assert (v["soma"], v["validos"]) == (2, 3)
    assert v["votos"] == {"G": "UP", "N": "UP", "C": "SIDEWAYS"}
    ids = {x["id"]: x for x in banco.votos()}
    assert all(ids[v["votos_ids"][vaga]]["json_valido"] and ids[v["votos_ids"][vaga]]["vaga"] == vaga
               for vaga in "GNC")
    assert v["regra_versao"] == "painel-agg-v1" and v["prompt_versao"] == "painel-v1"
    assert len(banco.linhas("painel_veredito")) == 1 and res.chamadas == 3
    # Linhas de auditoria completas.
    for linha in banco.votos():
        assert linha["erro"] is None and linha["http_status"] == 200 and linha["modelo_efetivo"]
        assert linha["temperature"] == 0.2 and linha["max_tokens"] == 4000 and linha["forma_prompt"] == "sistema"
        assert linha["numeros_sem_origem"] is not None
    assert {c["modelo"]: c["json_objeto"] for c in registro} == {m: True for m in PRINCIPAL.values()}


def test_v2_so_congela_a_partir_das_04h_de_d_mais_1():
    banco = BancoPainel()
    provs, registro = falsos({"C": [FALHA_503]})
    res, _ = ciclo(banco, AGORA, provs)
    assert res.vereditos["BTCUSDT"] is None, "V=2 congelou antes das 04:00"
    res, _ = ciclo(banco, em(3, 59), provs)
    assert res.vereditos["BTCUSDT"] is None, "V=2 congelou antes das 04:00"
    antes = len(registro)
    res, _ = ciclo(banco, em(4, 0), provs)
    v = res.vereditos["BTCUSDT"]
    assert v is not None and v["motivo_congelamento"] == "V=2 apos 04:00"
    assert v["veredito"] == "compra" and (v["soma"], v["validos"]) == (2, 2)
    assert v["votos"] == {"G": "UP", "N": "UP", "C": None} and v["votos_ids"]["C"] is None
    # A vaga que faltava ainda teve a sua chance nesse ciclo (a 5a do dia).
    assert modelos_chamados(registro, "C", antes) == [PRINCIPAL["C"]]


def test_v2_nao_congela_pelo_teto_antes_das_04h():
    # A vaga C ja esgotou as 5 do dia as 02:00: V=2 ainda assim espera as
    # 04:00 (a regra do teto e so para V < 2).
    sementes = [linha_voto("G", "UP"), linha_voto("N", "DOWN")] + [linha_voto("C") for _ in range(5)]
    banco = BancoPainel(painel_votos=sementes)
    provs, registro = falsos()
    res, _ = ciclo(banco, em(2, 0), provs)
    assert registro == [] and res.vereditos["BTCUSDT"] is None
    res, _ = ciclo(banco, em(4, 5), provs)
    assert registro == []
    v = res.vereditos["BTCUSDT"]
    assert v["motivo_congelamento"] == "V=2 apos 04:00" and v["veredito"] == "neutro"


def test_v_menor_que_2_vira_sem_quorum_as_18h_sem_chamar_ninguem():
    sementes = [linha_voto("G", "UP"), linha_voto("N"), linha_voto("C")]
    banco = BancoPainel(painel_votos=sementes)
    provs, registro = falsos({"N": [FALHA_503], "C": [FALHA_503]})
    res, _ = ciclo(banco, em(17, 59), provs)
    assert res.vereditos["BTCUSDT"] is None
    assert len(registro) == 4    # N e C ainda tentam ate as 18:00
    # A partir das 18:00: congela com o que houver -- mesmo que N e C
    # fossem votar agora, ninguem e chamado (9.6.3 e 9.7).
    provs2, registro2 = falsos()
    res, _ = ciclo(banco, em(18, 0), provs2)
    v = res.vereditos["BTCUSDT"]
    assert registro2 == [], f"chamou depois das 18:00: {[c['modelo'] for c in registro2]}"
    assert v["veredito"] == "sem_quorum" and v["motivo_congelamento"] == "18:00"
    assert v["votos"] == {"G": "UP", "N": None, "C": None} and v["validos"] == 1


def test_v_menor_que_2_congela_pelo_teto_antes_das_18h():
    sementes = [linha_voto("G", "UP")] + [linha_voto("N") for _ in range(5)] + [linha_voto("C") for _ in range(5)]
    banco = BancoPainel(painel_votos=sementes)
    provs, registro = falsos()
    res, _ = ciclo(banco, em(2, 10), provs)
    v = res.vereditos["BTCUSDT"]
    assert registro == []
    assert v["veredito"] == "sem_quorum" and v["motivo_congelamento"] == "teto" and v["validos"] == 1


def test_teto_alcancado_no_proprio_ciclo_congela():
    sementes = [linha_voto("G", "UP")] + [linha_voto("N") for _ in range(4)] + [linha_voto("C") for _ in range(5)]
    banco = BancoPainel(painel_votos=sementes)
    provs, registro = falsos({"N": [FALHA_503]})
    res, _ = ciclo(banco, em(2, 10), provs)
    assert modelos_chamados(registro, "N") and not modelos_chamados(registro, "C")
    # N gastou a 5a agora: o teto fecha o dia.
    assert res.vereditos["BTCUSDT"]["motivo_congelamento"] == "teto"


def test_virada_de_dia_congela_pendencia_antiga_sem_chamar():
    antiga = {"id": "ent-antiga", "dia_utc": ONTEM, "simbolo": "BTCUSDT", "prompt_versao": "painel-v1",
              "sha256_sistema": "x", "sha256_usuario": "y", "sha256_embutido": "z", "entrada_json": {},
              "prompt_texto": "entrada de D-1"}
    sementes = [linha_voto("G", "UP", dia=ONTEM), linha_voto("N", dia=ONTEM)]
    banco = BancoPainel(painel_entradas=[antiga], painel_votos=sementes)
    provs, registro = falsos()
    ciclo(banco, AGORA, provs)
    [velho] = banco.linhas("painel_veredito", dia_utc=ONTEM, simbolo="BTCUSDT")
    assert velho["veredito"] == "sem_quorum" and velho["motivo_congelamento"] == "virada de dia"
    assert velho["votos"] == {"G": "UP", "N": None, "C": None}
    assert registro and {c["dia"] for c in registro} == {D}, "chamou alguem para o dia antigo"
    # E o congelamento nao se repete no ciclo seguinte.
    ciclo(banco, em(1, 10), falsos()[0])
    assert len(banco.linhas("painel_veredito", dia_utc=ONTEM)) == 1


def test_virada_de_dia_com_dois_votos_tambem_e_sem_quorum():
    # 9.6.4: pendencia antiga congela sem_quorum mesmo com 2 votos -- nenhuma
    # carteira pode ter usado esse veredito no dia dele, e ele nao pode
    # contar no rearme da G3.
    antiga = {"id": "ent-antiga", "dia_utc": ONTEM, "simbolo": "BTCUSDT", "prompt_versao": "painel-v1",
              "sha256_sistema": "x", "sha256_usuario": "y", "sha256_embutido": "z", "entrada_json": {},
              "prompt_texto": "entrada de D-1"}
    sementes = [linha_voto("G", "UP", dia=ONTEM), linha_voto("N", "UP", dia=ONTEM)]
    banco = BancoPainel(painel_entradas=[antiga], painel_votos=sementes)
    ciclo(banco, AGORA, falsos()[0])
    [velho] = banco.linhas("painel_veredito", dia_utc=ONTEM, simbolo="BTCUSDT")
    assert velho["veredito"] == "sem_quorum" and velho["validos"] == 2, velho


def test_veredito_ja_congelado_nao_chama_ninguem():
    congelado = {"id": "ver-1", "dia_utc": D, "simbolo": "BTCUSDT", "prompt_versao": "painel-v1",
                 "regra_versao": "painel-agg-v1", "votos": {"G": "UP", "N": "UP", "C": None},
                 "votos_ids": {"G": "a", "N": "b", "C": None}, "soma": 2, "validos": 2, "veredito": "compra",
                 "motivo_congelamento": "V=2 apos 04:00"}
    banco = BancoPainel(painel_veredito=[congelado])
    http = HttpFalso({})
    provs, registro = falsos()
    res, esperas = ciclo(banco, em(5, 10), provs, http=http)
    assert registro == [] and res.chamadas == 0 and esperas == []
    assert http.pedidos == [] and banco.linhas("painel_entradas") == []
    assert res.vereditos["BTCUSDT"]["id"] == "ver-1"
    # E depois de um V=3 no 1o ciclo, o 2o nao chama ninguem.
    banco2 = BancoPainel()
    provs2, registro2 = falsos()
    ciclo(banco2, AGORA, provs2)
    antes = len(registro2)
    ciclo(banco2, em(1, 10), provs2)
    assert len(registro2) == antes == 3


def test_nunca_repergunta_vaga_que_ja_votou():
    # G ja votou UP nesta (D, par); se fosse chamada de novo, votaria DOWN.
    banco = BancoPainel(painel_votos=[linha_voto("G", "UP")])
    provs, registro = falsos({"G": [votar("DOWN")], "C": [FALHA_503]})
    ciclo(banco, AGORA, provs)
    assert modelos_chamados(registro, "G") == []
    assert modelos_chamados(registro, "N") == [PRINCIPAL["N"]]
    # 2o ciclo: so a vaga C (a unica sem voto valido) e chamada.
    antes = len(registro)
    ciclo(banco, em(1, 10), provs)
    assert {c["vaga"] for c in registro[antes:]} == {"C"}
    assert len([v for v in banco.votos() if v["json_valido"]]) == 2


def test_resposta_invalida_nao_vira_voto():
    lixo = RespostaBruta(True, texto="I think the trend is SIDEWAYS.", http_status=200, modelo_efetivo="dots")
    banco = BancoPainel()
    provs, _ = falsos({"C": [lixo]})
    res, _ = ciclo(banco, AGORA, provs)
    assert res.vereditos["BTCUSDT"] is None, "resposta invalida contou como voto"
    linhas = banco.votos("C")
    assert len(linhas) == 2
    assert all(not x["json_valido"] and x.get("trend_call") is None and x["erro"] == "json invalido" for x in linhas)
    assert all(x["resposta_bruta"] == lixo.texto for x in linhas)


# ================================================================== limites de chamadas


def test_no_maximo_2_por_ciclo_e_5_por_dia_por_vaga_e_ativo():
    banco = BancoPainel()
    provs, registro = falsos({"C": [FALHA_503]})
    por_ciclo = []
    for hora, minuto in ((0, 17), (1, 10), (2, 10), (3, 10)):
        antes = len(registro)
        ciclo(banco, em(hora, minuto), provs)
        por_ciclo.append(len(modelos_chamados(registro, "C", antes)))
    assert por_ciclo == [2, 2, 1, 0], por_ciclo
    assert sorted(x["tentativa"] for x in banco.votos("C")) == [1, 2, 3, 4, 5]


def test_teto_e_por_vaga_e_ativo():
    # BTC esgotado para C nao tira as tentativas de C no ETH.
    sementes = [linha_voto("C") for _ in range(5)]
    banco = BancoPainel(painel_votos=sementes)
    provs, registro = falsos({"C": [FALHA_503]})
    ciclo(banco, AGORA, provs, pares=("BTCUSDT", "ETHUSDT"))
    assert modelos_chamados(registro, "C", par="BTCUSDT") == []
    assert len(modelos_chamados(registro, "C", par="ETHUSDT")) == 2


def test_linha_em_andamento_conta_para_o_teto():
    # Quatro tentativas interrompidas (job morto no meio): so sobra 1.
    sementes = [linha_voto("C", erro="em_andamento") for _ in range(4)]
    banco = BancoPainel(painel_votos=sementes)
    provs, registro = falsos({"C": [FALHA_503]})
    ciclo(banco, AGORA, provs)
    assert len(modelos_chamados(registro, "C")) == 1
    # Com cinco, nenhuma.
    banco2 = BancoPainel(painel_votos=[linha_voto("C", erro="em_andamento") for _ in range(5)])
    provs2, registro2 = falsos()
    ciclo(banco2, AGORA, provs2)
    assert modelos_chamados(registro2, "C") == []


def test_linha_e_inserida_antes_da_requisicao():
    banco = BancoPainel()
    vistas = []

    def confere(ch):
        linhas = [dict(v) for v in banco.tabelas.get("painel_votos", [])
                  if v["vaga"] == "C" and v["modelo_pedido"] == ch["modelo"]]
        vistas.append([(v["erro"], v.get("http_status"), v["json_valido"]) for v in linhas])
        return votar("UP")(ch)

    provs, _ = falsos({"C": [confere]})
    ciclo(banco, AGORA, provs)
    assert vistas == [[("em_andamento", None, False)]], vistas
    [linha] = banco.votos("C")
    assert linha["json_valido"] and linha["erro"] is None


def test_provedor_que_levanta_excecao_ainda_conta_a_tentativa():
    banco = BancoPainel()
    provs, registro = falsos({PRINCIPAL["C"]: [TimeoutError("read timed out")], "C": [FALHA_503]})
    res, esperas = ciclo(banco, AGORA, provs)
    linhas = sorted(banco.votos("C"), key=lambda x: x["tentativa"])
    assert len(linhas) == 2 and res.erro_de_configuracao == []
    assert linhas[0]["modelo_pedido"] == PRINCIPAL["C"] and "TimeoutError" in linhas[0]["erro"]
    assert linhas[0]["http_status"] is None and not linhas[0]["json_valido"]
    assert esperas == [10.0]
    # No ciclo seguinte ela continua contando: sobram 5 - 2 = 3.
    for hora in (1, 2, 3):
        ciclo(banco, em(hora, 10), provs)
    assert len(banco.votos("C")) == 5


def test_espera_so_entre_as_tentativas_do_mesmo_ciclo():
    # min(Retry-After, 20 s), ou 10 s; e nenhuma espera depois da ultima
    # tentativa do ciclo (o pior caso de 280 s conta 1 espera por ativo).
    banco = BancoPainel()
    provs, _ = falsos({"C": [FALHA_503]})
    _, esperas = ciclo(banco, AGORA, provs, pares=("BTCUSDT", "ETHUSDT"))
    assert esperas == [10.0, 10.0], esperas
    banco2 = BancoPainel()
    curto = RespostaBruta(False, http_status=429, erro="upstream", limit_source="upstream", tipo_erro="transitoria",
                          retry_after=3.0)
    provs2, _ = falsos({PRINCIPAL["N"]: [curto]})
    _, esperas2 = ciclo(banco2, AGORA, provs2)
    assert esperas2 == [3.0], esperas2


# ================================================================== cadeia


def test_cadeia_principal_primeiro_depois_reserva_nao_tentada():
    banco = BancoPainel()
    provs, registro = falsos({"C": [FALHA_503]})
    dots, qwen, glm = CADEIA["C"]
    por_ciclo = []
    for hora in (0, 1, 2):
        antes = len(registro)
        ciclo(banco, em(hora, 17), provs)
        por_ciclo.append(modelos_chamados(registro, "C", antes))
    assert por_ciclo == [[dots, qwen], [dots, glm], [dots]], por_ciclo


def test_cadeia_volta_a_primeira_reserva_quando_todas_ja_foram_tentadas():
    dots, qwen, glm = CADEIA["C"]
    banco = BancoPainel(painel_votos=[linha_voto("C", modelo=qwen), linha_voto("C", modelo=glm)])
    provs, registro = falsos({"C": [FALHA_503]})
    ciclo(banco, AGORA, provs)
    assert modelos_chamados(registro, "C") == [dots, qwen]


def test_erro_de_modelo_404_tira_o_modelo_do_dia():
    dots, qwen, glm = CADEIA["C"]
    banco = BancoPainel()
    provs, registro = falsos({dots: [MODELO_404], "C": [FALHA_503]})
    ciclo(banco, AGORA, provs)
    assert modelos_chamados(registro, "C") == [dots, qwen]
    antes = len(registro)
    ciclo(banco, em(1, 10), provs)
    assert modelos_chamados(registro, "C", antes) == [glm, qwen], "o modelo 404 voltou a ser chamado"


def test_gemma_recusando_instrucao_fica_fora_do_dia_entre_ciclos():
    gemini, gemma31, gemma26 = CADEIA["G"]
    sementes = [linha_voto("G", modelo=gemma31, http_status=400, erro=GEMMA_400.erro),
                linha_voto("G", modelo=gemma26)]
    banco = BancoPainel(painel_votos=sementes)
    provs, registro = falsos({"G": [FALHA_503]})
    ciclo(banco, AGORA, provs)
    assert modelos_chamados(registro, "G") == [gemini, gemma26], modelos_chamados(registro, "G")


# ================================================================== 429


def test_429_da_cota_da_conta_para_o_openrouter_no_resto_do_dia():
    banco = BancoPainel()
    caixa = {}

    def c_espera_o_n(_ch):
        # Garante a ordem: esta resposta so volta depois que N viu a cota.
        fim = time.monotonic() + 5
        while not caixa["painel"]._openrouter_parado and time.monotonic() < fim:
            time.sleep(0.005)
        return FALHA_503

    provs, registro = falsos({"G": [FALHA_503], "N": [CONTA_429], "C": [c_espera_o_n]})
    painel = Painel(banco, provedores=provs, agora=AGORA, relogio=lambda: 0.0, esperar=[].append)
    caixa["painel"] = painel
    res = painel.rodar(mercados("BTCUSDT", "ETHUSDT"), 1e9)
    assert modelos_chamados(registro, "N") == [PRINCIPAL["N"]], "N seguiu chamando depois da cota da conta"
    assert len(modelos_chamados(registro, "C")) <= 1
    assert len(modelos_chamados(registro, "G")) == 4          # o Google nao e afetado
    [linha_n] = [x for x in banco.linhas("painel_votos") if x["vaga"] == "N"]
    assert linha_n["limit_source"] == "conta_diaria"
    assert all(v is None for v in res.vereditos.values())     # G ainda pode votar hoje

    # Ciclo seguinte, mesmo dia UTC: le `limit_source='conta_diaria'` do banco.
    provs2, registro2 = falsos()
    res2, _ = ciclo(banco, em(1, 10), provs2, pares=("BTCUSDT", "ETHUSDT"))
    assert {c["vaga"] for c in registro2} == {"G"}, [c["modelo"] for c in registro2]
    # Com N e C parados ate 00:00, V=1 e ninguem mais pode votar: teto.
    assert {v["motivo_congelamento"] for v in res2.vereditos.values()} == {"teto"}
    assert {v["veredito"] for v in res2.vereditos.values()} == {"sem_quorum"}


def test_cota_da_conta_de_ontem_nao_para_hoje():
    ontem = linha_voto("N", dia=ONTEM, http_status=429, limit_source="conta_diaria",
                       inicio=(AGORA - timedelta(minutes=40)).isoformat())
    banco = BancoPainel(painel_votos=[ontem])
    provs, registro = falsos()
    ciclo(banco, AGORA, provs)
    assert {c["vaga"] for c in registro} == {"G", "N", "C"}


def test_429_do_upstream_nao_para_o_openrouter():
    nemo, ultra, _ = CADEIA["N"]
    banco = BancoPainel()
    provs, registro = falsos({nemo: [UPSTREAM_429, votar("UP")], ultra: [FALHA_503]})
    res, esperas = ciclo(banco, AGORA, provs)
    assert modelos_chamados(registro, "N") == [nemo, ultra]
    assert esperas == [20.0]           # min(Retry-After 35, 20)
    assert modelos_chamados(registro, "C") == [PRINCIPAL["C"]]
    assert res.vereditos["BTCUSDT"] is None
    antes = len(registro)
    res, _ = ciclo(banco, em(1, 10), provs)
    assert modelos_chamados(registro, "N", antes) == [nemo]
    assert res.vereditos["BTCUSDT"]["motivo_congelamento"] == "V=3"


# ================================================================== configuracao


def test_erro_de_configuracao_vai_para_a_lista_e_nao_derruba_as_outras_vagas():
    banco = BancoPainel()
    provs, registro = falsos({"G": [CHAVE_403]})
    res, _ = ciclo(banco, AGORA, provs)
    assert len(res.erro_de_configuracao) == 1 and res.erro_de_configuracao[0].startswith("vaga G")
    assert modelos_chamados(registro, "G") == [PRINCIPAL["G"]], "tentou reserva depois de erro de configuracao"
    assert modelos_chamados(registro, "N") == [PRINCIPAL["N"]]
    assert modelos_chamados(registro, "C") == [PRINCIPAL["C"]]
    assert sorted(x["vaga"] for x in banco.votos() if x["json_valido"]) == ["C", "N"]


def test_404_de_politica_de_dados_401_402_e_chave_ausente_sao_configuracao():
    casos = {
        "404 politica": POLITICA_404,
        "401": RespostaBruta(False, http_status=401, erro="No auth credentials found", tipo_erro="configuracao"),
        "402": RespostaBruta(False, http_status=402, erro="Payment required", tipo_erro="configuracao"),
        "400 malformada": RespostaBruta(False, http_status=400, erro="Invalid request body", tipo_erro="bug"),
        "chave ausente": ErroDoProvedor("OPENROUTER_API_KEY ausente no ambiente"),
    }
    for nome, falha in casos.items():
        banco = BancoPainel()
        provs, registro = falsos({"N": [falha]})
        res, _ = ciclo(banco, AGORA, provs)
        assert len(res.erro_de_configuracao) == 1 and res.erro_de_configuracao[0].startswith("vaga N"), \
            f"{nome}: {res.erro_de_configuracao}"
        assert modelos_chamados(registro, "N") == [PRINCIPAL["N"]], nome
        validos = sorted(x["vaga"] for x in banco.votos() if x["json_valido"])
        if nome == "400 malformada":
            # Bug de requisicao e da vaga, nao da conta: a C segue.
            assert validos == ["C", "G"], nome
        else:
            # Chave, pagamento ou politica valem para a conta OpenRouter
            # inteira: a C para quando o erro chega (9.6). Como as vagas
            # rodam em paralelo, a 1a chamada dela pode ja ter saido.
            assert "G" in validos and "N" not in validos, nome
            assert len(modelos_chamados(registro, "C")) <= 1, nome


def test_provedores_reais_sem_chave_deixam_o_job_vermelho():
    # Regressao (revisao de 25/09): secret nao criado no GitHub vira string
    # vazia; o provedor real capturava o "ausente" dentro do proprio try e
    # devolvia 'transitoria' -- vagas mudas com o job verde.
    antes = {k: os.environ.get(k) for k in ("OPENROUTER_API_KEY", "GEMINI_API_KEY")}
    os.environ["OPENROUTER_API_KEY"] = ""
    os.environ["GEMINI_API_KEY"] = ""
    try:
        banco = BancoPainel()
        res, _ = ciclo(banco, AGORA, {})     # {} = provedores reais
        assert res.erro_de_configuracao, "chave ausente tem de deixar o job vermelho"
        assert all("ausente" in (v.get("erro") or "") for v in banco.votos())
        assert len(banco.votos()) == 3, "uma tentativa por vaga e para -- sem gastar o teto"
    finally:
        for k, v in antes.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


# ================================================================== prazo


def test_nenhuma_requisicao_comeca_a_menos_de_70s_do_prazo():
    banco = BancoPainel()
    provs, registro = falsos()
    res, _ = ciclo(banco, AGORA, provs, relogio=lambda: 1000.0, prazo=1069.9)
    assert registro == [] and banco.linhas("painel_votos") == [] and res.chamadas == 0
    res, _ = ciclo(banco, AGORA, provs, relogio=lambda: 1000.0, prazo=1070.0)
    assert len(registro) == 3


def test_prazo_corta_no_meio_do_ciclo():
    # So a vaga C pendente, nos 2 ativos; cada chamada "leva" 50 s.
    def pendente_so_c():
        return [linha_voto(v, "UP", par=p) for v in "GN" for p in ("BTCUSDT", "ETHUSDT")]

    for prazo, esperado in ((169.0, 2), (170.0, 3)):
        relogio = [0.0]

        def lenta(_ch, relogio=relogio):
            relogio[0] += 50.0
            return FALHA_503

        banco = BancoPainel(painel_votos=pendente_so_c())
        provs, registro = falsos({"C": [lenta]})
        ciclo(banco, AGORA, provs, pares=("BTCUSDT", "ETHUSDT"), relogio=lambda r=relogio: r[0], prazo=prazo)
        assert len(registro) == esperado, f"prazo {prazo}: {len(registro)} chamadas"


# ================================================================== G3: rearme


def test_compras_do_painel_desde_so_quorum_depois_da_saida_em_ordem():
    def ver(dias, veredito, par="BTCUSDT"):
        return {"dia_utc": (D_DT + timedelta(days=dias)).date().isoformat(), "simbolo": par, "veredito": veredito}

    linhas = [ver(2, "compra"), ver(-3, "compra"), ver(0, "sem_quorum"), ver(1, "neutro"), ver(-1, "compra"),
              ver(-2, "venda"), ver(0, "compra", "ETHUSDT"), ver(3, "sem_quorum"), ver(4, "venda")]
    banco = BancoFiltrado(painel_veredito=linhas)
    saida = int((D_DT - timedelta(days=1) + timedelta(hours=15)).timestamp() * 1000)   # D-1 15:00
    # D-1 (fecha depois da saida) compra, D sem_quorum (fora), D+1 neutro,
    # D+2 compra, D+3 sem_quorum (fora), D+4 venda.
    assert compras_do_painel_desde(banco, "BTCUSDT", saida) == [True, False, True, False]
    # Saida exatamente no fechamento de D-1: D-1 nao conta mais.
    fecha_d_menos_1 = D_MS - 1
    assert compras_do_painel_desde(banco, "BTCUSDT", fecha_d_menos_1) == [False, True, False]
    assert compras_do_painel_desde(banco, "ETHUSDT", saida) == [True]


# ================================================================== execucao


def _rodar_tudo() -> int:
    testes = sorted((n, f) for n, f in globals().items() if n.startswith("test_") and callable(f))
    falhas = []
    for nome, funcao in testes:
        try:
            funcao()
            print(f"  ok    {nome}")
        except AssertionError as erro:
            falhas.append(nome)
            print(f"  FALHA {nome}: {erro}")
        except Exception as erro:  # noqa: BLE001
            falhas.append(nome)
            print(f"  ERRO  {nome}: {type(erro).__name__}: {erro}")
    print(f"\n{len(testes) - len(falhas)}/{len(testes)} passaram")
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(_rodar_tudo())
