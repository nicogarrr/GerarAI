"""Supervivientes de mutmut en ``TaxReportService._build_filing`` (ronda 2).

La capa de declaracion no se publica con divisa base distinta de EUR y el
arrastre de saldos negativos mira exactamente los 4 ejercicios anteriores,
recalculados sin capa filing. Solo se fija el comportamiento actual.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.services.tax_report_service import TaxReportService


@pytest.fixture()
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _empty(base="EUR"):
    return {"summary": {"base_currency": base}, "dividends": [], "realized": [], "misc": []}


@pytest.mark.parametrize("base", ["USD", "GBP", "eur"])
def test_sin_eur_como_base_no_hay_capa_de_declaracion(db, base):
    service = TaxReportService()
    service.compute_report = lambda *a, **k: pytest.fail("no debe recalcular ejercicios previos")
    filing = service._build_filing(db, 2025, _empty(base))
    assert filing["available"] is False
    assert filing["reason"].startswith("La cartera no usa EUR como divisa base")
    assert "Modelo 100" in filing["reason"]
    assert set(filing) == {"available", "reason"}


def test_arrastre_mira_los_cuatro_ejercicios_anteriores_sin_filing(db):
    service = TaxReportService()
    calls = []

    def fake_compute(_db, year, include_filing=True, **_kw):
        calls.append((year, include_filing))
        return {
            "summary": {"total_dividends_base": 10.0, "total_realized_gain_base": -100.0,
                        "incomplete_fx": False},
            "misc": [],
        }

    service.compute_report = fake_compute
    for summary in ({"base_currency": "EUR"}, {}):
        calls.clear()
        filing = service._build_filing(db, 2025, {**_empty(), "summary": summary})
        assert calls == [(2021, False), (2022, False), (2023, False), (2024, False)]
        carry = next(v for v in filing.values() if isinstance(v, dict) and "window_years" in v)
        assert carry["window_years"] == 4
        assert [row["year"] for row in carry["prior_losses"]] == [2021, 2022, 2023, 2024]
        # Cada ejercicio: -100 de patrimoniales, de los que el 25 % de sus 10 de
        # rendimientos ya absorbio 2,5 en su propio ejercicio.
        assert [row["pending_start_base"] for row in carry["prior_losses"]] == [97.5] * 4
        assert carry["remaining_to_carry_base"] == 390.0
