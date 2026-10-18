from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import delete, or_, select

import main
from app.core.database import SessionLocal, init_db
from app.models import Company, ExternalClaim, NewsEvent, Position, ThesisChange
from app.services.source_hierarchy_service import classify_source

TARGET_TICKER = "MATBIG"
OTHER_TICKER = "MATOTH"


def cleanup_materiality_artifacts() -> None:
    init_db()
    db = SessionLocal()
    try:
        companies = db.scalars(select(Company).where(Company.ticker.in_([TARGET_TICKER, OTHER_TICKER]))).all()
        company_ids = [company.id for company in companies]
        if company_ids:
            news_events = db.scalars(select(NewsEvent).where(NewsEvent.company_id.in_(company_ids))).all()
            summaries = [event.summary for event in news_events if event.summary]
            if summaries:
                db.execute(delete(ExternalClaim).where(ExternalClaim.claim.in_(summaries)))
            db.execute(delete(ThesisChange).where(ThesisChange.company_id.in_(company_ids)))
            db.execute(delete(NewsEvent).where(NewsEvent.company_id.in_(company_ids)))
            db.execute(delete(Position).where(Position.company_id.in_(company_ids)))
        db.execute(
            delete(ExternalClaim).where(
                or_(
                    ExternalClaim.claim.like(f"%{TARGET_TICKER}%"),
                    ExternalClaim.claim.like(f"%{OTHER_TICKER}%"),
                )
            )
        )
        for company in companies:
            db.delete(company)
        db.commit()
    finally:
        db.close()


def create_company(db, ticker: str, name: str) -> Company:
    company = Company(
        ticker=ticker,
        name=name,
        exchange="TEST",
        currency="USD",
        sector="Software",
        industry="Application Software",
        company_type="standard",
        valuation_model="standard_dcf",
        special_sources=[],
        special_risks=[],
        factor_tags=[],
    )
    db.add(company)
    db.flush()
    return company


def create_position(db, company: Company, market_value: str) -> None:
    db.add(
        Position(
            company_id=company.id,
            quantity=Decimal("10"),
            average_cost=Decimal("10"),
            market_price=Decimal("10"),
            market_value=Decimal(market_value),
            unrealized_pnl=Decimal("0"),
            currency="USD",
            source="test_materiality",
        )
    )


def test_news_materiality_uses_portfolio_weight_and_source_hierarchy():
    cleanup_materiality_artifacts()
    db = SessionLocal()
    try:
        target = create_company(db, TARGET_TICKER, "Materiality Target")
        other = create_company(db, OTHER_TICKER, "Materiality Other")
        create_position(db, target, "600000000000")
        create_position(db, other, "400000000000")
        db.commit()
    finally:
        db.close()

    client = TestClient(main.app)
    response = client.post(
        "/api/news/manual",
        json={
            "text": (
                f"Materiality Target ({TARGET_TICKER}) reports earnings "
                "and updates guidance after a margin miss."
            ),
            "source": "company_ir",
            "url": "https://ir.example.com/news",
        },
    )
    assert response.status_code == 200
    payload = response.json()

    assert payload["requires_update"] is True
    assert payload["materiality_score"] >= 7
    assert payload["source_tier"] == "tier_2_company"
    assert payload["portfolio_weight"] >= 0.55
    assert payload["model_route"] == "deep_thesis"
    assert any("portfolio_weight=" in reason for reason in payload["materiality_reasons"])

    events = client.get("/api/news")
    assert events.status_code == 200
    event = next(item for item in events.json() if item["ticker"] == TARGET_TICKER)
    assert event["source_tier"] == "tier_2_company"
    assert event["portfolio_weight"] >= 0.55
    assert event["materiality_reasons"]

    cleanup_materiality_artifacts()


def test_source_hierarchy_classifies_regulatory_urls_as_highest_tier():
    tier = classify_source("feed", "https://www.sec.gov/Archives/edgar/data/example")
    assert tier.key == "tier_1_regulatory"
    assert tier.trust_score == 1.0


def test_source_tier_catalog_is_exactly_the_known_eight():
    """Tripwire: si SOURCE_TIERS crece, la etiqueta UI (etiquetaTierFuente en
    lib/labels.ts) debe crecer con él - un tier sin etiqueta se pinta crudo
    en /research/news (F175)."""
    from app.services.source_hierarchy_service import SOURCE_TIERS

    assert sorted(SOURCE_TIERS) == [
        "tier_1_regulatory",
        "tier_2_company",
        "tier_3_transcript",
        "tier_4_reputable_media",
        "tier_5_data_provider",
        "tier_6_bootstrap",
        "tier_7_user_input",
        "tier_unknown",
    ]


def test_event_type_catalog_is_exactly_the_known_six():
    """Tripwire: el backend solo emite event_type desde MATERIAL_KEYWORDS o el
    fallback 'general_news' (MaterialityService.assess_news). Si el catálogo
    crece, la etiqueta UI (etiquetaTipoEvento en lib/labels.ts) debe crecer
    con él - un tipo sin etiqueta se pinta crudo en /research/news (F175)."""
    from pathlib import Path

    from app.services.materiality_service import MATERIAL_KEYWORDS

    assert sorted(MATERIAL_KEYWORDS) == [
        "capital_allocation",
        "contract",
        "dilution",
        "earnings",
        "regulatory",
    ]
    labels_ts = (
        Path(__file__).resolve().parents[2] / "lib" / "labels.ts"
    ).read_text(encoding="utf-8")
    for event_type in [*MATERIAL_KEYWORDS, "general_news"]:
        assert f"{event_type}:" in labels_ts, (
            f"etiquetaTipoEvento no traduce '{event_type}' y se pintaría crudo"
        )
