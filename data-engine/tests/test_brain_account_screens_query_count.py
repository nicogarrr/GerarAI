"""Pantallas guardadas del cerebro de cuenta: las queries no crecen por pantalla.

Antes, ``_saved_screens_answer`` lanzaba una query de coincidencias POR CADA
pantalla guardada (hasta 15 en la respuesta): 5 sentencias con 3 pantallas,
17 con 15. Ahora las coincidencias de todas las pantallas mostradas salen de
una sola query con IN agrupada en memoria. Este test fija el coste plano y
que la respuesta conserva el orden de coincidencias por id (el del bucle
anterior) y el tope de 15 pantallas.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.models import Company, Tenant
from app.models.entities import Base, SavedScreen, SavedScreenMatch
from app.services import brain_account_tools as bat


def _session(n_screens: int, n_matches: int = 6):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    tenant = Tenant(external_id=f"ba-{uuid.uuid4().hex[:8]}", name="T", status="active")
    db.add(tenant)
    db.flush()
    db.info["tenant_id"] = tenant.id
    for s in range(n_screens):
        screen = SavedScreen(tenant_id=tenant.id, name=f"Screen {s}", criteria=[{"k": "v"}])
        db.add(screen)
        db.flush()
        for m in range(n_matches):
            ticker = f"S{s}M{m}{uuid.uuid4().hex[:3].upper()}"
            company = Company(
                ticker=ticker, name=ticker, exchange="NASDAQ", currency="USD",
                sector="T", industry="T", company_type="standard",
                valuation_model="standard_dcf",
            )
            db.add(company)
            db.flush()
            db.add(
                SavedScreenMatch(
                    tenant_id=tenant.id, saved_screen_id=screen.id, company_id=company.id,
                    first_matched_at=datetime(2026, 1, 1, tzinfo=UTC),
                    last_matched_at=datetime(2026, 1, 1, tzinfo=UTC),
                )
            )
    db.commit()
    return engine, db, tenant


def _count_and_run(n_screens: int) -> tuple[int, str]:
    engine, db, tenant = _session(n_screens)
    statements: list[str] = []
    event.listen(engine, "before_cursor_execute", lambda *a: statements.append(a[2]))
    response = bat._saved_screens_answer(db, tenant.id)
    db.close()
    return len(statements), response.answer


def test_pantallas_guardadas_no_escalan_por_pantalla():
    pocas, _ = _count_and_run(3)
    muchas, _ = _count_and_run(15)
    assert muchas == pocas, (pocas, muchas)
    assert pocas <= 4


def test_pantallas_guardadas_conservan_orden_y_tope():
    _, answer = _count_and_run(16)
    # Tope de 15 pantallas en la respuesta.
    assert "Screen 14" in answer and "Screen 15" not in answer
    # Tickers en orden de coincidencia (id ascendente) dentro de la pantalla.
    i0 = answer.index("S0M0")
    i1 = answer.index("S0M1")
    assert i0 < i1
