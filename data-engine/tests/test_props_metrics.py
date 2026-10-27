"""Tests de propiedades (invariantes) de métricas y ratios.

Casos aleatorios con semilla fija (``random.Random``), 200 por propiedad:
deterministas y sin dependencias nuevas.
"""

from __future__ import annotations

import random
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.api.routes.portfolio import _scenario_returns
from app.api.routes.thesis import _pct_change
from app.models import FinancialFact
from app.services.driver_operating_model import DriverOperatingModel
from app.services.long_term_model_service import LongTermModelService
from app.services.metric_semantics import MetricSemanticsRegistry
from app.services.number_format import format_number_es
from app.services.number_parsing import parse_localized_number
from app.services.peer_comparison_service import PeerComparisonService
from app.services.screener_service import ScreenerService
from app.services.split_adjustment import cumulative_split_factor_after
from app.services.thesis_projection_service import ThesisProjectionService

N_CASOS = 200


def _casos(semilla: int, n: int = N_CASOS) -> list[random.Random]:
    base = random.Random(semilla)
    return [random.Random(base.random()) for _ in range(n)]


def _fact(value: float, year: int, fact_id: int) -> FinancialFact:
    return FinancialFact(
        id=fact_id,
        company_id=1,
        metric="revenue",
        value=Decimal(repr(value)),
        period=f"FY{year}",
        fiscal_year=year,
        fiscal_quarter="FY",
        confidence=Decimal("0.9"),
    )


@pytest.mark.parametrize("rng", _casos(201), ids=lambda _: "")
def test_cagr_ida_y_vuelta_en_todas_las_implementaciones(rng):
    """CAGR (CFA L1 Quantitative Methods): inicio·(1 + CAGR)^años = fin.
    Las cinco implementaciones dan el mismo número."""
    inicio = rng.uniform(1, 10_000)
    fin = rng.uniform(1, 10_000)
    year0 = rng.randint(2000, 2015)
    years = rng.randint(1, 10)
    year1 = year0 + years
    valores = [
        float(ScreenerService._cagr([_fact(fin, year1, 2), _fact(inicio, year0, 1)]).value),  # type: ignore[union-attr]
        ThesisProjectionService._revenue_cagr({year0: _fact(inicio, year0, 1), year1: _fact(fin, year1, 2)}).value,
        DriverOperatingModel._cagr([(year0, inicio, 1, "USD"), (year1, fin, 2, "USD")]),
        LongTermModelService._cagr([{"year": year0, "value": inicio}, {"year": year1, "value": fin}]),
        _scenario_returns(fin, inicio, years)[0],  # type: ignore[index]
    ]
    for cagr in valores:
        assert cagr is not None
        assert inicio * (1 + cagr) ** years == pytest.approx(fin, rel=1e-9)


@pytest.mark.parametrize("rng", _casos(202), ids=lambda _: "")
def test_cagr_no_definido_con_base_no_positiva(rng):
    """Con base ≤ 0 el CAGR no es un número real: todas devuelven N/D."""
    inicio = -rng.uniform(0, 1_000)
    fin = rng.uniform(1, 1_000)
    assert ScreenerService._cagr([_fact(fin, 2025, 2), _fact(inicio, 2020, 1)]) is None
    assert ThesisProjectionService._revenue_cagr({2020: _fact(inicio, 2020, 1), 2025: _fact(fin, 2025, 2)}).value is None
    assert DriverOperatingModel._cagr([(2020, inicio, 1, "USD"), (2025, fin, 2, "USD")]) is None
    assert LongTermModelService._cagr([{"year": 2020, "value": inicio}, {"year": 2025, "value": fin}]) is None
    assert _scenario_returns(fin, inicio, 5) is None


@pytest.mark.parametrize("rng", _casos(203), ids=lambda _: "")
def test_variacion_porcentual_tiene_el_signo_de_la_mejora(rng):
    """(nuevo − base)/|base|: positiva si y solo si nuevo > base, también con
    base negativa (Damodaran, crecimiento con beneficios negativos), e
    invariante al reescalar las dos cifras por k > 0."""
    base = rng.choice([-1, 1]) * rng.uniform(0.01, 1_000)
    nuevo = rng.uniform(-1_000, 1_000)
    pct = _pct_change(base, nuevo)
    assert pct is not None
    assert (pct > 0) == (nuevo > base)
    k = rng.uniform(0.01, 100)
    assert _pct_change(base * k, nuevo * k) == pytest.approx(pct)
    _, var = MetricSemanticsRegistry.classify("x", Decimal(repr(base)), Decimal(repr(nuevo)))
    assert float(var) * 100 == pytest.approx(pct)  # type: ignore[arg-type]


@pytest.mark.parametrize("rng", _casos(204), ids=lambda _: "")
def test_factor_de_split_multiplicativo_e_independiente_del_orden(rng):
    """F = Π ratios posteriores al cierre (NIC 33 §64): no depende del orden,
    ignora los splits anteriores y EPS/F·F = EPS."""
    ref = date(2015, 1, 1) + timedelta(days=rng.randint(0, 3_000))
    eventos = [
        (date(2005, 1, 1) + timedelta(days=rng.randint(0, 9_000)), Decimal(rng.choice(["2", "3", "4", "7", "10", "0.1", "0.5"])))
        for _ in range(rng.randint(0, 5))
    ]
    esperado = Decimal(1)
    for dia, ratio in eventos:
        if dia > ref:
            esperado *= ratio
    barajados = eventos[:]
    rng.shuffle(barajados)
    assert cumulative_split_factor_after(eventos, ref) == esperado
    assert cumulative_split_factor_after(barajados, ref) == esperado
    eps = Decimal(repr(round(rng.uniform(0.01, 50), 2)))
    assert (eps / esperado) * esperado == pytest.approx(eps)


@pytest.mark.parametrize("rng", _casos(205), ids=lambda _: "")
def test_formatear_y_parsear_es_ida_y_vuelta(rng):
    """Formato es-ES (miles con punto, decimales con coma; CLDR) y parseo
    son inversos: parsear lo formateado devuelve la cifra a 2 decimales."""
    valor = Decimal(repr(round(rng.uniform(-10_000_000, 10_000_000), 2)))
    texto = format_number_es(valor, 2)
    assert texto is not None
    parsed = parse_localized_number(texto)
    assert parsed is not None
    assert parsed[0] == valor


@pytest.mark.parametrize("rng", _casos(206), ids=lambda _: "")
def test_mediana_de_pares_invariantes(rng):
    """Mediana (Damodaran, múltiplos de pares): no depende del orden, queda
    entre el mínimo y el máximo y se desplaza con la serie."""
    service = PeerComparisonService.__new__(PeerComparisonService)
    valores = [Decimal(repr(round(rng.uniform(-50, 200), 3))) for _ in range(rng.randint(1, 15))]
    mediana = service._median(valores)
    assert mediana is not None
    barajados = valores[:]
    rng.shuffle(barajados)
    assert service._median(barajados) == mediana
    assert min(valores) <= mediana <= max(valores)
    c = Decimal(repr(round(rng.uniform(-100, 100), 3)))
    assert service._median([v + c for v in valores]) == mediana + c
