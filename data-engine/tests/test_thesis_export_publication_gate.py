"""Archived valuation prose must not escape through downloadable exports."""
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.routes.obsidian import _load_thesis_notes_by_company
from app.api.routes.thesis import thesis_epub
from app.models.entities import Base, Company, FundamentalModelVersion, Tenant, ThesisVersion
from app.services.thesis_memo import build_memo_markdown


@pytest.fixture
def saved():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        tenant = Tenant(external_id="gate", name="Gate", status="active", metadata_={})
        other = Tenant(external_id="other", name="Other", status="active", metadata_={})
        company = Company(ticker="AAPL", name="Apple", exchange="NASDAQ", currency="USD", company_type="mature", valuation_model="dcf")
        db.add_all([tenant, other, company])
        db.flush()
        db.info["tenant_id"] = tenant.id
        thesis = ThesisVersion(tenant_id=tenant.id, company_id=company.id, version=3,
            status="published", rating="buy", executive_summary="ARCHIVED_PROSE margen -65,1% valor 119,92",
            thesis_markdown="ARCHIVED_MEMO", expected_value=Decimal("119.92"),
            margin_of_safety=Decimal("-0.651"), valuation_risk_score=87,
            created_at=datetime(2026, 10, 1, tzinfo=UTC))
        db.add(thesis)
        db.commit()
        yield db, company, thesis, other
    engine.dispose()


def model(db, company, *, publishable, version=1, tenant_id=None):
    row = FundamentalModelVersion(tenant_id=tenant_id or db.info["tenant_id"],
        company_id=company.id, version=version, engine_version="test", algorithm_version="test",
        framework_key="dcf", horizon_years=10, status="ok", publishable=publishable,
        input_fingerprint=f"input-{version}", forecast_fingerprint="forecast",
        market_snapshot_fingerprint="market", valuation_snapshot_fingerprint="valuation")
    db.add(row)
    db.commit()
    return row


@pytest.mark.parametrize("publishable", [False, None])
def test_blocked_memo_also_protects_published_audio_input(saved, publishable):
    db, company, thesis, _ = saved
    if publishable is not None:
        model(db, company, publishable=publishable)
    thesis.catalysts = ["ARCHIVED_CATALYST 119,92"]
    thesis.invalidation_criteria = ["ARCHIVED_CRITERION -65,1%"]
    memo = build_memo_markdown(db, company, thesis, draft=False)
    for sentinel in ("ARCHIVED_", "119,92", "-65,1", "rating compra"):
        assert sentinel not in memo
    assert "archivada v3" in memo and "2026-10-01" in memo
    assert "NO es asesoramiento" in memo
    assert thesis.executive_summary.startswith("ARCHIVED_")


def test_blocked_obsidian_has_notice_not_body_or_citations(saved):
    db, company, thesis, _ = saved
    model(db, company, publishable=False)
    notes = _load_thesis_notes_by_company(db, [company])[company.id]
    assert len(notes) == 1
    assert "ARCHIVED_" not in notes[0].body
    assert "archivada v3" in notes[0].body
    assert notes[0].sources == []
    assert thesis.thesis_markdown == "ARCHIVED_MEMO"


def test_blocked_epub_has_notice_not_archived_summary(saved):
    import io
    import zipfile

    db, company, thesis, _ = saved
    model(db, company, publishable=False)
    response = thesis_epub(company.ticker, db)
    with zipfile.ZipFile(io.BytesIO(response.body)) as book:
        text = "\n".join(book.read(name).decode() for name in book.namelist() if name.endswith(".xhtml"))
    assert "ARCHIVED_" not in text and "119,92" not in text
    assert "archivada v3" in text and "2026-10-01" in text


def test_publishable_export_preserves_original_prose(saved):
    db, company, thesis, _ = saved
    model(db, company, publishable=True)
    assert "ARCHIVED_PROSE" in build_memo_markdown(db, company, thesis)
    assert "ARCHIVED_MEMO" in _load_thesis_notes_by_company(db, [company])[company.id][0].body


def test_audio_gate_uses_new_cache_namespace(saved, monkeypatch):
    from app.api.routes.thesis import _audio_context
    from app.services.thesis_service import ThesisService

    db, company, thesis, _ = saved
    row = model(db, company, publishable=True)
    monkeypatch.setattr(ThesisService, "latest_published", lambda *_: thesis)
    monkeypatch.setattr(ThesisService, "data_freshness", lambda *_, **__: None)
    previous_key, previous_text = _audio_context(db, company.ticker, None)
    assert "ARCHIVED" in previous_text
    row.publishable = False
    db.commit()
    key, text = _audio_context(db, company.ticker, None)
    assert key != previous_key and key.endswith("-withheld-v1")
    assert "ARCHIVED" not in text and "119,92" not in text
    assert "archivada v3" in text


def test_whole_vault_gate_uses_one_query_for_many_companies(saved):
    from sqlalchemy import event

    from app.services.thesis_publication_gate import thesis_withheld_reasons

    db, company, thesis, _ = saved
    model(db, company, publishable=False)
    queries = []
    def count(_conn, _cursor, statement, *_args):
        queries.append(statement)
    event.listen(db.bind, "before_cursor_execute", count)
    try:
        assert thesis_withheld_reasons(db, [thesis] * 50)[thesis.id]
    finally:
        event.remove(db.bind, "before_cursor_execute", count)
    assert len(queries) == 1
