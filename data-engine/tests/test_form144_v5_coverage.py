"""Cobertura de lo nuevo (auditor FAV v4): migracion 0137, connector,
monitor, news, persistence, actor y scheduler."""

from __future__ import annotations

from unittest.mock import Mock, patch

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError

from app.models.entities import NewsEvent
from app.services import form144_monitor, form144_news, form144_persistence
from app.services.connectors import form144
from tests.test_0137_form144_migration import _create_table, _load
from tests.test_form144_monitor import REAL_144_XML, _db, _FakeClient

# ---------------- migracion 0137 ----------------


def _create_table_nullable_flipped(conn):
    metadata = sa.MetaData()
    cols = []
    from app.models.entities import Form144Notice

    for column in Form144Notice.__table__.columns:
        nullable = (not column.nullable) if column.name == "accession_number" else column.nullable
        cols.append(sa.Column(column.name, column.type, nullable=nullable, primary_key=(column.name == "id")))
    sa.Table("form144_notices", metadata, *cols)
    metadata.create_all(conn)


def test_adoption_rejects_nullable_mismatch(monkeypatch):
    module = _load()
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        monkeypatch.setattr(module, "op", Operations(MigrationContext.configure(conn)))
        _create_table_nullable_flipped(conn)
        with pytest.raises(RuntimeError, match="schema mismatch"):
            module.upgrade()


def test_adoption_rejects_string_length_mismatch(monkeypatch):
    module = _load()
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        monkeypatch.setattr(module, "op", Operations(MigrationContext.configure(conn)))
        conn.exec_driver_sql(
            "CREATE TABLE form144_notices (id INTEGER PRIMARY KEY, accession_number VARCHAR(41))"
        )
        with pytest.raises(RuntimeError, match="schema mismatch"):
            module.upgrade()


def test_adoption_rejects_missing_pk(monkeypatch):
    module = _load()
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        monkeypatch.setattr(module, "op", Operations(MigrationContext.configure(conn)))
        _create_table(conn, with_pk=False)
        with pytest.raises(RuntimeError, match="sin PK"):
            module.upgrade()


def test_adoption_with_full_constraints_marks_adopted(monkeypatch):
    module = _load()
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE tenants (id INTEGER PRIMARY KEY)")
        _create_table(conn)
        ops = Operations(MigrationContext.configure(conn))
        with ops.batch_alter_table("form144_notices") as batch:
            batch.create_unique_constraint("uq_existing", ["tenant_id", "accession_number"])
            batch.create_foreign_key("fk_ok", "tenants", ["tenant_id"], ["id"])
        monkeypatch.setattr(module, "op", ops)
        module.upgrade()
        mode = conn.scalar(
            sa.text(
                "SELECT mode FROM migration_table_provenance "
                "WHERE revision='0137_form144_notices' AND table_name='form144_notices'"
            )
        )
        assert mode == "adopted"
        module.downgrade()
        assert sa.inspect(conn).has_table("form144_notices")  # adoptada: no se borra


def test_downgrade_without_provenance_row_keeps_table(monkeypatch):
    module = _load()
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        monkeypatch.setattr(module, "op", Operations(MigrationContext.configure(conn)))
        module.upgrade()  # created + marca created
        conn.execute(
            sa.text(
                "DELETE FROM migration_table_provenance "
                "WHERE revision='0137_form144_notices' AND table_name='form144_notices'"
            )
        )
        module.downgrade()  # sin marca: lo seguro es conservar
        assert sa.inspect(conn).has_table("form144_notices")


# ---------------- connector ----------------


def test_sleep_and_get_text_delegate(monkeypatch):
    form144._sleep(0)
    seen = {}
    monkeypatch.setattr(
        form144.edgar_common,
        "get_text",
        lambda url, client, headers=None, throttle=None, sleep=None: seen.update(
            url=url, headers=headers, throttle=throttle
        )
        or "TXT",
    )
    assert form144._get_text("https://www.sec.gov/x", None) == "TXT"
    assert seen["url"] == "https://www.sec.gov/x"
    assert seen["throttle"] is not None


def test_is_form144_xml_accepts_defusedxml_rejected_xml():
    hostile = '<!DOCTYPE edgarSubmission [<!ENTITY a "x">]><edgarSubmission><formData/></edgarSubmission>'
    assert form144._is_form144_xml(hostile) is True  # la decision es del parser (unparsed)
    assert form144._is_form144_xml("<div>AccessDenied</div>") is False


def test_fetch_filing_xml_retries_rendered_html_with_raw(monkeypatch):
    responses = iter(["<html>rendered</html>", REAL_144_XML])
    monkeypatch.setattr(form144, "_get_text", lambda url, client=None: next(responses))
    rendered = (
        "https://www.sec.gov/Archives/edgar/data/849869/000084986926000005/"
        "xsl144X01/primary_doc.xml"
    )
    assert form144.fetch_filing_xml(rendered) == REAL_144_XML


def test_fetch_filing_xml_rejects_non_sec_host():
    with pytest.raises(ValueError, match="sec.gov"):
        form144.fetch_filing_xml("https://evil.example.com/doc.xml")


def test_fetch_filing_xml_raises_when_no_xml_variant(monkeypatch):
    monkeypatch.setattr(form144, "_get_text", lambda url, client=None: "<html>nope</html>")
    with pytest.raises(ValueError, match="no es un Form 144"):
        form144.fetch_filing_xml(
            "https://www.sec.gov/Archives/edgar/data/849869/000084986926000005/primary_doc.xml"
        )


def test_parse_helpers_never_invent():
    assert form144._children(None, "x") == []
    assert form144._to_int("1,234") == 1234
    assert form144._to_int(None) is None
    assert form144._to_int("abc") is None
    assert form144._to_float("3.5") == 3.5
    assert form144._to_float(None) is None
    assert form144._to_float("abc") is None
    assert form144._yes_no("Y") is True
    assert form144._yes_no("N") is False
    assert form144._yes_no("X") is None
    totals = form144.proposed_sale_totals(
        {
            "securities": [
                {
                    "shares": 10.0,
                    "market_value": 100.0,
                    "shares_outstanding": 1000.0,
                    "approx_sale_date": "11/16/2026",
                    "exchange": "NASDAQ",
                    "broker_name": "BROKER",
                    "securities_class_title": "Common",
                }
            ]
        }
    )
    assert totals["shares_to_sell"] == 10  # entero declarado: int
    assert form144.proposed_sale_totals({"securities": []})["shares_to_sell"] is None


# ---------------- monitor ----------------


def test_normalize_cik_tolerant():
    assert form144_monitor._normalize_cik("0000849869") == "849869"
    assert form144_monitor._normalize_cik("ABC") == "ABC"


def test_missing_cik_reported_and_status_error(monkeypatch):
    db = _db()
    monkeypatch.setattr(form144_monitor, "resolve_ciks", lambda *a, **k: {})
    stats = form144_monitor.scan(db, tickers=["ZZT"], delay_seconds=0)
    assert stats["tickers_scanned"] == 0
    assert any("sin CIK SEC" in e for e in stats["errors"])
    assert stats["status"] == "error"


def test_zero_download_budget_stops_before_first_listing(monkeypatch):
    db = _db()
    listing = Mock(return_value=[])
    monkeypatch.setattr(form144_monitor, "resolve_ciks", lambda *a, **k: {"ZZT": "1"})
    monkeypatch.setattr(form144_monitor.form144_connector, "recent_form144_filings", listing)
    stats = form144_monitor.scan(db, tickers=["ZZT"], max_new_fetches=0, delay_seconds=0)
    assert listing.call_count == 0
    assert any("presupuesto de descargas agotado" in e for e in stats["errors"])


def test_zero_time_budget_stops_immediately(monkeypatch):
    db = _db()
    listing = Mock(return_value=[])
    monkeypatch.setattr(form144_monitor, "resolve_ciks", lambda *a, **k: {"ZZT": "1"})
    monkeypatch.setattr(form144_monitor.form144_connector, "recent_form144_filings", listing)
    stats = form144_monitor.scan(db, tickers=["ZZT"], max_seconds=0, delay_seconds=0)
    assert listing.call_count == 0
    assert any("presupuesto de tiempo agotado" in e for e in stats["errors"])


def test_listing_failure_is_per_ticker_and_continues(monkeypatch):
    db = _db()
    monkeypatch.setattr(form144_monitor, "resolve_ciks", lambda *a, **k: {"ZZT": "1", "AAA": "2"})

    def boom(cik, **kwargs):
        if cik == "1":
            raise RuntimeError("sec down")
        return []

    monkeypatch.setattr(form144_monitor.form144_connector, "recent_form144_filings", boom)
    stats = form144_monitor.scan(db, tickers=["AAA", "ZZT"], delay_seconds=0)
    assert stats["tickers_listed"] == 2  # sigue con el siguiente emisor
    assert any("ZZT: form144_list_error" in e for e in stats["errors"])
    assert stats["status"] == "partial"


def test_inner_download_budget_keeps_offset_on_partial_ticker(monkeypatch):
    db = _db()
    filings = [
        {"accession_number": f"0000849869-26-0000{i:02d}", "form": "144", "filing_date": "2026-11-13",
         "document_url": "https://www.sec.gov/Archives/edgar/data/849869/x/primary_doc.xml"}
        for i in range(3)
    ]
    monkeypatch.setattr(form144_monitor, "resolve_ciks", lambda *a, **k: {"ZZT": "0000849869"})
    monkeypatch.setattr(form144_monitor.form144_connector, "recent_form144_filings", lambda *a, **k: filings)
    stats = form144_monitor.scan(
        db, tickers=["ZZT"], max_new_fetches=1, delay_seconds=0, fetcher=lambda filing: REAL_144_XML
    )
    assert stats["filings_new"] == 1
    assert stats["next_offset"] == 0  # el emisor a medias se rehace entero
    assert any("presupuesto de descargas agotado" in e for e in stats["errors"])


def test_real_download_path_without_fetcher(monkeypatch):
    db = _db()
    monkeypatch.setattr(
        form144_monitor.form144_connector, "fetch_filing_xml", lambda url, client=None: REAL_144_XML
    )
    stats = form144_monitor.scan(db, client=_FakeClient(), delay_seconds=0)
    assert stats["filings_new"] == 1


def test_issuer_mismatch_rejected_and_delayed(monkeypatch):
    db = _db()
    hostile = REAL_144_XML.replace("<issuerCik>0000849869</issuerCik>", "<issuerCik>9999999999</issuerCik>")
    sleeps: list[float] = []
    stats = form144_monitor.scan(
        db,
        client=_FakeClient(),
        fetcher=lambda filing: hostile,
        delay_seconds=0.5,
        sleeper=sleeps.append,
    )
    assert stats["filings_rejected"] == 1
    assert sleeps == [0.5]
    assert stats["filings_new"] == 0


def test_filing_failure_is_best_effort(monkeypatch):
    db = _db()

    def boom(filing):
        raise RuntimeError("xml roto")

    # Exercise the filing-error path without a real SEC listing request.
    # A failed listing would stop before boom and test the wrong branch.
    monkeypatch.setattr("httpx.Client.get", Mock(side_effect=AssertionError("unexpected live HTTP")))
    fetcher = Mock(side_effect=boom)
    stats = form144_monitor.scan(db, client=_FakeClient(), fetcher=fetcher, delay_seconds=0.01, sleeper=lambda s: None)
    fetcher.assert_called_once()
    assert stats["filings_new"] == 0
    assert any("form144_filing_error" in e for e in stats["errors"])
    assert stats["status"] == "partial"


def test_fatal_never_raises_and_stays_public_reason(monkeypatch):
    db = _db()
    monkeypatch.setattr(
        form144_monitor, "resolve_ciks", Mock(side_effect=RuntimeError("redis url con secreto"))
    )
    stats = form144_monitor.scan(db, tickers=["ZZT"], delay_seconds=0)
    assert stats["status"] == "error"
    assert stats["errors"] == ["fatal: form144_scan_fatal"]
    assert "secreto" not in str(stats)


# ---------------- news ----------------

_ARCH_URL = "https://www.sec.gov/Archives/edgar/data/849869/000084986926000005/primary_doc.xml"
_FILING = {
    "accession_number": "0000849869-26-000005",
    "issuer_ticker": "ZZT",
    "document_url": _ARCH_URL,
    "filing_date": "2026-11-16",
    "form": "144",
}


def test_news_rejects_invalid_identity(db=None):
    db = _db()
    assert form144_news.ensure_news(db, {**_FILING, "accession_number": "bad"})["reason"] == "invalid_identity"
    other_url = "https://www.sec.gov/Archives/edgar/data/849869/000084986926000099/primary_doc.xml"
    assert (
        form144_news.ensure_news(db, {**_FILING, "document_url": other_url})["reason"]
        == "invalid_identity"
    )
    assert (
        form144_news.ensure_news(db, _FILING, parsed={"issuer_cik": "9999999"})["reason"]
        == "issuer_mismatch"
    )
    assert (
        form144_news.ensure_news(db, {**_FILING, "filing_date": "no-es-fecha"})["reason"]
        == "invalid_date"
    )
    assert form144_news.ensure_news(db, {**_FILING, "issuer_ticker": "NOEXISTE"})["reason"] == (
        "issuer_not_found"
    )


def test_news_summary_marks_10b5_plan():
    db = _db()
    parsed = {
        "parsed_ok": True,
        "issuer_cik": "0000849869",
        "seller_name": "LEWIS ROBERT B",
        "plan_adoption_dates": ["05/01/2026"],
        "relationships": ["Director"],
    }
    out = form144_news.ensure_news(db, _FILING, parsed)
    assert out["created"] is True
    row = db.scalar(select(NewsEvent))
    assert "10b5-1" in row.summary


def test_news_update_keeps_previous_parsed_data():
    db = _db()
    good = {"parsed_ok": True, "issuer_cik": "0000849869", "seller_name": "LEWIS ROBERT B"}
    assert form144_news.ensure_news(db, _FILING, good)["created"] is True
    # Una re-ingesta sin parsear no pisa los datos parseados previos.
    out = form144_news.ensure_news(db, _FILING, {"parsed_ok": False})
    assert out["created"] is False
    row = db.scalar(select(NewsEvent))
    assert row.metadata_["proposed_sale"]["seller_name"] == "LEWIS ROBERT B"


def test_news_identity_race_retries_once():
    db = _db()
    parsed = {"parsed_ok": True, "issuer_cik": "0000849869"}
    assert form144_news.ensure_news(db, _FILING, parsed)["created"] is True
    db.commit()  # sin pendientes: el flush parcheado solo se dispara en el reintento
    original_flush = db.flush
    calls = {"n": 0}

    def flaky_flush(*args, **kwargs):
        # autoflush invoca flush() en cada query aunque no haya nada pendiente:
        # la carrera solo se simula cuando hay trabajo real que escribir.
        if not (db.new or db.dirty):
            return original_flush(*args, **kwargs)
        calls["n"] += 1
        if calls["n"] == 1:
            raise IntegrityError("INSERT", {}, Exception("unique"))
        return original_flush(*args, **kwargs)

    with patch.object(db, "flush", flaky_flush):
        out = form144_news.ensure_news(db, _FILING, parsed)
    assert out["created"] is False  # gano la fila existente en el reintento


# ---------------- persistence ----------------


def test_persist_existing_filing_notifies_news_without_duplicate(monkeypatch):
    db = _db()
    parsed = form144.parse_form144_xml(REAL_144_XML)
    filing = dict(_FILING)
    first = form144_persistence.persist_filing(db, filing, parsed, raw_text=REAL_144_XML)
    assert first["filing_created"] is True
    seen = []
    monkeypatch.setattr(
        "app.services.form144_news.ensure_news",
        lambda db, filing, payload, tenant_id=None: seen.append(payload) or {"created": False},
    )
    second = form144_persistence.persist_filing(db, filing, parsed, raw_text=REAL_144_XML)
    assert second["filing_created"] is False
    assert second["filing_id"] == first["filing_id"]
    assert seen  # la noticia se recalcula sobre la fila existente


# ---------------- actor y scheduler ----------------


def test_actor_executes_scan_under_lease(monkeypatch):
    from app.workers import dramatiq_app

    closed = {"db": False}

    class FakeDb:
        info = {"tenant_id": 7}

        def close(self):
            closed["db"] = True

    monkeypatch.setattr(dramatiq_app, "_session", lambda tenant_id, user_id: FakeDb())
    monkeypatch.setattr(dramatiq_app, "acquire_job_lease", lambda *a, **k: object())
    released = []
    monkeypatch.setattr(dramatiq_app, "release_job_lease", lambda *a, **k: released.append(a))
    monkeypatch.setattr(dramatiq_app, "_lease_redis_url", lambda: None)
    from app.services import form144_monitor as monitor_mod

    monkeypatch.setattr(
        monitor_mod,
        "scan",
        lambda db, **kw: {
            "status": "ok",
            "tickers_scanned": 1,
            "filings_seen": 1,
            "filings_new": 0,
            "filings_unparsed": 0,
            "filings_rejected": 0,
            "errors": [],
        },
    )
    out = dramatiq_app.scan_form144_watchlist.fn(tenant_id=7)
    assert out["status"] == "ok"
    assert out["actor"] == "scan_form144_watchlist"
    assert closed["db"] and released


def test_actor_skips_when_lease_held(monkeypatch):
    from app.workers import dramatiq_app

    class FakeDb:
        info = {"tenant_id": 7}

        def close(self):
            pass

    monkeypatch.setattr(dramatiq_app, "_session", lambda tenant_id, user_id: FakeDb())
    monkeypatch.setattr(dramatiq_app, "acquire_job_lease", lambda *a, **k: None)
    monkeypatch.setattr(dramatiq_app, "_lease_redis_url", lambda: None)
    out = dramatiq_app.scan_form144_watchlist.fn(tenant_id=7)
    assert out["status"] == "skipped"
    assert out["reason"] == "lease_held"


def test_scheduler_registers_form144_hourly_job():
    import app.workers.scheduler as sched

    jobs = []

    class Fake:
        def add_job(self, func, trigger, id=None, **kw):
            jobs.append((id, trigger, kw, func))

    with patch.object(sched, "BlockingScheduler", return_value=Fake()), patch.object(
        sched, "tenant_contexts", return_value=[]
    ), patch("app.workers.dramatiq_app._redis_client", return_value=None):
        sched.build_scheduler()
    hourly = [job for job in jobs if job[0] == "form144_watchlist_hourly"]
    assert len(hourly) == 1
    _, trigger, kwargs, func = hourly[0]
    assert trigger == "interval"
    assert kwargs["hours"] == 1
    from app.workers.dramatiq_app import scan_form144_watchlist

    assert scan_form144_watchlist in func.args
