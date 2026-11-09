"""Bordes de refresh_shorts y emit_shorts_increase no cubiertos por las suites existentes.

Cubre: guarda de tenant y advisory lock de PostgreSQL en refresh_shorts, la ruta FINRA
(exito, sin fila, fecha futura), la salida temprana de emit_shorts_increase sin cartera ni
watchlist, y las guardas conservadoras de fechas/titulares CNMV y settlement FINRA.
Las fechas se derivan del reloj de prueba; nada depende de un dia fijo del calendario.
"""

import asyncio
import hashlib
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models import Position
from app.models.entities import Base, Company, ConnectorState, Tenant
from app.services.short_positions_service import emit_shorts_increase, read_shorts, refresh_shorts


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(Tenant(id=1, external_id="owner"))
        db.commit()
        db.info.update(tenant_id=1, user_id="owner")
        yield db
    engine.dispose()


def _company(db, ticker="ACME", exchange="NASDAQ"):
    company = Company(
        ticker=ticker, name=ticker, exchange=exchange, company_type="compounders", valuation_model="dcf"
    )
    db.add(company)
    db.commit()
    return company


def _cnmv_payload(day, percent=1.5, holder="Fund"):
    return {
        "source": "CNMV",
        "positions": [{"holder": holder, "percent": percent, "position_date": day.isoformat()}],
        "public_total_percent": percent,
        "source_url": "https://cnmv.example/pos",
    }


def test_refresh_sin_tenant_lanza(db):
    db.info.pop("tenant_id")
    company = _company(db)
    with pytest.raises(ValueError, match="Tenant context required"):
        asyncio.run(refresh_shorts(db, company))


def test_refresh_postgresql_advisory_lock(monkeypatch):
    db = MagicMock()
    db.info = {"tenant_id": 1}
    db.get_bind.return_value.dialect.name = "postgresql"
    db.scalar.return_value = None
    company = SimpleNamespace(id=7, ticker="GRF", exchange="BME")

    async def positions(issuer, **kwargs):
        return {"source": "CNMV", "positions": [], "public_total_percent": 1.0}

    monkeypatch.setattr("app.services.short_positions_service.resolve_issuer", lambda ticker: {"nif": "A1"})
    monkeypatch.setattr("app.services.short_positions_service.fetch_positions", positions)
    monkeypatch.setattr("app.services.short_positions_service.emit_shorts_increase", lambda *a, **k: None)
    asyncio.run(refresh_shorts(db, company))
    clause, params = db.execute.call_args.args
    assert "pg_advisory_xact_lock" in str(clause)
    expected = int.from_bytes(hashlib.sha256(b"public-shorts:1:7").digest()[:8], "big", signed=True)
    assert params == {"key": expected}


def _finra(monkeypatch, row, interest=None):
    async def volume(ticker, **kwargs):
        return row

    async def short_interest(ticker, **kwargs):
        return interest

    monkeypatch.setattr("app.services.short_positions_service.fetch_short_volume", volume)
    monkeypatch.setattr("app.services.short_positions_service.fetch_short_interest", short_interest)


def test_refresh_finra_exito(db, monkeypatch):
    company = _company(db)
    hoy = datetime.now(UTC).date()
    _finra(monkeypatch, {"date": hoy.isoformat(), "short_volume": 10, "total_volume": 100})
    result = asyncio.run(refresh_shorts(db, company))
    assert result["status"] == "available"
    assert result["data"]["source"] == "FINRA" and result["data"]["kind"] == "OFICIAL"
    assert result["data"]["short_interest"] is None
    state = db.query(ConnectorState).filter_by(connector="public_shorts", company_id=company.id).one()
    assert state.consecutive_errors == 0 and state.last_error is None
    assert state.last_success_at is not None and state.metadata_["source"] == "FINRA"


def test_refresh_finra_sin_fila_marca_error(db, monkeypatch):
    company = _company(db)
    _finra(monkeypatch, None)
    result = asyncio.run(refresh_shorts(db, company))
    assert result["status"] == "degraded"
    state = db.query(ConnectorState).filter_by(connector="public_shorts", company_id=company.id).one()
    assert state.consecutive_errors == 1 and state.last_error == "ValueError"


def test_refresh_finra_fecha_futura_marca_error(db, monkeypatch):
    company = _company(db)
    manana = (datetime.now(UTC).date() + timedelta(days=1)).isoformat()
    _finra(monkeypatch, {"date": manana, "short_volume": 10, "total_volume": 100})
    result = asyncio.run(refresh_shorts(db, company))
    assert result["status"] == "degraded"
    state = db.query(ConnectorState).filter_by(connector="public_shorts", company_id=company.id).one()
    assert state.consecutive_errors == 1 and state.last_error == "ValueError"


def test_emit_sin_cartera_ni_watchlist_no_alerta(db, monkeypatch):
    emit = MagicMock()
    monkeypatch.setattr("app.services.review_alert_service.ReviewAlertService.emit_alert", emit)
    company = _company(db)
    now = datetime.now(UTC)
    emit_shorts_increase(
        db,
        company,
        _cnmv_payload(now.date() - timedelta(days=20), 1.0),
        _cnmv_payload(now.date() - timedelta(days=5), 2.0),
        now,
    )
    emit.assert_not_called()


def _alertas(monkeypatch):
    emit = MagicMock()
    monkeypatch.setattr("app.services.review_alert_service.ReviewAlertService.emit_alert", emit)
    return emit


def _cnmv_dates(days):
    base = datetime.now(UTC).date()
    antes = base - timedelta(days=days[0])
    despues = base - timedelta(days=days[1])
    return (_cnmv_payload(antes, 1.0), _cnmv_payload(despues, 2.0))


def test_emit_cnmv_fecha_titular_invalida_no_alerta(db, monkeypatch):
    emit = _alertas(monkeypatch)
    company = _company(db)
    db.add(Position(company_id=company.id, quantity=1))
    db.commit()
    now = datetime.now(UTC)
    previo = _cnmv_payload(now.date() - timedelta(days=20), 1.0)
    actual = _cnmv_payload(now.date() - timedelta(days=5), 2.0)
    actual["positions"][0]["position_date"] = "no-es-fecha"
    emit_shorts_increase(db, company, previo, actual, now)
    emit.assert_not_called()


def test_emit_cnmv_fecha_futura_no_alerta(db, monkeypatch):
    emit = _alertas(monkeypatch)
    company = _company(db)
    db.add(Position(company_id=company.id, quantity=1))
    db.commit()
    now = datetime.now(UTC)
    previo = _cnmv_payload(now.date() - timedelta(days=5), 1.0)
    actual = _cnmv_payload(now.date() + timedelta(days=1), 2.0)
    emit_shorts_increase(db, company, previo, actual, now)
    emit.assert_not_called()


def test_emit_cnmv_percent_cambiado_sin_avance_no_alerta(db, monkeypatch):
    emit = _alertas(monkeypatch)
    company = _company(db)
    db.add(Position(company_id=company.id, quantity=1))
    db.commit()
    now = datetime.now(UTC)
    dia = now.date() - timedelta(days=5)
    previo = _cnmv_payload(dia, 1.0)
    actual = _cnmv_payload(dia, 2.0)
    emit_shorts_increase(db, company, previo, actual, now)
    emit.assert_not_called()


def test_emit_cnmv_totales_sin_subida_no_alerta(db, monkeypatch):
    emit = _alertas(monkeypatch)
    company = _company(db)
    db.add(Position(company_id=company.id, quantity=1))
    db.commit()
    now = datetime.now(UTC)
    previo, actual = _cnmv_dates((20, 5))
    actual["public_total_percent"] = previo["public_total_percent"]
    emit_shorts_increase(db, company, previo, actual, now)
    emit.assert_not_called()


def test_emit_finra_settlement_invalido_no_alerta(db, monkeypatch):
    emit = _alertas(monkeypatch)
    company = _company(db)
    db.add(Position(company_id=company.id, quantity=1))
    db.commit()
    now = datetime.now(UTC)
    actual = {
        "source": "FINRA",
        "short_interest": {"settlement_date": "basura", "previous_short_interest": 10, "short_interest": 20},
    }
    emit_shorts_increase(db, company, {}, actual, now)
    emit.assert_not_called()


def test_emit_finra_aumento_emite_alerta(db, monkeypatch):
    emit = _alertas(monkeypatch)
    company = _company(db)
    db.add(Position(company_id=company.id, quantity=1))
    db.commit()
    now = datetime.now(UTC)
    stamp = (now.date() - timedelta(days=3)).isoformat()
    actual = {
        "source": "FINRA",
        "short_interest": {
            "settlement_date": stamp,
            "previous_short_interest": 1000,
            "short_interest": 2000,
            "source_url": "https://finra.example/short",
        },
    }
    emit_shorts_increase(db, company, {}, actual, now)
    emit.assert_called_once()
    kwargs = emit.call_args.kwargs
    assert kwargs["alert_type"] == "shorts_rising" and kwargs["company_id"] == company.id
    assert "1.000" in kwargs["message"] and "2.000" in kwargs["message"]
    assert stamp in kwargs["message"]
    assert kwargs["fingerprint_parts"][:2] == ["shorts_rising", str(company.id)]
    assert kwargs["metadata"]["source_url"] == "https://finra.example/short"
    assert kwargs["metadata"]["kind"] == "DERIVADO"


def test_read_shorts_finra_fecha_antigua_marca_stale(db):
    company = _company(db)
    vieja = (datetime.now(UTC).date() - timedelta(days=30)).isoformat()
    db.add(
        ConnectorState(
            tenant_id=1,
            company_id=company.id,
            connector="public_shorts",
            feed_url="public-shorts",
            last_success_at=datetime.now(UTC),
            metadata_={"source": "FINRA", "date": vieja},
        )
    )
    db.commit()
    result = read_shorts(db, company)
    assert result["status"] == "stale"
    assert "4 días" in result["reason"]
