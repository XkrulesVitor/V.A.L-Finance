"""
Adaptadores das regras de `estrategia/` para o ciclo ao vivo.

Cada familia responde a mesma pergunta -- "o que o ultimo dia fechado
diz?" -- no mesmo formato (`Sinal`), para o ciclo nao ter um `if` por
carteira. As regras em si continuam em `estrategia/`, compartilhadas com o
backtest; aqui so ha a traducao.
"""

from dataclasses import dataclass, field

from backtest.engine import BUY, HOLD, NO_TRADE, SELL
from estrategia import alvo, rsi2, tartarugas
from estrategia import tendencia_diaria as reguas


@dataclass
class Sinal:
    pronto: bool                      # False: sem historico (ou sem veredito do painel)
    compra: bool
    venda: bool
    dia_fechamento_em: int | None     # fechamento_em do dia que gerou o sinal
    motivo: str
    leitura: dict = field(default_factory=dict)


def ler(regra: str, diarios: list[dict]) -> Sinal:
    """Sinal do ULTIMO dia da lista (a lista termina num dia ja fechado)."""
    if not diarios:
        return Sinal(False, False, False, None, "sem candles diarios")
    dia = diarios[-1]
    atr = alvo.atr_pct(diarios)
    if regra == "reguas":
        leitura = reguas.detalhar([c["fechamento"] for c in diarios])
        v = leitura["votos"]
        pronto = v is not None
        compra, venda = pronto and v >= reguas.ENTRA_COM, pronto and v <= reguas.SAI_COM
        motivo = reguas.motivo(v, "BUY" if compra else "SELL" if venda else "HOLD")
    elif regra == "tartarugas":
        leitura = tartarugas.leitura(diarios)
        pronto = leitura.get("pronta", False)
        compra, venda = pronto and leitura["rompeu_alta"], pronto and leitura["rompeu_baixa"]
        motivo = tartarugas.motivo(leitura, "BUY" if compra else "SELL" if venda else "HOLD")
    elif regra == "rsi2":
        leitura = rsi2.leitura(diarios)
        pronto = leitura.get("pronta", False)
        compra = pronto and leitura["em_alta_longa"] and leitura["queda_curta"]
        venda = pronto and leitura["repicou"]
        motivo = rsi2.motivo(leitura, "BUY" if compra else "SELL" if venda else "HOLD")
    else:
        raise ValueError(f"regra sem adaptador diario: {regra}")
    leitura = {**leitura, "atr_pct": atr}
    return Sinal(pronto, bool(compra), bool(venda), dia["fechamento_em"], motivo, leitura)


def motivo(regra: str, leitura: dict, acao: str) -> str:
    """
    O motivo gravado descreve a ACAO tomada, e nao so o sinal: uma T1
    comprada que mantem grava "6 de 6 prazos em alta", nao "(entra com 4)".
    """
    if regra == "reguas":
        return reguas.motivo(leitura.get("votos"), acao)
    if regra == "rsi2":
        return rsi2.motivo(leitura, acao)
    if regra == "tartarugas":
        if not leitura.get("pronta"):
            return "historico diario insuficiente"
        if acao == BUY:
            return f"fechou acima da maior alta de {tartarugas.ENTRADA_DIAS} dias"
        if acao == SELL:
            return f"fechou abaixo da menor baixa de {tartarugas.SAIDA_DIAS} dias"
        if acao == HOLD:
            return f"comprada; sai se fechar abaixo de {leitura['minima_20d']:,.2f} (menor baixa de 20 dias)"
        if leitura.get("rompeu_alta"):
            return "rompimento de alta"
        return (f"sem rompimento (alta de {tartarugas.ENTRADA_DIAS}d a {leitura['maxima_55d']:,.2f}, "
                f"baixa de {tartarugas.SAIDA_DIAS}d a {leitura['minima_20d']:,.2f})")
    raise ValueError(f"regra sem motivo: {regra}")


def nivel_de_stop(regra: str, preco_entrada: float, leitura: dict) -> tuple[float, str]:
    """(nivel, motivo que a saida grava se ele disparar)."""
    catastrofe = reguas.nivel_de_stop(preco_entrada)
    if regra == "tartarugas" and leitura.get("n"):
        nivel = tartarugas.nivel_de_stop(preco_entrada, leitura["n"])
        return nivel, ("stop de catastrofe" if nivel == catastrofe else "stop 2N")
    return catastrofe, "stop de catastrofe"


def compras_desde(regra: str, diarios: list[dict], desde_ms: int) -> list[bool]:
    """
    Para cada dia fechado DEPOIS de `desde_ms`, em ordem: o sinal daquele
    dia era de compra? Dias sem sinal pronto ficam de fora. E o que o rearme
    do stop gain (`estrategia.alvo.rearmada`) consome. Recalculado dos
    candles a cada ciclo: deterministico, sem estado a mais no banco.
    """
    saida = []
    for i, dia in enumerate(diarios):
        if dia["fechamento_em"] <= desde_ms:
            continue
        s = ler(regra, diarios[: i + 1])
        if s.pronto:
            saida.append(s.compra)
    return saida
