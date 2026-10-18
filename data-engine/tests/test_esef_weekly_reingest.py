"""PR-C: re-ingesta ESEF semanal. Fase build (rebuild snapshots desde
filings.xbrl.org) encadena fase ingest (refresh_from_esef por emisor
reviewed presente como Company), en chunks auto-encolados."""

import sys
import types
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models import Company
from app.workers import dramatiq_app as workers


def _db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=[Company.__table__])
    return sessionmaker(bind=engine)()


def _company(db, ticker):
    company = Company(
        ticker=ticker, name=ticker, exchange="BME", currency="EUR",
        sector="S", industry="I", company_type="standard",
        valuation_model="unassigned", special_sources=[], special_risks=[],
        factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


def test_build_phase_rebuilds_snapshots_and_chains_ingest(tmp_path):
    fake_module = types.ModuleType("build_esef_snapshots")

    async def fake_build(out, country, fetched_at, client):
        return {"issuers": {"LEI1": {"ticker": "SAN"}}, "unresolved": {}}

    fake_module.build = fake_build
    db = _db()
    with (
        patch.object(workers, "_session", return_value=db),
        patch.dict(sys.modules, {"build_esef_snapshots": fake_module}),
        patch("app.core.config.get_settings") as settings,
        patch.object(workers.refresh_esef_fundamentals, "send") as send,
    ):
        settings.return_value.esef_snapshot_dir = str(tmp_path)
        result = workers.refresh_esef_fundamentals(tenant_id=1, user_id="u")

    assert result["status"] == "ok" and result["phase"] == "build"
    assert result["issuers"] == 1
    send.assert_called_once_with(1, "u", phase="ingest", cursor=0)


def test_build_phase_skips_without_snapshot_dir():
    db = _db()
    with (
        patch.object(workers, "_session", return_value=db),
        patch("app.core.config.get_settings") as settings,
    ):
        settings.return_value.esef_snapshot_dir = None
        result = workers.refresh_esef_fundamentals(tenant_id=1, user_id="u")
    assert result["status"] == "skipped"
    assert result["reason"] == "esef_snapshot_dir_not_configured"


def test_ingest_phase_refreshes_companies_and_chunks():
    db = _db()
    _company(db, "SAN")

    class _FakeIngestion:
        async def refresh_from_esef(self, db, company):
            return {"facts": 10}

    with (
        patch.object(workers, "_session", return_value=db),
        patch.object(workers, "ESEF_REINGEST_CHUNK", 500),
        patch.object(workers.refresh_esef_fundamentals, "send") as send,
        patch(
            "app.services.financial_ingestion_service.FinancialIngestionService",
            _FakeIngestion,
        ),
    ):
        result = workers.refresh_esef_fundamentals(
            tenant_id=1, user_id="u", phase="ingest", cursor=0)

    assert result["status"] == "ok" and result["phase"] == "ingest"
    assert result["results"]["SAN"] == "ok"  # refrescado via snapshot local
    assert all(v in {"ok", "no_company"} for v in result["results"].values())
    assert sum(1 for v in result["results"].values() if v == "no_company") == \
        result["reviewed_total"] - 1
    assert result["reviewed_total"] >= 100  # tabla reviewed amplia
    assert result["next_cursor"] is None
    send.assert_not_called()  # un solo chunk basta con el tope alto
