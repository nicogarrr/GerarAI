from contextlib import contextmanager
from decimal import Decimal
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import delete, or_, select

import main
from app.core.database import SessionLocal, get_db, init_db
from app.models import Company, ExternalClaim, NewsEvent, Position, Tenant, ThesisChange
from app.services.source_hierarchy_service import classify_source

TARGET_TICKER = "MATBIG"
OTHER_TICKER = "MATOTH"
# Simula lo que otros tests del mismo worker de xdist dejan en la base de la
# sesion: una posicion en otra divisa y sin valor en base. Con ella el peso
# global se rompia (los dos tests de peso fallaban solo en paralelo).
LEFTOVER_TICKER = "MATLEFT"


def cleanup_materiality_artifacts() -> None:
    init_db()
    db = SessionLocal()
    try:
        companies = db.scalars(select(Company).where(Company.ticker.in_([TARGET_TICKER, OTHER_TICKER, LEFTOVER_TICKER]))).all()
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


@contextmanager
def own_tenant():
    """Tenant propio para el test: el peso de materialidad suma las posiciones
    del tenant (todas sus carteras, igual que la pagina de cartera, Cerebro y
    el panel de la ficha), asi que solo lo que crea el test entra en la cuenta.
    Devuelve una fabrica de sesiones de ese tenant y enruta la API a el."""
    init_db()
    with SessionLocal() as db:
        tenant = Tenant(external_id=f"materiality-{uuid4().hex[:12]}", name="materiality test")
        db.add(tenant)
        db.commit()
        tenant_id = tenant.id

    def session():
        db = SessionLocal()
        db.info["tenant_id"] = tenant_id
        return db

    def override():
        db = session()
        try:
            yield db
        finally:
            db.close()

    main.app.dependency_overrides[get_db] = override
    try:
        yield session
    finally:
        main.app.dependency_overrides.pop(get_db, None)
        cleanup_materiality_artifacts()
        with SessionLocal() as db:
            db.execute(delete(Tenant).where(Tenant.id == tenant_id))
            db.commit()


def leave_foreign_position_behind() -> None:
    """Posicion sin tenant (como las de otros tests legacy), en EUR y sin valor en base."""
    db = SessionLocal()
    try:
        company = create_company(db, LEFTOVER_TICKER, "Materiality Leftover")
        db.add(Position(
            company_id=company.id, quantity=Decimal("1"), average_cost=Decimal("1"),
            market_price=Decimal("1"), market_value=Decimal("90000000000000"),
            unrealized_pnl=Decimal("0"), currency="EUR", base_currency="EUR",
            source="test_materiality",
        ))
        db.commit()
    finally:
        db.close()


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
    leave_foreign_position_behind()
    with own_tenant() as tenant_session:
        db = tenant_session()
        try:
            target = create_company(db, TARGET_TICKER, "Materiality Target")
            other = create_company(db, OTHER_TICKER, "Materiality Other")
            create_position(db, target, "600000000000")
            create_position(db, other, "400000000000")
            db.commit()
        finally:
            db.close()
        _assert_news_materiality(TestClient(main.app))


def _assert_news_materiality(client) -> None:
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


def test_source_hierarchy_classifies_regulatory_urls_as_highest_tier():
    tier = classify_source("feed", "https://www.sec.gov/Archives/edgar/data/example")
    assert tier.key == "tier_1_regulatory"
    assert tier.trust_score == 1.0


def test_source_tier_catalog_is_exactly_the_known_nine():
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
        "tier_8_social",
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


def test_portfolio_weight_convierte_a_divisa_base_con_divisas_mezcladas():
    """Peso de una acción japonesa: 2.000.000 JPY (12.000 € en base) frente a
    100.000 € de otra posición. A mano: 12.000 / 112.000 = 10,71 %
    (ajuste de materialidad +1). Antes se sumaban JPY y EUR como la misma
    unidad: 2.000.000 / 2.100.000 = 95,2 % (ajuste +2)."""
    from app.services.materiality_service import MaterialityService

    cleanup_materiality_artifacts()
    leave_foreign_position_behind()
    with own_tenant() as tenant_session:
        _assert_mixed_currency_weight(tenant_session(), MaterialityService())


def _assert_mixed_currency_weight(db, service) -> None:
    try:
        target = create_company(db, TARGET_TICKER, "Materiality Target")
        other = create_company(db, OTHER_TICKER, "Materiality Other")
        db.add(Position(
            company_id=target.id, quantity=Decimal("100"), average_cost=Decimal("20000"),
            market_price=Decimal("20000"), market_value=Decimal("2000000"),
            unrealized_pnl=Decimal("0"), currency="JPY", base_currency="EUR",
            market_value_base=Decimal("12000"), source="test_materiality",
        ))
        db.add(Position(
            company_id=other.id, quantity=Decimal("1000"), average_cost=Decimal("100"),
            market_price=Decimal("100"), market_value=Decimal("100000"),
            unrealized_pnl=Decimal("0"), currency="EUR", base_currency="EUR",
            source="test_materiality",
        ))
        db.commit()
        weight = service.portfolio_weight(db, target)
        assert abs(weight - 12000 / 112000) < 1e-9
        assert service._portfolio_adjustment(weight) == 1
    finally:
        db.close()


def test_trade_resumption_does_not_inherit_halt_criticality():
    """Repro prod 28-oct-2026: «Canadian Investment Regulatory Organization
    Trade Resumption - BN.PF.N» salía 10/10 negativo con aviso de tesis por
    heredar «halt» del cuerpo del aviso. La reanudación no es un halt."""
    from app.core.database import SessionLocal, init_db
    from app.services.materiality_service import MaterialityService

    init_db()
    db = SessionLocal()
    try:
        service = MaterialityService()
        resumption = service.assess_news(
            db,
            None,
            "Canadian Investment Regulatory Organization Trade Resumption - "
            "BN.PF.N. Trading resumes in the shares after the trading halt.",
            "company_ir",
            "https://example.com/resumption",
            use_jev=False,
        )
        assert resumption.materiality_score < 10
        assert resumption.impact_direction == "neutral"

        halt = service.assess_news(
            db,
            None,
            "Canadian Investment Regulatory Organization Trading Halt - "
            "BN.PF.N pending material news.",
            "company_ir",
            "https://example.com/halt",
            use_jev=False,
        )
        assert halt.materiality_score == 10
        assert halt.impact_direction == "negative"
    finally:
        db.close()


def test_mainstream_news_sources_are_not_tier_unknown():
    """Repro prod 28-oct-2026: Stock Titan, MarketBeat o el Financial Times
    salían como fuente desconocida (confianza 0,25) cuando son medios
    habituales de la ingesta."""
    for source in ("Stock Titan", "MarketBeat", "Seeking Alpha", "GlobeNewswire"):
        tier = classify_source(source, "https://news.google.com/rss/articles/xyz")
        assert tier.key == "tier_5_data_provider", source
        assert tier.trust_score == 0.68
    ft = classify_source("Financial Times", "https://news.google.com/rss/articles/xyz")
    assert ft.key == "tier_4_reputable_media"
    # Lo genuinamente desconocido sigue en tier_unknown.
    assert classify_source("KuCoin", "https://kucoin.com/news/x").key == "tier_unknown"
    assert classify_source("Random Blog", "https://blog.example.com/x").key == "tier_unknown"
