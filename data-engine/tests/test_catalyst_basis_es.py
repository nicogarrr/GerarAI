"""El detalle del plazo de presentación (catalizador) va en es-ES: fechas
«30 sept 2026» y categoría de filer traducida (auditoría F1). Sin red:
filing_deadline_event es función pura sobre el payload de submissions."""

from __future__ import annotations

from app.services.catalyst_calendar_service import filing_deadline_event


def _subs(category: str) -> dict:
    rows = [
        ("10-Q", "2026-06-27"), ("10-Q", "2026-03-28"), ("10-Q", "2025-12-27"),
        ("10-K", "2025-09-27"), ("10-Q", "2025-06-28"),
    ]
    return {
        "fiscalYearEnd": "0926",
        "category": category,
        "filings": {"recent": {"form": [f for f, _ in rows], "reportDate": [r for _, r in rows]}},
    }


def test_fechas_y_categoria_del_basis_en_es():
    event = filing_deadline_event(_subs("Large accelerated filer"), "X")
    assert event is not None
    detail = event["detail"]
    assert "2026-" not in detail and "2025-" not in detail, detail
    assert "sept 2026" in detail
    assert "emisor acelerado grande" in detail
    assert "Large accelerated" not in detail


def test_categoria_acelerada_traducida():
    event = filing_deadline_event(_subs("Accelerated filer"), "X")
    assert event is not None
    assert "categoría EDGAR: emisor acelerado" in event["detail"]
