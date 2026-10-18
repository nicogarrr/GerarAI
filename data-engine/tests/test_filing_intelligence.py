from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models.entities import (
    Base,
    Company,
    Document,
    DocumentChunk,
    Position,
    ResearchAlert,
    Tenant,
    WatchItem,
)
from app.services.earnings_releases import summarize_release
from app.services.filing_changes import comparable, compare_sections
from app.services.filing_intelligence import KEY, analyze_document, official_document


def chunks(text):
    return [{"id": 11, "chunk_index": 0, "text": text}]


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with sessionmaker(engine, expire_on_commit=False)() as session:
        tenant = Tenant(external_id="filing-one", name="One")
        other = Tenant(external_id="filing-two", name="Two")
        company = Company(ticker="FILING", name="Filing", exchange="NASDAQ", currency="USD",
                          company_type="holding", valuation_model="unassigned")
        session.add_all([tenant, other, company])
        session.flush()
        session.info.update(tenant_id=tenant.id, company_id=company.id, other_tenant=other.id)
        session.add(WatchItem(symbol="FILING"))
        session.commit()
        yield session
    engine.dispose()


def document(db, *, period="2026-09-30", form="10-Q", text=None, tenant=None, number=1):
    doc = Document(tenant_id=tenant or db.info["tenant_id"], company_id=db.info["company_id"],
                   title=form, source_type="SEC",
                   source_url=f"https://www.sec.gov/Archives/edgar/data/1/{number}/report.htm",
                   checksum=f"hash-{number}", published_at=datetime(2026, 10, 1, tzinfo=UTC),
                   metadata_={"form": form, "report_date": period})
    active_tenant = db.info["tenant_id"]
    db.info["tenant_id"] = doc.tenant_id
    db.add(doc)
    db.flush()
    if text:
        db.add(DocumentChunk(tenant_id=doc.tenant_id, document_id=doc.id, chunk_index=0, text=text))
    db.commit()
    db.info["tenant_id"] = active_tenant
    return doc


OLD = "Item 1A. Risk Factors\nOur supplier concentration may delay commercial production.\nItem 2. Properties\nNo comparison outside the risk section.\nOutlook\nRevenue guidance is $4.87 billion for fiscal 2026.\nNote 12. Related-party transactions\nWe purchased services from related parties for $12 million."
NEW = OLD.replace("supplier concentration", "single supplier dependence").replace("$4.87", "$5.12")


def test_diff_quotes_numbers_and_heading_boundaries():
    result = compare_sections(chunks(NEW), chunks(OLD))
    assert result["status"] == "changed"
    risk, guidance, related = result["sections"]
    assert risk["changes"][0]["before"][0]["text"].startswith("Our supplier concentration")
    assert "$5.12 billion" in guidance["changes"][0]["after"][0]["text"]
    assert related["status"] == "unchanged"
    assert "outside" not in str(risk)
    assert risk["changes"][0]["after"][0]["chunk_id"] == 11


def test_missing_section_does_not_claim_removed():
    result = compare_sections(chunks("Revenue guidance remains unchanged for next year."), chunks(OLD))
    risk = result["sections"][0]
    assert risk["status"] == "insufficient_data"
    assert risk["changes"] == []


@pytest.mark.parametrize("previous", [
    {"form": "10-K", "report_date": "2025-09-30"},
    {"form": "10-Q", "report_date": "2026-06-30"},
    {"form": "10-Q/A", "report_date": "2025-09-30"},
    {"form": "10-Q", "report_date": "invalid"},
    {"form": "10-Q", "report_date": "2025-06-30"},
])
def test_non_comparable_periods(previous):
    assert not comparable({"form": "10-Q", "report_date": "2026-09-30"}, previous)


def test_year_ago_53_week_calendar():
    assert comparable({"form": "10-K", "report_date": "2026-10-03"},
                      {"form": "10-K", "report_date": "2025-09-27"})


def test_no_period_inferred_from_publication(db):
    prior = document(db, period="2025-09-30", text=OLD, number=1)
    now = document(db, period=None, text=NEW, number=2)
    assert analyze_document(db, now)["status"] == "insufficient_data"
    assert "previous_source" not in analyze_document(db, now)
    assert prior.id != now.id


def test_tenant_scoped_comparison_alert_dedup_and_citations(db):
    document(db, period="2025-09-30", text=OLD, tenant=db.info["other_tenant"], number=1)
    now = document(db, text=NEW, number=2)
    assert analyze_document(db, now)["status"] == "insufficient_data"
    prior = document(db, period="2025-09-30", text=OLD, number=3)
    result = analyze_document(db, now)
    db.commit()
    assert result["previous_source"]["document_id"] == prior.id
    assert result["status"] == "changed"
    assert now.metadata_[KEY]["source"]["checksum"] == now.checksum
    analyze_document(db, now)
    db.commit()
    alerts = db.scalars(select(ResearchAlert)).all()
    assert len(alerts) == 1
    assert alerts[0].channels == ["in_app"]
    assert alerts[0].metadata_["matching"] == ["watchlist"]
    assert alerts[0].metadata_["thesis_path"] == "/research/FILING"
    assert alerts[0].metadata_["thesis_version_id"] is None


def test_held_company_alert_and_untracked_silence(db):
    db.query(WatchItem).delete()
    document(db, period="2025-09-30", text=OLD, number=1)
    now = document(db, text=NEW, number=2)
    analyze_document(db, now)
    assert db.scalar(select(ResearchAlert.id)) is None
    db.add(Position(company_id=db.info["company_id"], quantity=Decimal("2")))
    db.commit()
    analyze_document(db, now)
    db.commit()
    assert db.scalar(select(ResearchAlert)).metadata_["matching"] == ["cartera"]


def test_wrong_tenant_and_absent_tenant_fail_closed(db):
    doc = document(db, text=NEW)
    db.info["tenant_id"] = db.info["other_tenant"]
    with pytest.raises(ValueError):
        analyze_document(db, doc)
    db.info.pop("tenant_id")
    with pytest.raises(ValueError):
        analyze_document(db, doc)


@pytest.mark.parametrize("url", ["https://www.sec.gov.evil.test/Archives/edgar/data/1/x.htm",
                                     "https://evil.test/x", "https://www.sec.gov/files/news.htm",
                                     "https://u:p@www.sec.gov/Archives/edgar/data/1/x.htm"])
def test_unofficial_url_not_promoted(db, url):
    doc = document(db, text=NEW)
    doc.source_url = url
    assert not official_document(doc)
    assert analyze_document(db, doc)["status"] == "insufficient_data"


RELEASE = "Quarterly results\nRevenue was $4.87 billion, compared with $4.01 billion last year.\nThe company raised revenue guidance to $5.12 billion."


def test_extracts_release_verbatim_no_numeric_derivation():
    result = summarize_release(chunks(RELEASE), {"form": "8-K"})
    assert result["status"] == "ready"
    assert result["key_points"][0]["text"] == "Revenue was $4.87 billion, compared with $4.01 billion last year."
    assert result["guidance"][0]["change_status"] == "explicit_language"
    assert result["guidance_comparison_status"] == "not_established"


def test_not_all_8k_or_ex99_are_earnings():
    assert summarize_release(chunks("We appointed a new chief executive officer."), {"form": "8-K"})["status"] == "insufficient_data"
    assert summarize_release(chunks(RELEASE), {"form": "EX-99.1"})["status"] == "insufficient_data"
    assert summarize_release(chunks(RELEASE), {"form": "EX-99.1", "parent_form": "8-K"})["status"] == "ready"
    stub = "Financial results are incorporated by reference to Exhibit 99.1. Revenue guidance is in the attached exhibit."
    assert summarize_release(chunks(stub), {"form": "8-K"})["status"] == "insufficient_data"


def test_no_guidance_change_claim_without_explicit_language():
    result = summarize_release(chunks(RELEASE.replace("raised", "provided")), {"form": "8-K"})
    assert result["guidance"][0]["change_status"] == "not_established"


def test_persisted_earnings_alert(db):
    doc = document(db, form="8-K", text=RELEASE)
    result = analyze_document(db, doc)
    db.commit()
    assert result["status"] == "ready"
    assert db.scalar(select(ResearchAlert)).alert_type == "earnings_release"


def test_spanish_cnmv_annual_report(db):
    old = document(db, form="annual_report", period="2025-12-31", number=1,
                   text="Factores de riesgo\nLa dependencia de proveedores puede retrasar la producción anual.")
    new = document(db, form="annual_report", period="2026-12-31", number=2,
                   text="Factores de riesgo\nLa dependencia de proveedores puede retrasar la producción y ventas.")
    old.source_type = new.source_type = "CNMV"
    old.source_url = "https://www.cnmv.es/documento1.pdf"
    new.source_url = "https://www.cnmv.es/documento2.pdf"
    db.commit()
    assert analyze_document(db, new)["status"] == "changed"


def test_large_document_is_saved_as_insufficient_data(db, monkeypatch):
    monkeypatch.setattr("app.services.filing_intelligence.MAX_CHUNKS", 1)
    doc = document(db, form="8-K", text=RELEASE)
    db.add(DocumentChunk(document_id=doc.id, chunk_index=1, text=RELEASE))
    db.commit()
    assert analyze_document(db, doc)["status"] == "insufficient_data"
    assert doc.metadata_[KEY]["status"] == "insufficient_data"


def test_oversized_section_not_treated_as_complete():
    huge = "Item 1A. Risk Factors\n" + "\n".join(
        f"Risk number {i} may affect future business performance." for i in range(5001)
    )
    result = compare_sections(chunks(huge), chunks(huge))
    assert result["sections"][0]["status"] == "insufficient_data"


def test_real_html_parser_and_long_chunker_preserve_sec_sections():
    from app.services.document_ingestion_service import DocumentIngestionService

    service = DocumentIngestionService()

    def parse_html(risk):
        body = ("<div><b><span>Item </span><span>1A.</span></b> <span>Risk Factors</span></div>"
                + "".join(f"<p>{risk} Risk detail number {i} may affect revenue and production.</p>" for i in range(60))
                + "<div><b>Item </b><span>2.</span> <span>Properties</span></div>"
                + "<p>Our buildings outside the risk section should never appear as risks.</p>")
        parsed = service._parse_html(body.encode())
        raw_chunks = service._chunk_blocks(parsed.blocks, "hash", parsed.parser, "sec.htm", "https://www.sec.gov/")
        assert len(raw_chunks) > 1
        return [{"id": i + 1, "chunk_index": i, "text": c["text"]} for i, c in enumerate(raw_chunks)]

    old, new = parse_html("Our supplier concentration can delay launch."), parse_html("Our single supplier can delay launch.")
    result = compare_sections(new, old)
    risk = result["sections"][0]
    assert risk["status"] == "changed"
    assert "Our single supplier" in str(risk)
    assert "buildings" not in str(risk)
    assert "Properties" not in str(risk)
