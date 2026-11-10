"""Ingesta FRED (market_observations): las queries no crecen por punto.

Antes, ``store_series`` lanzaba hasta 2 queries POR PUNTO de la serie (el
chequeo de última observación y el de vintage): ~800 sentencias por serie y
refresco en estado estacionario (limit=800 del conector). Ahora la última
observación de cada día y los pares (día, vintage) salen de dos consultas por
serie. Este test fija el coste plano en estado estacionario y la paridad del
comportamiento: mismo valor no reescribe, valor nuevo añade revisión (append,
nunca sobrescribe) y una re-pasada es idempotente.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.models import MarketObservation
from app.models.entities import Base
from app.services.market_observation_service import store_series

BASE = date(2026, 1, 1)


def _rows(n_days: int, value: str = "20") -> list[dict]:
    return [
        {"date": (BASE - timedelta(days=i)).isoformat(), "value": value}
        for i in range(n_days)
    ]


def _session(n_days: int):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    for i in range(n_days):
        db.add(
            MarketObservation(
                metric_key="vix_us", geography="US",
                observation_date=BASE - timedelta(days=i), value=Decimal("20"),
                unit="índice", source="FRED",
                source_url="https://fred.stlouisfed.org/series/VIXCLS",
                fetched_at=datetime(2026, 1, 1, tzinfo=UTC), vintage="initial",
                status="observed",
            )
        )
    db.commit()
    return engine, db


def _count_steady(n_days: int) -> tuple[int, dict]:
    engine, db = _session(n_days)
    statements: list[str] = []
    event.listen(engine, "before_cursor_execute", lambda *a: statements.append(a[2]))
    result = store_series(db, "vix_us", _rows(n_days), datetime(2026, 2, 1, tzinfo=UTC))
    db.close()
    return len(statements), result


def test_ingesta_fred_estacionaria_no_escala_por_punto():
    pocas, r30 = _count_steady(30)
    muchas, r400 = _count_steady(400)
    assert muchas == pocas, (pocas, muchas)
    assert pocas <= 3
    assert r30 == r400 == {"added": 0, "revisions_applied": 0}


def test_ingesta_fred_revision_append_e_idempotencia():
    engine, db = _session(0)
    rows = _rows(50)
    first = store_series(db, "vix_us", rows, datetime(2026, 2, 1, tzinfo=UTC))
    assert first == {"added": 50, "revisions_applied": 0}
    # Re-pasada con los mismos valores: nada nuevo (vintage «initial» ya existe).
    again = store_series(db, "vix_us", rows, datetime(2026, 2, 1, 1, tzinfo=UTC))
    assert again == {"added": 0, "revisions_applied": 0}
    # FRED corrige dos días: se añaden como revisión, nunca se sobrescribe.
    rows[3]["value"] = "21"
    rows[7]["value"] = "22"
    revised = store_series(db, "vix_us", rows, datetime(2026, 2, 2, tzinfo=UTC))
    assert revised == {"added": 2, "revisions_applied": 2}
    assert db.query(MarketObservation).count() == 52
    # El histórico anterior sigue intacto.
    antiguas = db.query(MarketObservation).filter_by(vintage="initial").count()
    assert antiguas == 50
    db.close()


def test_ingesta_fred_no_hidrata_la_historia_de_vintages():
    # Probe del auditor: 8 días × 30 vintages, todos «observed». La última de
    # cada día sale con row_number en SQL (rn = 1): 8 instancias ORM, no 240.
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    for i in range(8):
        for v in range(30):
            db.add(
                MarketObservation(
                    metric_key="vix_us", geography="US",
                    observation_date=BASE - timedelta(days=i), value=Decimal("20"),
                    unit="índice", source="FRED",
                    source_url="https://fred.stlouisfed.org/series/VIXCLS",
                    fetched_at=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(minutes=v),
                    vintage=f"v{v}", status="observed",
                )
            )
    db.commit()
    db.expire_all()
    loaded = {"n": 0}

    def _on_load(*a):
        loaded["n"] += 1

    # Listener nombrado y retirado en finally: un listener sobre la clase
    # mapeada es global y sobrevive al engine si no se quita.
    event.listen(MarketObservation, "load", _on_load)
    try:
        result = store_series(db, "vix_us", _rows(8), datetime(2026, 2, 1, tzinfo=UTC))
        assert loaded["n"] <= 8, loaded
        assert result == {"added": 0, "revisions_applied": 0}
    finally:
        event.remove(MarketObservation, "load", _on_load)
        db.close()
        engine.dispose()
