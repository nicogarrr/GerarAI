"""8-K digest: apartados declarados cuando no hay texto completo (F359)."""
from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import Company, Document, Tenant, WatchItem
from app.services.eight_k_digest import declared_items, eight_k_digest


def _db() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    db.add(Tenant(id=1, external_id="k8-test", name="K8 test"))
    db.flush()
    db.info["tenant_id"] = 1
    db.add(Company(id=1, ticker="INTC", name="Intel", exchange="NASDAQ",
                   company_type="large_cap", valuation_model="dcf"))
    db.add(WatchItem(symbol="INTC", company="Intel"))
    db.flush()
    return db


def _document(metadata: dict) -> Document:
    return Document(
        company_id=1,
        title="8-K presentado ante la SEC",
        source_type="SEC",
        source_url="https://www.sec.gov/Archives/edgar/data/50863/000005086325000123/intc-20251015.htm",
        published_at=datetime(2026, 10, 15, tzinfo=UTC),
        checksum="abc123",
        metadata_=metadata,
    )


def test_declared_items_parse_codes_with_official_titles():
    doc = _document({"form": "8-K", "items": "2.02, 9.01, 2.02"})
    items = declared_items(doc)
    assert [i["code"] for i in items] == ["2.02", "9.01"]
    assert items[0]["title"] == "Resultados de operaciones y situación financiera"
    assert items[0]["excerpts"] == []


def test_declared_items_ignore_missing_or_foreign_metadata():
    assert declared_items(_document({"form": "8-K"})) == []
    assert declared_items(_document({"form": "10-Q", "items": None})) == []


def test_digest_shows_declared_items_when_full_text_missing():
    db = _db()
    db.add(_document({"form": "8-K", "items": "2.02, 9.01"}))
    db.commit()
    result = eight_k_digest(db)
    assert result["status"] == "ready"
    entry = result["items"][0]
    assert entry["status"] == "insufficient_data"
    assert [i["code"] for i in entry["items"]] == ["2.02", "9.01"]
    assert entry["items"][0]["title"] == "Resultados de operaciones y situación financiera"
    assert "declarados ante la SEC" in entry["reason"]


def test_digest_without_declared_items_keeps_plain_reason():
    db = _db()
    db.add(_document({"form": "8-K"}))
    db.commit()
    entry = eight_k_digest(db)["items"][0]
    assert entry["items"] == []
    assert entry["reason"] == "Sin texto completo disponible; revisa el documento oficial."
