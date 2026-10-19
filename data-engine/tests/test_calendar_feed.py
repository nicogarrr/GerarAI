from datetime import UTC, date, datetime

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.api.routes import calendar as calendar_routes
from app.core.database import SessionLocal, init_db
from app.models import Company, EarningsDate, Position, Tenant, WatchItem
from app.services import calendar_feed_service as svc

TODAY = date(2026, 10, 19)


def _company(db, ticker, name):
    c = db.scalar(select(Company).where(Company.ticker == ticker))
    if c is None:
        c = Company(ticker=ticker, name=name, exchange="NYSE", currency="USD",
                    company_type="research_candidate", valuation_model="unassigned")
        db.add(c)
        db.flush()
    return c


def _setup(db):
    from uuid import uuid4

    from sqlalchemy import delete

    db.execute(delete(EarningsDate).where(EarningsDate.ticker.in_(["FHELD", "FWATCH", "FOTHER"])))
    uid = uuid4().hex[:8]
    ta, tb = Tenant(external_id=f"feed-ta-{uid}", name="A"), Tenant(external_id=f"feed-tb-{uid}", name="B")
    db.add_all([ta, tb])
    db.flush()
    held, watched, other = _company(db, "FHELD", "Held, Inc;"), _company(db, "FWATCH", "Watch Co"), _company(db, "FOTHER", "Other")
    db.add_all([
        WatchItem(symbol="FWATCH", company="Watch Co", tenant_id=ta.id),
        WatchItem(symbol="FOTHER", company="Other", tenant_id=tb.id),
        Position(company_id=held.id, quantity=10, tenant_id=ta.id),
    ])
    now = datetime.now(UTC)
    for t, d in (("FHELD", 21), ("FWATCH", 22), ("FOTHER", 23)):
        db.add(EarningsDate(ticker=t, event_date=date(2026, 10, d), source="nasdaq+yahoo", source_label="NASDAQ + Yahoo",
                            session="after_market" if t == "FHELD" else None, fiscal_label="Sep/2026",
                            confirmed=t != "FWATCH", fetched_at=now))
    db.commit()
    return ta, tb


def test_token_lifecycle_hash_only_and_rotation():
    init_db()
    db = SessionLocal()
    try:
        ta, _ = _setup(db)
        db.info["tenant_id"] = ta.id
        t1, row1 = svc.create_token(db, "followed")
        assert t1.startswith("gfc_") and row1.token_hash == svc.hash_token(t1) and t1 not in row1.token_hash
        t2, row2 = svc.create_token(db, "watchlist")
        db.refresh(row1)
        assert row1.revoked_at is not None and row2.revoked_at is None
        assert svc.active_token(db).id == row2.id
        assert svc.revoke_tokens(db) == 1
        assert svc.active_token(db) is None
        with pytest.raises(ValueError):
            svc.create_token(db, "todo")
    finally:
        db.rollback()
        db.close()


def test_public_feed_is_tenant_scoped_scope_filtered_and_has_no_portfolio_data():
    init_db()
    db = SessionLocal()
    try:
        ta, _ = _setup(db)
        db.info["tenant_id"] = ta.id
        token, _ = svc.create_token(db, "followed")
        wtoken, _ = svc.create_token(db, "watchlist")
        # token del feed "followed" fue revocado al regenerar -> 404
        anon = SessionLocal()
        assert svc.feed_for_token(anon, token, today=TODAY) is None
        anon.close()
        anon = SessionLocal()
        ics = svc.feed_for_token(anon, wtoken, today=TODAY)
        anon.close()
        assert "FWATCH" in ics and "FHELD" not in ics and "FOTHER" not in ics
        assert "fecha estimada" in ics and "Franja" not in ics.split("FWATCH")[0]
        db.info["tenant_id"] = ta.id
        full, _ = svc.create_token(db, "followed")
        anon = SessionLocal()
        ics = svc.feed_for_token(anon, full, today=TODAY)
        anon.close()
        assert "FHELD" in ics and "FWATCH" in ics and "FOTHER" not in ics
        assert "Held\\, Inc\\;" in ics  # escapado RFC 5545
        # El nombre del calendario (X-WR-CALNAME) menciona cartera/watchlist como
        # etiqueta; el resto del ICS no puede llevar nada de la cartera.
        body = "\n".join(line for line in ics.splitlines() if not line.startswith("X-WR-CALNAME:"))
        for banned in ("quantity", "cartera", "watchlist", "cost", "price"):
            assert banned not in body.lower()
        assert "DTSTART;VALUE=DATE:20261021" in ics and "T" not in ics.split("DTSTART;VALUE=DATE:")[1][:9]
        assert ics.endswith("END:VCALENDAR\r\n") and "\r\n" in ics
        assert all(len(line.encode()) <= 75 for line in ics.split("\r\n"))
    finally:
        db.rollback()
        db.close()


def test_public_route_rejects_malformed_and_unknown_tokens():
    for name in ("x.ics", "gfc_abc", "gfc_" + "a" * 100 + ".ics", "gfc_unknowntoken.ics"):
        with pytest.raises(HTTPException) as exc:
            calendar_routes.calendar_feed_public(name)
        assert exc.value.status_code == 404
    assert calendar_routes.calendar_feed_status.__name__  # rutas autenticadas existen


def test_fold_keeps_utf8_intact():
    line = "DESCRIPTION:" + "áéíóú" * 30
    parts = svc._fold(line)
    assert all(len(p.encode()) <= 75 for p in parts)
    assert "".join(p[1:] if i else p for i, p in enumerate(parts)) == line


def test_public_feed_http_without_identity_and_authenticated_routes_stay_401(monkeypatch):
    """Regresion #1774: el GET publico colgaba de private_dependencies y daba 401.
    Con la app real: token valido sin identidad = 200 (+cabeceras), token
    invalido = 404, y GET/POST/DELETE /api/calendar/feed siguen exigiendo firma."""
    from fastapi.testclient import TestClient

    import main

    init_db()
    db = SessionLocal()
    try:
        ta, _ = _setup(db)
        db.info["tenant_id"] = ta.id
        token, _row = svc.create_token(db, "followed")
    finally:
        db.close()
    from app.core.config import get_settings

    # Auth exigida como en produccion (conftest la desactiva por defecto).
    monkeypatch.setattr(get_settings(), "research_auth_required", True)
    client = TestClient(main.app)
    ok = client.get(f"/api/calendar/feed/{token}.ics")
    assert ok.status_code == 200
    assert ok.headers["content-type"].startswith("text/calendar")
    assert ok.headers["x-robots-tag"] == "noindex"
    assert ok.headers["referrer-policy"] == "no-referrer"
    assert ok.headers["cache-control"] == "private, max-age=300"
    assert "BEGIN:VCALENDAR" in ok.text and "FOTHER" not in ok.text
    for bad in ("gfc_unknowntoken.ics", "gfc_" + "a" * 100 + ".ics", "x.ics", f"{token}"):
        r = client.get(f"/api/calendar/feed/{bad}")
        assert r.status_code == 404, bad
    assert client.get("/api/calendar/feed").status_code == 401
    assert client.post("/api/calendar/feed", json={}).status_code == 401
    assert client.delete("/api/calendar/feed").status_code == 401


def test_public_feed_ip_rate_limit_returns_429_after_limit(monkeypatch):
    import asyncio
    from types import SimpleNamespace

    from app.core import rate_limit as rl

    monkeypatch.setattr(rl, "PUBLIC_FEED_LIMIT_PER_MINUTE", 3)
    req = SimpleNamespace(client=SimpleNamespace(host="203.0.113.77"), headers={})
    for _ in range(3):
        asyncio.run(rl.enforce_public_ip_rate_limit(req))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(rl.enforce_public_ip_rate_limit(req))
    assert exc.value.status_code == 429


def test_public_client_ip_uses_last_xff_only_behind_private_proxy():
    from types import SimpleNamespace

    from app.core.rate_limit import public_client_ip

    def req(peer, xff=None):
        return SimpleNamespace(client=SimpleNamespace(host=peer), headers={"x-forwarded-for": xff} if xff else {})

    # Tras Caddy (peer privado): ultima entrada, las anteriores son falsificables.
    assert public_client_ip(req("172.18.0.2", "1.1.1.1, 76.76.21.9")) == "76.76.21.9"
    assert public_client_ip(req("172.18.0.2")) == "172.18.0.2"
    assert public_client_ip(req("172.18.0.2", "basura")) == "172.18.0.2"
    # Acceso directo (peer publico): la cabecera se ignora.
    assert public_client_ip(req("8.8.4.4", "9.9.9.9")) == "8.8.4.4"


def test_ics_calname_follows_scope():
    cal = {"days": []}
    assert "X-WR-CALNAME:Resultados de tu watchlist" in svc.build_ics(cal, scope="watchlist")
    assert "X-WR-CALNAME:Resultados de cartera y watchlist" in svc.build_ics(cal, scope="followed")
    assert "X-WR-CALNAME:Resultados de cartera y watchlist" in svc.build_ics(cal)
