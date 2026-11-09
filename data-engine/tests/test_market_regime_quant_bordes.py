"""Bordes de las guardas de filtered_hmm (app/services/market_regime_quant.py).

Cubre las salidas "sin datos" que la suite existente no ejercita:
- historial insuficiente (limite exacto min_training+1), puntos desordenados
  y fechas duplicadas (guarda triple de la entrada);
- valores no finitos (NaN/inf);
- serie constante (std <= 0);
- ajuste no convergente y probabilidades no finitas (modelo sustituido por
  dobles quirurgicos via monkeypatch, sin tocar el camino feliz real);
- excepcion del modelo (ValueError/FloatingPointError/ImportError).

portfolio_beta queda fuera por decision del coordinador (lee posiciones de
cartera): se documenta y no se cubre.
"""

from datetime import date, timedelta
from types import SimpleNamespace

import numpy as np
import pytest

from app.services.market_regime_quant import filtered_hmm


def _puntos(n: int = 130) -> list[tuple[date, float, float]]:
    start = date(2026, 1, 1)
    return [
        (start + timedelta(days=i), 15 + (i % 9) / 3 + (i % 4) / 5, 3 + (i % 7) / 9 + (i % 5) / 4)
        for i in range(n)
    ]


@pytest.mark.filterwarnings(
    "ignore:Setting the shape on a NumPy array has been deprecated:DeprecationWarning:hmmlearn.utils"
)
def test_historial_insuficiente_en_el_limite():
    assert filtered_hmm(_puntos(126)) == {"status": "sin datos", "reason": "historial insuficiente"}
    assert filtered_hmm(_puntos(127))["status"] == "disponible"


def test_puntos_desordenados_o_duplicados_rechazados():
    puntos = _puntos()
    desordenados = puntos[::-1]
    assert filtered_hmm(desordenados)["reason"] == "historial insuficiente"
    duplicados = puntos[:-1] + [puntos[-2]]
    assert filtered_hmm(duplicados)["reason"] == "historial insuficiente"


@pytest.mark.parametrize("malo", [float("nan"), float("inf")])
def test_valores_no_finitos(malo):
    puntos = _puntos()
    puntos[-1] = (puntos[-1][0], malo, puntos[-1][2])
    assert filtered_hmm(puntos) == {"status": "sin datos", "reason": "valores inválidos"}


def test_serie_constante():
    start = date(2026, 1, 1)
    puntos = [(start + timedelta(days=i), 20.0, 4.0) for i in range(130)]
    assert filtered_hmm(puntos) == {"status": "sin datos", "reason": "serie constante"}


def test_ajuste_no_convergente(monkeypatch):
    class NoConverge:
        def __init__(self, **kwargs):
            self.monitor_ = SimpleNamespace(converged=False)

        def fit(self, data):
            return self

        def score_samples(self, data):  # pragma: no cover - no debe llamarse
            raise AssertionError("score_samples no debe llamarse sin convergencia")

    monkeypatch.setattr("hmmlearn.hmm.GaussianHMM", NoConverge)
    assert filtered_hmm(_puntos()) == {"status": "sin datos", "reason": "ajuste no convergente"}


def test_probabilidades_no_finitas(monkeypatch):
    class ProbRota:
        def __init__(self, **kwargs):
            self.monitor_ = SimpleNamespace(converged=True)

        def fit(self, data):
            return self

        def score_samples(self, data):
            return 0.0, np.full((len(data), 2), np.nan)

    monkeypatch.setattr("hmmlearn.hmm.GaussianHMM", ProbRota)
    assert filtered_hmm(_puntos()) == {"status": "sin datos", "reason": "probabilidad inválida"}


def test_excepcion_del_modelo(monkeypatch):
    class ModeloRoto:
        def __init__(self, **kwargs):
            raise ValueError("fallo de inicialización")

    monkeypatch.setattr("hmmlearn.hmm.GaussianHMM", ModeloRoto)
    assert filtered_hmm(_puntos()) == {"status": "sin datos", "reason": "modelo no disponible"}
