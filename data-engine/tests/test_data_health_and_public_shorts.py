"""Hermetic source identity, failure preservation and tenant coverage contracts."""
import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.entities import Base, Company, ConnectorState, FinancialFact, Tenant
from app.services.cnmv_mapping import resolve_issuer
from app.services.connectors.cnmv_shorts import fetch_positions, parse_positions
from app.services.data_health_service import inventory
from app.services.short_positions_service import read_shorts, refresh_shorts

ISSUER = resolve_issuer("GRF")
PAGE = '''<div>ES0171996087</div><table><caption>Notificaciones vivas iguales o superiores al 0,5%</caption><tbody><tr><td>Fund</td><td>1,810</td><td>21/08/2026</td><td>Histórico</td></tr></tbody></table><table><tbody><tr><td>Old</td><td>9,000</td></tr></tbody></table>'''


def test_current_only_and_identity():
    result = parse_positions(PAGE, ISSUER)
    assert result == [{"holder": "Fund", "percent": 1.81, "position_date": "2026-08-21"}]
    for page in ["", PAGE.replace("ES0171996087", "OTHER"), PAGE.replace("Notificaciones vivas", "Históricas"), PAGE.replace("1,810", "0,490"), PAGE.replace("1,810", "NaN")]:
        with pytest.raises(Exception):
            parse_positions(page, ISSUER)


def test_cnmv_fetch_link_threshold_and_derived_sum():
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, text=PAGE))) as client:
            return await fetch_positions(ISSUER, client=client)
    result = asyncio.run(run())
    assert result["public_total_percent"] == 1.81
    assert "nif=A58389123" in result["source_url"]
    assert result["total_kind"] == "DERIVADO"


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with sessionmaker(engine)() as db:
        db.add_all([Tenant(id=1, external_id="one"), Tenant(id=2, external_id="two")])
        db.add(Company(id=1, ticker="GRF", name="Grifols", exchange="BME", currency="EUR", company_type="mature", valuation_model="dcf"))
        db.commit()
        db.info["tenant_id"] = 1
        yield db
    engine.dispose()


def test_coverage_excludes_seed_and_other_tenant_and_not_live(db):
    now = datetime.now(UTC)
    db.add_all([FinancialFact(company_id=1, tenant_id=1, metric="sales", value=Decimal("1"), period="FY", source_type="SEC", updated_at=now - timedelta(days=100)),
                FinancialFact(company_id=1, tenant_id=1, metric="sales", value=Decimal("2"), period="FY", source_type="seed"),
                FinancialFact(company_id=1, tenant_id=2, metric="sales", value=Decimal("3"), period="FY", source_type="FMP")])
    # Seed different owners without current write guard.
    db.info.pop("tenant_id")
    db.commit()
    db.info["tenant_id"] = 1
    result = inventory(db, now=now)
    facts = [r for r in result["sources"] if r["layer"] == "Fundamentales"]
    assert len(facts) == 1 and facts[0]["source"] == "SEC"
    assert facts[0]["coverage_pct"] == 100 and facts[0]["status"] == "stale"
    assert "no fecha del dato" in result["freshness_basis"]
    db.info["tenant_id"] = 2
    assert [r for r in inventory(db)["sources"] if r["layer"] == "Fundamentales"][0]["source"] == "FMP"


def test_failure_preserves_data_and_reads_never_fetch(db, monkeypatch):
    company = db.get(Company, 1)
    now = datetime.now(UTC)
    db.add(ConnectorState(tenant_id=1, company_id=1, connector="public_shorts", feed_url="public-shorts", last_success_at=now, metadata_={"source": "CNMV", "positions": []}))
    db.commit()
    async def failed(*args, **kwargs):
        raise httpx.ConnectError("secret details")
    monkeypatch.setattr("app.services.short_positions_service.fetch_positions", failed)
    result = asyncio.run(refresh_shorts(db, company))
    assert result["status"] == "degraded" and result["data"]["source"] == "CNMV"
    assert "secret" not in str(result)
    assert read_shorts(db, company)["data"]["positions"] == []
    db.info["tenant_id"] = 2
    assert read_shorts(db, company)["data"] is None


def test_rate_guard_and_no_anonymous_access(db, monkeypatch):
    company = db.get(Company, 1)
    now = datetime.now(UTC)
    db.add(ConnectorState(tenant_id=1, company_id=1, connector="public_shorts", feed_url="public-shorts", last_started_at=now))
    db.commit()
    async def unexpected(*args, **kwargs):
        raise AssertionError("network called")
    monkeypatch.setattr("app.services.short_positions_service.fetch_positions", unexpected)
    assert asyncio.run(refresh_shorts(db, company))["status"] == "empty"
    db.info.pop("tenant_id")
    with pytest.raises(ValueError, match="Tenant"):
        inventory(db)
    with pytest.raises(ValueError, match="Tenant"):
        read_shorts(db, company)


@pytest.mark.parametrize("value", ["NaN", "inf", "-1", "1.5", "101"])
def test_finra_invalid_volumes_fail_closed(value):
    from app.services.connectors.short_interest import parse_regsho_daily
    assert parse_regsho_daily(f"20261006|ASTS|{value}|0|100|Q", "ASTS") is None


def test_finra_block_stops_requests():
    from app.services.connectors.short_interest import fetch_short_volume
    requests = []
    def blocked(request):
        requests.append(request)
        return httpx.Response(403)
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(blocked)) as client:
            return await fetch_short_volume("ASTS", client=client)
    assert asyncio.run(run()) is None
    assert len(requests) == 1


def test_unmapped_market_honest_and_no_network(db):
    company = db.get(Company, 1)
    company.ticker = "UNKNOWN.MC"
    db.commit()
    result = asyncio.run(refresh_shorts(db, company))
    assert result["data"] is None
    assert "mapeo revisado" in result["reason"]


def test_failed_layer_has_no_fake_zero(db, monkeypatch):
    original = db.execute
    def fail_facts(statement, *args, **kwargs):
        if "financial_facts" in str(statement):
            raise RuntimeError("private query details")
        return original(statement, *args, **kwargs)
    monkeypatch.setattr(db, "execute", fail_facts)
    facts = [row for row in inventory(db)["sources"] if row["layer"] == "Fundamentales"][0]
    assert facts["covered"] is None and facts["coverage_pct"] is None
    assert facts["status"] == "error" and "private" not in facts["reason"]


def test_propicks_missing_candidates_is_degraded(db):
    from app.models import ProPickRun
    db.add(ProPickRun(tenant_id=1, as_of=datetime.now(UTC), status="completed", funnel_version="test", universe_size=100))
    db.commit()
    row = [row for row in inventory(db)["connectors"] if row["source"].startswith("ProPicks")][0]
    assert row["status"] == "degraded" and row["errors"] is None


def test_cache_is_tenant_scoped(db, monkeypatch):
    from app.services import data_health_service as health
    health._CACHE.clear()
    calls = []
    def fake_inventory(session):
        calls.append(session.info["tenant_id"])
        return {"tenant": session.info["tenant_id"]}
    monkeypatch.setattr(health, "inventory", fake_inventory)
    assert health.read_inventory(db) == {"tenant": 1}
    assert health.read_inventory(db) == {"tenant": 1}
    db.info["tenant_id"] = 2
    assert health.read_inventory(db) == {"tenant": 2}
    assert calls == [1, 2]
    health._CACHE.clear()


def test_recent_fetch_does_not_make_old_finra_trade_current(db):
    company = db.get(Company, 1)
    db.add(ConnectorState(tenant_id=1, company_id=1, connector="public_shorts", feed_url="public-shorts", last_success_at=datetime.now(UTC), metadata_={"source": "FINRA", "date": "2024-01-01"}))
    db.commit()
    assert read_shorts(db, company)["status"] == "stale"


def test_esef_row_carries_eligibility_denominator(db):
    """ESEF solo aplica a emisores reviewed CNMV: la fila debe declarar el
    denominador de elegibilidad (no el universo) y su cobertura relativa."""

    now = datetime.now(UTC)
    db.add(Company(id=2, ticker="SAN", name="Santander", exchange="BME",
                   currency="EUR", company_type="mature", valuation_model="dcf"))
    db.add(FinancialFact(company_id=2, tenant_id=1, metric="revenue",
                         value=Decimal("1"), period="FY2025", source_type="ESEF",
                         is_reported=True, updated_at=now))
    db.commit()
    result = inventory(db, now=now)
    esef = [r for r in result["sources"] if r["source"] == "ESEF"][0]
    assert esef["covered"] == 1
    # De los reviewed existen SAN y GRF (fixture) como Company:
    assert esef["eligible"] == 2
    assert esef["coverage_pct_eligible"] == 50.0
    # La cobertura cruda contra el universo se mantiene (contexto), sin
    # disfrazarla de fallo de la fuente:
    assert esef["coverage_pct"] == round(100 * 1 / esef["total"], 2)
    sec = [r for r in result["sources"] if r["source"] == "SEC"]
    if sec:  # fuentes sin cota: sin denominador de elegibilidad
        assert sec[0]["eligible"] is None


def test_sec_backfill_connector_states_aggregate_into_one_line(db):
    """Objecion del auditor: el backfill SEC crea una ConnectorState por
    compania intentada (potencialmente ~2.000); una linea por fila llenaria
    el panel de salud de "empty/degraded" repetidas. Debe agregarse en una
    sola linea con contadores y sin tragarse los demas conectores."""
    now = datetime.now(UTC)
    db.add_all([
        ConnectorState(tenant_id=1, connector="sec-fundamentals-backfill",
                       company_id=1, feed_url="companyfacts",
                       last_started_at=now, last_success_at=now,
                       metadata_={"status": "ok", "reason": None}),
        ConnectorState(tenant_id=1, connector="sec-fundamentals-backfill",
                       company_id=2, feed_url="companyfacts",
                       last_started_at=now, consecutive_errors=3,
                       last_error="timeout",
                       metadata_={"status": "error", "reason": "timeout"}),
        ConnectorState(tenant_id=1, connector="insider-monitor",
                       last_started_at=now, last_success_at=now),
    ])
    db.commit()
    rows = [row for row in inventory(db)["connectors"]
            if row["source"].startswith("sec-fundamentals-backfill")]
    assert len(rows) == 1
    row = rows[0]
    assert "2 empresas" in row["source"]
    assert "ok 1" in row["source"] and "error 1" in row["source"]
    assert row["status"] == "degraded" and row["errors"] == 1
    assert row["last_success"] is not None and row["last_attempt"] is not None
    # El resto de conectores siguen saliendo como siempre.
    assert any(r["source"] == "insider-monitor" for r in inventory(db)["connectors"])


def test_sec_backfill_aggregate_observed_when_only_ok(db):
    now = datetime.now(UTC)
    db.add(ConnectorState(tenant_id=1, connector="sec-fundamentals-backfill",
                          company_id=1, feed_url="companyfacts",
                          last_started_at=now, last_success_at=now,
                          metadata_={"status": "ok"}))
    db.commit()
    row = [r for r in inventory(db)["connectors"]
           if r["source"].startswith("sec-fundamentals-backfill")][0]
    assert row["status"] == "observed" and row["errors"] == 0



def test_rss_feed_states_aggregate_into_one_line(db):
    """refresh_rss_feeds guarda una ConnectorState por feed (cursor de #3029):
    una linea "rss" por feed llenaria el panel de filas identicas sin URL.
    Se agrega en una sola linea con contadores, como el backfill SEC."""
    now = datetime.now(UTC)
    db.add_all([
        ConnectorState(tenant_id=1, connector="rss", feed_url=f"https://feed{n}.example/rss",
                       last_started_at=now, last_success_at=now)
        for n in range(3)
    ] + [
        ConnectorState(tenant_id=1, connector="rss", feed_url="https://caido.example/rss",
                       last_started_at=now, consecutive_errors=2, last_error="timeout"),
        ConnectorState(tenant_id=1, connector="insider-monitor",
                       last_started_at=now, last_success_at=now),
    ])
    db.commit()
    connectors = inventory(db)["connectors"]
    rows = [row for row in connectors if row["source"].startswith("rss")]
    assert len(rows) == 1
    row = rows[0]
    assert "4 feeds" in row["source"]
    assert "ok 3" in row["source"] and "error 1" in row["source"]
    assert row["status"] == "degraded" and row["errors"] == 1
    assert row["last_success"] is not None and row["last_attempt"] is not None
    assert any(r["source"] == "insider-monitor" for r in connectors)
