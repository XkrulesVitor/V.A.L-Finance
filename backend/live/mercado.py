"""
O instantaneo de mercado de um ciclo: buscado UMA vez por par e
compartilhado pelas seis carteiras.

Todas veem os mesmos candles e o mesmo preco. Se cada carteira buscasse o
seu, duas carteiras com a mesma regra (T1 e G1) poderiam decidir sobre
precos diferentes no mesmo ciclo, e a comparacao entre elas mediria o
relogio, nao a regra.
"""

from dataclasses import dataclass

from features.candles import somente_fechados

HORAS_A_PEDIR = 72          # cobre com folga os maiores buracos do agendador (6,4 h)
DIAS_JANELA = 300           # janela fixa dos indicadores diarios (ver indicadores.py)
DIAS_A_PEDIR = DIAS_JANELA + 1   # +1: o dia em andamento, que e descartado


@dataclass
class Mercado:
    par: str
    horarios: list[dict]      # 1h, inclui o candle em curso
    fechados_h: list[dict]    # 1h ja fechados
    diarios: list[dict]       # 1d ja fechados, os ultimos DIAS_JANELA
    preco: float              # ticker do instante

    @property
    def ultimo_h(self) -> dict | None:
        return self.fechados_h[-1] if self.fechados_h else None

    @property
    def em_curso(self) -> dict | None:
        return self.horarios[-1] if len(self.horarios) > len(self.fechados_h) else None

    @property
    def dia(self) -> dict | None:
        """O ultimo dia UTC fechado."""
        return self.diarios[-1] if self.diarios else None

    @property
    def completo(self) -> bool:
        return bool(self.fechados_h) and bool(self.diarios)


def buscar_mercado(binance, par: str) -> Mercado:
    horarios = binance.buscar_candles(par, intervalo="1h", limite=HORAS_A_PEDIR)
    diarios = somente_fechados(binance.buscar_candles(par, intervalo="1d", limite=DIAS_A_PEDIR))
    return Mercado(
        par=par,
        horarios=horarios,
        fechados_h=somente_fechados(horarios),
        diarios=diarios[-DIAS_JANELA:],
        preco=binance.buscar_preco(par),
    )
