"""
Backtest da estrategia hibrida -- passo 7 do roteiro.

    python backend/backtest/run_hybrid.py --dias 30          # ensaio curto
    python backend/backtest/run_hybrid.py                    # ano inteiro
    python backend/backtest/run_hybrid.py --sem-supabase

Roda `cerebro decide + Risk Engine valida` no mesmo motor, mesmo periodo
e mesmos parametros da baseline do passo 4, pra que a comparacao seja
direta contra o que ja esta gravado em `backtest_runs`.

## Cache de respostas do modelo

Um ano de candles de 1h com cadencia de 6h da ~1.460 consultas ao
Gemini. No free tier isso e da ordem do limite DIARIO inteiro, e leva
mais de uma hora de relogio por causa do limite por minuto. Sem cache,
qualquer erro no meio -- rede, cota, um 500 da API -- significaria
recomecar do zero e gastar a cota de novo, possivelmente sem sobrar
cota pra terminar no mesmo dia.

Entao toda resposta e gravada em disco, indexada pelo hash do prompt
exato que a gerou. Rodar de novo com os mesmos candles nao gasta
chamada nenhuma. E como o prompt inclui as features, o preco e o estado
da posicao, duas situacoes diferentes nunca colidem no mesmo hash.

O cache tambem torna o resultado reproduzivel: reexecutar a analise
depois devolve exatamente as mesmas teses, e nao uma nova amostragem de
um modelo estocastico.

**O que o cache NAO permite:** trocar os parametros de risco de graca.
O prompt inclui `posicao_aberta` -- o cerebro precisa saber se ha
posicao pra escolher entre HOLD e NO_TRADE -- entao mudar o risco muda
o dimensionamento, que muda quando as posicoes abrem e fecham, que muda
o prompt. Medido: trocar risco de 1% pra 0,25% fez o cache divergir
depois de 9 consultas das 364.

A consequencia e maior que o custo em cota, e e propriedade do
experimento e nao do cache: **as respostas do LLM nao sao independentes
da configuracao de risco**. Cada configuracao e uma execucao propria,
com seu proprio caminho pela serie. Comparar dois niveis de risco e
comparar dois experimentos, nao a mesma execucao dimensionada de dois
jeitos.
"""

from dotenv import load_dotenv
load_dotenv()

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backtest.engine import TAXA_PADRAO, rodar_backtest, salvar_json  # noqa: E402
from backtest.run_baseline import buscar_historico_com_cache, salvar_no_supabase  # noqa: E402
from backtest.strategies import ESTRATEGIAS  # noqa: E402
from brain.cadencia import INTERVALO_PADRAO_HORAS  # noqa: E402
from brain.hybrid_strategy import (  # noqa: E402
    MULTIPLICADORES_POR_HORIZONTE,
    EstrategiaHibrida,
)
from brain.llm_analyst import AnalistaLLM, TeseDeOperacao, montar_prompt  # noqa: E402
from risk.risk_engine import ParametrosDeRisco  # noqa: E402

PASTA_CACHE_LLM = Path(__file__).resolve().parent / ".cache" / "llm"
PASTA_RESULTADOS = Path(__file__).resolve().parent / "resultados"

NOME_DA_ESTRATEGIA = "hibrida_llm_risk"


class SemCache(RuntimeError):
    """Faltou resposta no cache e o modo offline proibe chamar a API."""


class CotaDiariaEsgotada(RuntimeError):
    """Acabou a cota do dia. Reenviar nao adianta -- so o dia seguinte resolve."""


class AnalistaComCache:
    """
    Envolve o `AnalistaLLM` com cache em disco e reenvio em caso de
    limite de requisicao.

    A chave e o hash do prompt exato -- nao das features soltas -- porque
    e o prompt que determina a resposta. Prompt igual, resposta igual;
    prompt diferente por um centavo de preco, chamada nova.
    """

    def __init__(
        self, analista: AnalistaLLM, pasta: Path, tentativas: int = 8,
        somente_cache: bool = False,
    ):
        self.analista = analista
        self.pasta = pasta
        self.tentativas = tentativas
        # somente_cache: nunca chama a API. Serve pra descobrir ate onde o
        # cache cobre sem gastar um unico request de cota -- e a cota
        # diaria e o recurso escasso aqui (500/dia, secao 8).
        self.somente_cache = somente_cache
        self.pasta.mkdir(parents=True, exist_ok=True)
        self.acertos_de_cache = 0
        self.chamadas_reais = 0
        self.esperas_por_limite = 0

    def analisar(self, features, simbolo, posicao_aberta=False, preco_atual=None):
        prompt = montar_prompt(features, simbolo, posicao_aberta, preco_atual)
        chave = hashlib.sha256(
            f"{self.analista.modelo}\n{prompt}".encode("utf-8")
        ).hexdigest()
        arquivo = self.pasta / f"{chave}.json"

        if arquivo.exists():
            self.acertos_de_cache += 1
            return TeseDeOperacao.model_validate_json(arquivo.read_text(encoding="utf-8"))

        if self.somente_cache:
            raise SemCache(
                f"sem resposta em cache apos {self.acertos_de_cache} consultas"
            )

        tese = self._chamar_com_reenvio(features, simbolo, posicao_aberta, preco_atual)
        arquivo.write_text(tese.model_dump_json(), encoding="utf-8")
        self.chamadas_reais += 1
        return tese

    def _chamar_com_reenvio(self, features, simbolo, posicao_aberta, preco_atual):
        espera = 20.0
        for tentativa in range(1, self.tentativas + 1):
            try:
                return self.analista.analisar(
                    features=features, simbolo=simbolo,
                    posicao_aberta=posicao_aberta, preco_atual=preco_atual,
                )
            except Exception as erro:  # noqa: BLE001
                # Cota diaria nao e erro transitorio: nenhuma espera dentro
                # deste processo resolve, so a virada do dia. Reenviar 8
                # vezes com backoff so troca um erro imediato por nove
                # minutos de espera pelo mesmo erro.
                if _e_cota_diaria(erro):
                    raise CotaDiariaEsgotada(
                        f"cota diaria do free tier esgotada apos "
                        f"{self.chamadas_reais} chamadas nesta rodada. "
                        f"O cache preservou tudo -- rode o mesmo comando amanha "
                        f"e ele retoma de onde parou."
                    ) from erro
                if not _e_transitorio(erro) or tentativa == self.tentativas:
                    raise
                self.esperas_por_limite += 1
                print(f"      {_classificar(erro)}; aguardando {espera:.0f}s "
                      f"(tentativa {tentativa}/{self.tentativas})", flush=True)
                time.sleep(espera)
                espera = min(espera * 2, 120.0)
        raise RuntimeError("inalcancavel")


# Erros que valem reenviar. Duas familias, e a segunda custou uma rodada
# de ~420 chamadas pra aparecer: alem do limite de requisicao (429), o
# Gemini devolve 503 UNAVAILABLE quando o modelo esta congestionado.
# E transitorio como o 429 e some sozinho, mas nao tem nada a ver com
# cota -- tratar so o 429 fazia a rodada inteira morrer num soluco de
# alguns segundos do servidor.
LIMITE_DE_REQUISICAO = ("429", "RESOURCE_EXHAUSTED", "QUOTA", "RATE")
INDISPONIBILIDADE = ("503", "UNAVAILABLE", "500", "INTERNAL", "502", "504",
                     "DEADLINE_EXCEEDED", "TIMEOUT", "CONNECTION")


def _e_cota_diaria(erro) -> bool:
    """
    Distingue as duas cotas que o Gemini impoe, porque elas pedem reacoes
    opostas: a de por-minuto passa sozinha em segundos e vale esperar; a
    de por-dia so passa amanha e esperar dentro do processo e desperdicio
    de relogio.

    A mensagem de erro traz o `quotaId`, e e nele que a diferenca aparece
    de forma confiavel -- o codigo HTTP e 429 nos dois casos.
    """
    texto = str(erro)
    return "PerDay" in texto or "GenerateRequestsPerDayPerProjectPerModel" in texto


def _e_transitorio(erro) -> bool:
    texto = str(erro).upper()
    return any(marca in texto for marca in LIMITE_DE_REQUISICAO + INDISPONIBILIDADE)


def _classificar(erro) -> str:
    texto = str(erro).upper()
    if any(marca in texto for marca in LIMITE_DE_REQUISICAO):
        return "limite de requisicao"
    return "modelo indisponivel (transitorio)"


def auditar_operacoes(resultado, capital, taxa) -> list[str]:
    """
    Reconstroi as metricas a partir SO da lista de operacoes, sem usar
    nenhuma funcao do motor. Mesma checagem feita na baseline: se o
    motor errou, os numeros divergem aqui.
    """
    problemas = []
    caixa, quantidade, entrada = capital, 0.0, None
    trades = vencedores = 0

    for operacao in resultado.operacoes:
        preco = operacao["preco"]
        if operacao["lado"] == "BUY":
            if quantidade != 0:
                problemas.append(f"BUY com posicao aberta no indice {operacao['indice']}")
            entrada = caixa
            quantidade = (caixa - caixa * taxa) / preco
            caixa = 0.0
        else:
            if quantidade <= 0:
                problemas.append(f"SELL sem posicao no indice {operacao['indice']}")
            bruto = quantidade * preco
            caixa = bruto - bruto * taxa
            trades += 1
            if entrada is not None and caixa > entrada:
                vencedores += 1
            quantidade = 0.0

    if abs(caixa - resultado.metricas["saldo_final"]) > 0.02:
        problemas.append(
            f"saldo final: motor={resultado.metricas['saldo_final']} auditoria={caixa:.2f}"
        )
    if trades != resultado.metricas["numero_trades"]:
        problemas.append(
            f"trades: motor={resultado.metricas['numero_trades']} auditoria={trades}"
        )
    if trades:
        acerto = vencedores / trades * 100
        if abs(acerto - (resultado.metricas["taxa_acerto_pct"] or 0)) > 0.02:
            problemas.append(
                f"taxa de acerto: motor={resultado.metricas['taxa_acerto_pct']} "
                f"auditoria={acerto:.2f}"
            )
    return problemas


def main() -> int:
    parser = argparse.ArgumentParser(description="Backtest da estrategia hibrida (passo 7).")
    parser.add_argument("--simbolo", default="BTCUSDT")
    parser.add_argument("--intervalo", default="1h")
    parser.add_argument("--inicio", default="1 year ago UTC")
    parser.add_argument("--fim", default=None)
    parser.add_argument("--dias", type=int, default=None,
                        help="corta o historico nos ULTIMOS N dias (ensaio curto)")
    parser.add_argument("--primeiros-dias", type=int, default=None,
                        help="corta nos PRIMEIROS N dias -- e por onde o cache "
                             "cresce, ja que o backtest caminha do inicio pro fim")
    parser.add_argument("--somente-cache", action="store_true",
                        help="falha em vez de chamar a API; nao gasta cota nenhuma")
    parser.add_argument("--capital", type=float, default=10_000.0)
    parser.add_argument("--taxa", type=float, default=TAXA_PADRAO)
    parser.add_argument("--cadencia-horas", type=int, default=INTERVALO_PADRAO_HORAS)
    parser.add_argument("--risco", type=float, default=0.01)
    parser.add_argument("--exposicao-maxima", type=float, default=0.50)
    parser.add_argument("--sem-supabase", action="store_true")
    parser.add_argument("--nome", default=NOME_DA_ESTRATEGIA,
                        help="strategy_name no banco. Rodadas com configuracao de "
                             "risco diferente precisam de nomes diferentes, senao "
                             "uma sobrescreve a leitura da outra na comparacao")
    parser.add_argument("--sem-baselines", action="store_true",
                        help="nao regrava as baselines do recorte (ja estao no banco)")
    parser.add_argument("--notas", default="estrategia hibrida do passo 7")
    argumentos = parser.parse_args()

    print(f"\n=== hibrida {argumentos.simbolo} {argumentos.intervalo} ===")
    candles = buscar_historico_com_cache(
        argumentos.simbolo, argumentos.intervalo, argumentos.inicio, argumentos.fim
    )
    if argumentos.dias:
        candles = candles[-(argumentos.dias * 24):]
        print(f"  recorte: ultimos {argumentos.dias} dias ({len(candles)} candles)")
    if argumentos.primeiros_dias:
        candles = candles[: argumentos.primeiros_dias * 24]
        print(f"  recorte: primeiros {argumentos.primeiros_dias} dias "
              f"({len(candles)} candles)")

    cadencia_ms = argumentos.cadencia_horas * 60 * 60 * 1000
    consultas_previstas = len(candles) // argumentos.cadencia_horas
    print(f"  cadencia de {argumentos.cadencia_horas}h -> ~{consultas_previstas} consultas")

    analista = AnalistaComCache(
        AnalistaLLM(), PASTA_CACHE_LLM, somente_cache=argumentos.somente_cache
    )
    print(f"  modelo: {analista.analista.modelo}"
          + ("  [somente cache -- nenhuma chamada de API]" if argumentos.somente_cache else ""))

    parametros_base = ParametrosDeRisco(
        risco_por_operacao=argumentos.risco,
        exposicao_maxima_pct=argumentos.exposicao_maxima,
    )
    estrategia = EstrategiaHibrida(
        analista,
        simbolo=argumentos.simbolo,
        intervalo_ms=cadencia_ms,
        parametros_base=parametros_base,
    )

    # Progresso: uma rodada longa sem sinal de vida e indistinguivel de
    # uma rodada travada.
    inicio_s = time.time()
    ultimo_aviso = [0]

    class ComProgresso:
        __name__ = argumentos.nome

        def __call__(self, contexto):
            if estrategia.consultas >= ultimo_aviso[0] + 50:
                ultimo_aviso[0] = estrategia.consultas
                decorrido = time.time() - inicio_s
                print(f"    {estrategia.consultas}/{consultas_previstas} consultas  "
                      f"({analista.chamadas_reais} reais, {analista.acertos_de_cache} de cache)  "
                      f"{decorrido / 60:.1f} min", flush=True)
            return estrategia(contexto)

    try:
        resultado = rodar_backtest(
            candles, ComProgresso(),
            capital_inicial=argumentos.capital,
            taxa_por_operacao=argumentos.taxa,
            nome_estrategia=argumentos.nome,
        )
    except CotaDiariaEsgotada as erro:
        # Nao e falha da rodada, e uma pausa. Sai com codigo proprio (2) e
        # mensagem util em vez de traceback: nada aqui esta quebrado, so
        # acabou o combustivel do dia.
        cobertura = analista.acertos_de_cache + analista.chamadas_reais
        print(f"\n  === PAUSA: {erro} ===")
        print(f"  progresso desta rodada: {cobertura}/{consultas_previstas} consultas "
              f"({analista.chamadas_reais} novas hoje)")
        print(f"  respostas em cache no total: "
              f"{len(list(PASTA_CACHE_LLM.glob('*.json')))}")
        print("  nada foi perdido. Rode o mesmo comando amanha.")
        return 2
    except SemCache as erro:
        print(f"\n  === PARADO: {erro} ===")
        print("  rode sem --somente-cache para completar (gasta cota).")
        return 2

    # As baselines rodam sobre EXATAMENTE os mesmos candles. E a unica
    # forma de a comparacao valer: as que estao gravadas em
    # `backtest_runs` cobrem o ano inteiro, e comparar um recorte contra
    # o ano seria comparar duas perguntas diferentes.
    referencias = {}
    for nome, estrategia_base in ESTRATEGIAS.items():
        referencias[nome] = rodar_backtest(
            candles, estrategia_base,
            capital_inicial=argumentos.capital,
            taxa_por_operacao=argumentos.taxa,
            nome_estrategia=nome,
        )

    print("\n  --- comparacao no mesmo periodo ---")
    for r in (referencias["buy_and_hold"], referencias["ema_crossover"], resultado):
        print("  " + r.resumo())

    hibrida_pct = resultado.metricas["retorno_total_pct"]
    print()
    for nome, referencia in referencias.items():
        base_pct = referencia.metricas["retorno_total_pct"]
        diferenca = hibrida_pct - base_pct
        veredito = "BATEU" if diferenca > 0 else ("empatou" if abs(diferenca) < 0.01 else "PERDEU")
        print(f"  vs {nome:<15} {hibrida_pct:+.2f}% contra {base_pct:+.2f}%  "
              f"-> {veredito} por {abs(diferenca):.2f} pontos")

    auditoria = estrategia.resumo_de_auditoria()
    print(f"\n  consultas ao cerebro: {auditoria['consultas_ao_cerebro']}  "
          f"(reais: {analista.chamadas_reais}, cache: {analista.acertos_de_cache})")
    print(f"  direcoes do LLM:      {auditoria['direcoes_do_llm']}")
    print(f"  horizontes:           {auditoria['horizontes_devolvidos']}")
    print(f"  overrides de risco:   {auditoria['overrides_de_risco']}")
    print(f"  bloqueios de risco:   {auditoria['bloqueios_de_risco']}")

    PASTA_RESULTADOS.mkdir(parents=True, exist_ok=True)
    salvar_json(resultado, PASTA_RESULTADOS / f"{argumentos.simbolo}_{argumentos.nome}.json")

    problemas = auditar_operacoes(resultado, argumentos.capital, argumentos.taxa)
    if problemas:
        print("\n  *** AUDITORIA DIVERGIU ***")
        for problema in problemas:
            print(f"    - {problema}")
        return 1
    print("\n  auditoria independente das operacoes: bate.")

    if argumentos.sem_supabase:
        print("  --sem-supabase: nada gravado.")
        return 0

    params_extra = {
        "multiplicadores_por_horizonte": {
            h: {"stop": s, "take": t} for h, (s, t) in MULTIPLICADORES_POR_HORIZONTE.items()
        },
        "cadencia_horas": argumentos.cadencia_horas,
        "risco_por_operacao": argumentos.risco,
        "exposicao_maxima_pct": argumentos.exposicao_maxima,
        "modelo": analista.analista.modelo,
        "provedor": analista.analista.provedor.nome,
        "auditoria": auditoria,
        # Consumo de cota desta rodada. `chamadas_reais` e o que conta
        # contra o limite diario -- `consultas_ao_cerebro` inclui os
        # acertos de cache, que nao custam nada. Sem separar os dois, o
        # painel de cota superestimaria o gasto de toda rodada repetida.
        "chamadas_reais": analista.chamadas_reais,
        "acertos_de_cache": analista.acertos_de_cache,
    }
    try:
        identificador = salvar_no_supabase(
            resultado, argumentos.simbolo, argumentos.notas, params_extra
        )
        print(f"  supabase: {argumentos.nome} gravado ({identificador})")

        # As baselines do MESMO recorte tambem vao pro banco. As que ja
        # estao la cobrem o ano inteiro; sem estas, quem consultar a
        # tabela depois compararia 91 dias contra 365 e concluiria
        # bobagem. Cada linha carrega seu proprio periodo, mas deixar a
        # comparacao explicita evita o erro.
        for nome, referencia in ({} if argumentos.sem_baselines else referencias).items():
            identificador = salvar_no_supabase(
                referencia, argumentos.simbolo,
                f"{argumentos.notas} -- baseline no mesmo recorte, para comparacao direta",
                {"recorte_de_comparacao": True},
            )
            print(f"  supabase: {nome} (recorte) gravado ({identificador})")
    except Exception as erro:  # noqa: BLE001
        print(f"  supabase: falhou -- {type(erro).__name__}: {erro}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
