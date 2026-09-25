"""
Conferencia da regra de tendencia diaria (as Reguas), a regra pura.

    python backend/tests/test_tendencia_diaria.py

Os testes do ciclo ao vivo que usa esta regra (a carteira T1) estao em
`tests/test_carteiras.py`, junto com os das outras cinco carteiras -- o
ciclo e o mesmo para todas (`live/ciclo_carteira.py`).

## O que mais importa aqui

- **o dia em andamento nao vota.** O estudo usa sempre o voto do dia
  anterior; se o ciclo ao vivo deixasse o dia corrente entrar, ele
  decidiria com um fechamento que ainda nao aconteceu -- e o numero do
  backtest deixaria de valer para ele.
- **o stop e conferido em todo fechamento de 1h nao visto**, e a saida
  sai no preco daquele fechamento.
- **depois de um stop, nao recompra com o voto velho.**
- **o explicador nunca bloqueia**: se o LLM cair, a operacao fica
  gravada igual.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backtest.engine import BUY, HOLD, NO_TRADE, SELL  # noqa: E402
from estrategia import tendencia_diaria as regra  # noqa: E402



# ------------------------------------------------------------ a regra pura

def test_votos_contam_os_prazos_em_alta():
    subindo = [100.0 + i for i in range(120)]
    caindo = [300.0 - i for i in range(120)]
    assert regra.votos(subindo) == 6
    assert regra.votos(caindo) == 0


def test_historico_curto_nao_vota():
    assert regra.votos([100.0] * (max(regra.LOOKBACKS) - 1)) is None
    assert regra.decidir(None, False) == NO_TRADE
    assert regra.decidir(None, True) == HOLD, "sem dado, quem esta dentro fica"


def test_histerese():
    # fora: entra com 4+
    assert regra.decidir(4, False) == BUY
    assert regra.decidir(3, False) == NO_TRADE
    # dentro: sai com 2-
    assert regra.decidir(3, True) == HOLD
    assert regra.decidir(2, True) == SELL
    # entre os dois, cada lado mantem o que faz: e isso que evita o rodizio
    assert regra.decidir(3, False) == NO_TRADE and regra.decidir(3, True) == HOLD


def test_entrada_segurada_ate_um_dia_fechar_depois_da_saida():
    assert regra.decidir(6, False, pode_entrar=False) == NO_TRADE
    assert regra.decidir(1, True, pode_entrar=False) == SELL, "a trava so segura entrada"
    saida = 1_000_000
    assert not regra.voto_vale_para_entrada(saida, saida)
    assert not regra.voto_vale_para_entrada(saida - 1, saida)
    assert regra.voto_vale_para_entrada(saida + 1, saida)
    assert regra.voto_vale_para_entrada(saida, None)


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
