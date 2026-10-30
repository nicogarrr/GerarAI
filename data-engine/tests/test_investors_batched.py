"""/api/investors y /investors/most-bought sin una consulta por gestor ni entidades ORM.

list_investors hacia 2 consultas por inversor revisado (gestor + todas las
filas del ultimo 13F como entidades, solo para contarlas y sumarlas). Ahora son
2 consultas en total y el resumen sale de columnas, con la misma regla de
accession vigente (la enmienda mas reciente sustituye al filing base).
"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

import app.services.investor_autosync as autosync
import app.services.investors as inv_mod
from app.models.entities import Base, FundManager, ManagerHolding

Q1, Q2 = date(2026, 3, 31), date(2026, 6, 30)


@pytest.fixture
def db(monkeypatch):
    monkeypatch.setattr(autosync, "maybe_autosync_holdings", lambda db: None)
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "tenant-a"
        yield session


def _holding(manager, acc, report, filed, cusip, value, shares="100"):
    return ManagerHolding(
        manager_id=manager.id, accession_number=acc, report_date=report, filing_date=filed,
        name_of_issuer=f"ISSUER {cusip}", title_of_class="COM", cusip=cusip, put_call=None,
        value_usd_thousands=None if value is None else Decimal(value), shares=Decimal(shares),
    )


def _seed(db):
    ciks = [inv.cik for inv in inv_mod.INVESTORS if inv.cik in inv_mod.REVIEWED_MANAGERS]
    a, b, c = (FundManager(cik=cik, name=cik, last_report_date=Q2, coverage="ok") for cik in ciks[:3])
    db.add_all([a, b, c])
    db.flush()
    db.add_all([
        _holding(a, "a-q1", Q1, date(2026, 5, 1), "000000001", "10"),
        _holding(a, "a-q2", Q2, date(2026, 8, 1), "000000001", "20"),
        _holding(a, "a-q2", Q2, date(2026, 8, 1), "000000002", "30"),
        # Enmienda posterior del mismo periodo: sustituye al filing base.
        _holding(a, "a-q2-amend", Q2, date(2026, 9, 1), "000000001", "25", "150"),
        _holding(a, "a-q2-amend", Q2, date(2026, 9, 1), "000000003", None),
        _holding(a, "a-q2-amend", Q2, date(2026, 9, 1), "000000004", "5"),
        # b: ultimo periodo sin filas -> sin datos.
        _holding(b, "b-q1", Q1, date(2026, 5, 1), "000000001", "7"),
        # c: solo valores sin cifra -> posiciones pero valor None.
        _holding(c, "c-q2", Q2, date(2026, 8, 2), "000000009", None),
        _holding(c, "c-q1", Q1, date(2026, 5, 2), "000000009", None),
    ])
    db.commit()
    # Otro tenant con el mismo CIK y mas filas: no debe colarse.
    db.info["tenant_id"] = "tenant-b"
    other = FundManager(cik=a.cik, name="other", last_report_date=Q2, coverage="ok")
    db.add(other)
    db.flush()
    db.add(_holding(other, "o-q2", Q2, date(2026, 8, 3), "000000001", "999"))
    db.commit()
    db.info["tenant_id"] = "tenant-a"
    db.expunge_all()


def _reference(db, inv):
    manager = inv_mod._manager(db, inv)
    rows = inv_mod._latest_view(db, manager) if manager else []
    return (len(rows) if rows else None), inv_mod._total(rows)


def test_list_investors_same_summary_in_constant_queries(db):
    _seed(db)
    count = [0]

    def _count(*_args):
        count[0] += 1

    event.listen(db.bind, "before_cursor_execute", _count)
    try:
        result = inv_mod.list_investors(db)
    finally:
        event.remove(db.bind, "before_cursor_execute", _count)

    assert count[0] <= 3  # antes: 2 por inversor revisado
    by_slug = {item["slug"]: item for item in result["investors"]}
    seen = 0
    for inv in inv_mod.INVESTORS:
        positions, value = _reference(db, inv)
        item = by_slug[inv.slug]
        assert (item["positions"], item["value_usd_thousands"]) == (positions, value), inv.slug
        seen += positions is not None
    assert seen == 2
    ciks = [inv.cik for inv in inv_mod.INVESTORS if inv.cik in inv_mod.REVIEWED_MANAGERS]
    first = next(i for i in result["investors"] if i["cik"] == ciks[0])
    assert first["positions"] == 3 and first["value_usd_thousands"] == 30.0
    assert first["coverage"] is not None


def test_most_bought_uses_batched_managers_and_keeps_tenant(db):
    _seed(db)
    result = inv_mod.most_bought(db)

    by_cusip = {item["cusip"]: item for item in result["items"]}
    # a: 000000001 sube de 100 a 150 acciones (enmienda), 3 y 4 son nuevas.
    assert set(by_cusip) == {"000000001", "000000003", "000000004"}
    assert by_cusip["000000001"]["buyers"][0]["change"] == "increased"
    assert by_cusip["000000001"]["value_usd"] == pytest.approx(25.0)
