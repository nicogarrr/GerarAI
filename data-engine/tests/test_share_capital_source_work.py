"""Un documento SEC compartido por muchos hechos se decodifica una vez."""
import json
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import Company, Document, FinancialFact
from app.models.entities import Base
from app.services.share_capital_service import build_share_capital


def test_source_metadata_decoded_once_not_once_per_fact():
    decodes = []

    def counted(raw):
        value = json.loads(raw)
        if isinstance(value, dict) and value.get("fixture_source"):
            decodes.append(len(raw))
        return value

    engine = create_engine("sqlite:///:memory:", json_deserializer=counted)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        company = Company(ticker="TEST", name="Test", exchange="NASDAQ", currency="USD",
                          company_type="holding", valuation_model="unassigned")
        db.add(company)
        db.flush()
        doc = Document(company_id=company.id, title="SEC", source_type="SEC",
                       source_url="https://www.sec.gov/test", metadata_={
                           "fixture_source": True, "unrelated_text": "x" * 100_000,
                           "capital_fact_provenance": {},
                       })
        db.add(doc)
        db.flush()
        for year in range(2000, 2025):
            db.add(FinancialFact(company_id=company.id, source_id=doc.id, metric="shares_outstanding",
                                value=Decimal(100 + year), unit="shares", period=f"{year}-12-31:FY",
                                fiscal_quarter="FY", source_type="SEC", is_reported=True))
        db.flush()
        cid = company.id
        db.expunge_all()
        company = db.get(Company, cid)
        decodes.clear()
        result = build_share_capital(db, company)
        assert len(result["series"]) == 25
        assert all(row["source_url"] == "https://www.sec.gov/test" for row in result["series"])
        assert len(decodes) == 1  # antes25decodificaciones del mismo JSON
        assert sum(decodes) < 101_000  # antes>2,5MB de JSON transferido/parseado
