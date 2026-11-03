"""Risk-matrix: series de precios por Core + tramos = la lectura ORM de antes.

Misma base de datos que el test de la ruta (SQLite real), mismas filas
(valores y nombres de columna), mismas listas por empresa y mismo orden de
claves que el setdefault + append sobre la capa ORM; y la respuesta de la ruta
no cambia (salvo ``provenance.fetched_at``).
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models import Company, MarketPrice, Tenant
from app.services import portfolio_risk_matrix_service as svc
from tests.auth_helpers import signed_request
from tests.test_portfolio_risk_matrix_route import SECRET, _seed


def _orm_reference(db, company_ids: list[int], cutoff: date) -> dict[int, list[Any]]:
    """La lectura anterior a este cambio, tal cual."""
    price_series: dict[int, list[Any]] = {company_id: [] for company_id in company_ids}
    for price in db.execute(
        select(
            MarketPrice.company_id,
            MarketPrice.date,
            MarketPrice.close,
            MarketPrice.adj_close,
            MarketPrice.source,
        )
        .where(MarketPrice.company_id.in_(company_ids), MarketPrice.date >= cutoff)
        .order_by(MarketPrice.company_id, MarketPrice.date)
    ).all():
        price_series.setdefault(price.company_id, []).append(price)
    return price_series


def _as_plain(series: dict[int, list[Any]]) -> list[tuple[int, list[dict[str, Any]]]]:
    return [(cid, [dict(row._mapping) for row in rows]) for cid, rows in series.items()]


def test_core_price_series_equal_orm_reading(monkeypatch) -> None:
    _client, tenant, _user = _seed(monkeypatch)
    db = SessionLocal()
    try:
        tenant_row = db.query(Tenant).filter(Tenant.external_id == tenant).one()
        db.info["tenant_id"] = tenant_row.id
        ids = list(db.scalars(select(Company.id).order_by(Company.id.desc())).all())
        missing = max(ids) + 1000  # empresa sin precios: lista vacia y en su sitio
        company_ids = [*ids, missing]
        today = date.today()
        for cutoff in (today - timedelta(days=400), today - timedelta(days=20), today + timedelta(days=1)):
            got = svc._load_price_series(db, company_ids, cutoff)
            want = _orm_reference(db, company_ids, cutoff)
            assert list(got) == list(want) == company_ids
            assert _as_plain(got) == _as_plain(want)
            assert all(row._fields == ("company_id", "date", "close", "adj_close", "source") for rows in got.values() for row in rows)
        assert any(got_rows for got_rows in svc._load_price_series(db, company_ids, today - timedelta(days=400)).values())
    finally:
        db.close()


def test_route_payload_unchanged_against_orm_reading(monkeypatch) -> None:
    client, tenant, user = _seed(monkeypatch)
    res_core = signed_request(client, SECRET, tenant, user, "GET", "/api/portfolio/risk-matrix")
    monkeypatch.setattr(svc, "_load_price_series", _orm_reference)
    res_orm = signed_request(client, SECRET, tenant, user, "GET", "/api/portfolio/risk-matrix")
    assert res_core.status_code == res_orm.status_code == 200
    core, orm = res_core.json(), res_orm.json()
    core["provenance"].pop("fetched_at", None)
    orm["provenance"].pop("fetched_at", None)
    assert core["status"] == "ok"
    assert core == orm
