"""PDF de cartera: la «Fecha» es la del informe (hoy en Madrid), no la de alta de la cartera.

El informe enseña posiciones y valores de hoy pero salía fechado con el día en
que se creó la cartera (meses atrás), y en día UTC.
"""

from datetime import UTC, datetime

from app.core.local_date import local_today
from app.models import Portfolio, ThesisVersion
from tests.test_thesis_pdf_export import _page_text, env  # noqa: F401 - fixture


def test_portfolio_pdf_is_dated_today_not_portfolio_creation(env):  # noqa: F811
    client, factory, port_id = env
    with factory() as db:
        portfolio = db.get(Portfolio, port_id)
        portfolio.created_at = datetime(2025, 1, 15, 10, tzinfo=UTC)
        db.commit()
    res = client.get(f"/api/portfolio/{port_id}/pdf")
    assert res.status_code == 200
    page1, _page2 = _page_text(res.content)
    flat = " ".join(page1.split())
    assert f"Fecha: {local_today().isoformat()}" in flat
    assert "2025-01-15" not in flat


def test_thesis_pdf_date_is_madrid_day_of_last_update(env):  # noqa: F811
    """Tesis actualizada a las 23:30 UTC del 1 de marzo: en Madrid ya es el 2."""
    client, factory, _port_id = env
    with factory() as db:
        for thesis in db.query(ThesisVersion).all():
            thesis.updated_at = datetime(2026, 3, 1, 23, 30, tzinfo=UTC)
        db.commit()
    res = client.get("/api/thesis/SAN.MC/pdf")
    assert res.status_code == 200
    page1, _page2 = _page_text(res.content)
    flat = " ".join(page1.split())
    assert "Fecha: 2026-03-02" in flat and "2026-03-01" not in flat
