"""Utilidades compartidas para los tests del backtest point-in-time.

Vive en un modulo aparte (y no en ``conftest.py``, que es compartido) porque
todos los tests de D1 necesitan la misma cosa: una base de datos en memoria con
un tenant, una empresa sembrada y las trampas de look-ahead listas. Cada test
que lo usa sigue siendo plano: importa, siembra, afirma.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

# Imported for the side effect: registers the backtest tables on Base.metadata.
import app.models.thesis_backtest  # noqa: F401
from app.core.database import Base
from app.models import (
    CalculatedMetric,
    Claim,
    ClaimEvidence,
    Company,
    Document,
    FinancialFact,
    MarketPrice,
    Tenant,
    ThesisSection,
    ThesisVersion,
)

TICKER = "AAA"
FY = 2024
FY_PERIOD = "2024-12-31"
#: The trap. Un hecho de un ejercicio que ninguna fecha de corte puede ver.
FUTURE_PERIOD = "2999-12-31"
FUTURE_FY = 2999
FUTURE_VALUE = Decimal("999999")

#: The thesis exists from this date on; anything earlier is "not yet published".
THESIS_DAY = date(2024, 7, 15)
#: FY2024 accounts filed on this date.
FILING_DAY = date(2025, 3, 20)
FUTURE_FILING_DAY = date(2999, 3, 15)
#: The cutoffs the tests replay.
CUTOFF_EARLY = date(2024, 6, 30)
CUTOFF_MID = date(2025, 6, 30)
CUTOFF_LATE = date(2026, 6, 30)

BENCHMARK_TICKER = "^GSPC"

BASE_FACTS: dict[str, float] = {
    "revenue": 1000.0,
    "free_cash_flow": 120.0,
    "net_debt": 300.0,
    "shares_diluted": 100.0,
}


def ts(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, 12, 0, tzinfo=UTC)


def make_session(tenant_external_id: str = "tenant-test") -> Session:
    """A fresh in-memory database with one active tenant, tenant-scoped.

    In-memory rather than the session-wide file the other tests use, so a
    backtest that writes rows can never collide with, or be seen by, another
    test's data.

    ``StaticPool`` + ``check_same_thread=False``: a ``TestClient`` runs the app
    on its own thread, and SQLite's default in-memory pool hands each thread a
    *different* connection, which means a different empty database. Pinning one
    connection for the whole engine is what makes the test client see the rows
    the fixture seeded.
    """
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    tenant = Tenant(external_id=tenant_external_id, name=tenant_external_id, status="active")
    session.add(tenant)
    session.commit()
    session.info["tenant_id"] = tenant.id
    return session


def make_company(
    session: Session,
    *,
    ticker: str = TICKER,
    company_type: str = "industrial",
    valuation_model: str = "standard_dcf",
    factor_tags: list[str] | None = None,
) -> Company:
    company = Company(
        ticker=ticker,
        name=f"Backtest {ticker}",
        exchange="TEST",
        currency="EUR",
        sector="Test",
        industry="Test",
        company_type=company_type,
        valuation_model=valuation_model,
        special_sources=[],
        special_risks=[],
        factor_tags=factor_tags or [],
    )
    session.add(company)
    session.flush()
    return company


def add_accounts(
    session: Session,
    company: Company,
    *,
    fiscal_year: int = FY,
    period: str = FY_PERIOD,
    facts: dict[str, float] | None = None,
    published_at: date = FILING_DAY,
    include_wacc: bool = True,
) -> Document:
    """A dated annual filing: the document plus its facts, or nothing at all.

    ``published_at`` is what makes this a point-in-time test and not a schema
    test: the same numbers filed in 2025 and in 2026 are different facts for a
    replay, even though the period is identical.
    """
    document = Document(
        company_id=company.id,
        title=f"{company.ticker} accounts FY{fiscal_year}",
        source_type="sec_10k",
        source_url=f"https://example.invalid/{company.ticker}/{fiscal_year}",
        published_at=ts(published_at),
    )
    session.add(document)
    session.flush()
    for metric, value in (facts if facts is not None else BASE_FACTS).items():
        unit = "ratio" if abs(value) < 1 else "EUR"
        session.add(
            FinancialFact(
                company_id=company.id,
                metric=metric,
                value=Decimal(str(value)),
                unit=unit,
                period=period,
                fiscal_year=fiscal_year,
                fiscal_quarter="FY",
                source_id=document.id,
                source_type="sec",
                confidence=Decimal("0.92"),
            )
        )
    if include_wacc:
        session.add(
            CalculatedMetric(
                company_id=company.id,
                metric="wacc",
                value=Decimal("0.09"),
                unit="decimal",
                period=f"{fiscal_year}-12-31:FY",
                fiscal_year=fiscal_year,
                status="ok",
                definition_version="WACC_STANDARD_V1",
                formula="ke*E/(D+E) + kd*(1-t)*D/(D+E)",
                # computed before every replay cutoff (PIT filter: created_at <= as_of)
                created_at=datetime(2020, 1, 1, tzinfo=UTC),
            )
        )
    session.flush()
    return document


def add_future_trap(
    session: Session,
    company: Company,
    *,
    metric: str = "revenue",
    published_at: date = FUTURE_FILING_DAY,
) -> None:
    """A fact from FY2999, filed in 2999, with an unambiguous readable period.

    The period is a real ISO date, so nothing about this row is malformed or
    ambiguous: the only thing standing between it and a 2024 valuation is the
    point-in-time filter. That is what makes it a useful trap. The filing date
    is real and also in the future: under the abstention policy a fact without
    one would not be a future trap at all, just an unverifiable row.
    """
    document = Document(
        company_id=company.id,
        title=f"{company.ticker} accounts FY{FUTURE_FY}",
        source_type="sec_10k",
        source_url=f"https://example.invalid/{company.ticker}/{FUTURE_FY}",
        published_at=ts(published_at),
    )
    session.add(document)
    session.flush()
    session.add(
        FinancialFact(
            company_id=company.id,
            metric=metric,
            value=FUTURE_VALUE,
            source_id=document.id,
            unit="EUR",
            period=FUTURE_PERIOD,
            fiscal_year=FUTURE_FY,
            fiscal_quarter="FY",
            source_type="sec",
            confidence=Decimal("0.99"),
        )
    )
    session.flush()


def add_prices(
    session: Session,
    company: Company,
    *,
    start: date = date(2024, 1, 2),
    count: int = 130,
    step_days: int = 7,
    base: float = 12.0,
    drift: float = 0.0009,
    with_adj_close: bool = True,
) -> None:
    for index in range(count):
        day = start + timedelta(days=index * step_days)
        price = Decimal(str(round(base * (1 + index * drift), 4)))
        session.add(
            MarketPrice(
                company_id=company.id,
                date=day,
                close=price,
                adj_close=price if with_adj_close else None,
                source="seed",
            )
        )
    session.flush()


def add_future_price(session: Session, company: Company, *, day: date = date(2030, 1, 2)) -> None:
    session.add(
        MarketPrice(
            company_id=company.id,
            date=day,
            close=Decimal("9999"),
            adj_close=Decimal("9999"),
            source="seed_future_trap",
        )
    )
    session.flush()


def add_benchmark(session: Session, *, ticker: str = BENCHMARK_TICKER) -> Company:
    company = Company(
        ticker=ticker,
        name="S&P 500 (benchmark)",
        exchange="INDEX",
        currency="EUR",
        sector="Index",
        industry="Index",
        company_type="index",
        valuation_model="none",
        special_sources=[],
        special_risks=[],
        factor_tags=[],
    )
    session.add(company)
    session.flush()
    for index in range(130):
        day = date(2024, 1, 2) + timedelta(days=index * 7)
        price = Decimal(str(round(100.0 * (1 + index * 0.0004), 4)))
        session.add(
            MarketPrice(
                company_id=company.id, date=day, close=price, adj_close=price, source="seed"
            )
        )
    session.flush()
    return company


def add_thesis(
    session: Session,
    company: Company,
    *,
    created_at: date = THESIS_DAY,
    version: int = 1,
    statement: str | None = None,
    evidence_published_at: date = FILING_DAY,
) -> ThesisVersion:
    thesis = ThesisVersion(
        company_id=company.id,
        version=version,
        status="published",
        thesis_markdown="# Tesis\nRevenue 1000 grows with a durable margin.",
        executive_summary="Tesis de prueba",
        rating="buy",
        source_coverage_score=90,
        created_at=ts(created_at),
    )
    session.add(thesis)
    session.flush()
    text = statement or f"Revenue {int(BASE_FACTS['revenue'])} grows with a durable margin."
    claim = Claim(
        company_id=company.id,
        thesis_version_id=thesis.id,
        statement=text,
        claim_type="thesis",
        status="verified",
        confidence=Decimal("0.80"),
        materiality_score=8,
        created_at=ts(created_at),
        metadata_={"metric": "revenue"},
    )
    session.add(claim)
    session.flush()
    evidence_doc = Document(
        company_id=company.id,
        title=f"{company.ticker} evidence {version}",
        source_type="sec_10k",
        published_at=ts(evidence_published_at),
    )
    session.add(evidence_doc)
    session.flush()
    session.add(
        ClaimEvidence(
            claim_id=claim.id,
            document_id=evidence_doc.id,
            source_url=f"https://example.invalid/{company.ticker}/ev{version}",
            evidence_type="supports",
            summary="Reported accounts",
            confidence=Decimal("0.85"),
            source_tier="primary",
            created_at=ts(created_at),
        )
    )
    session.flush()
    return thesis


def add_debate(session: Session, thesis: ThesisVersion, *, verdict: str = "neutral", created_at: date = THESIS_DAY) -> None:
    session.add(
        ThesisSection(
            thesis_version_id=thesis.id,
            company_id=thesis.company_id,
            section_key="thesis_debate",
            title="Thesis debate (bull vs bear)",
            body=f"VEREDICTO: {verdict} | evidencia equilibrada",
            status="published",
            order_index=999,
            created_at=ts(created_at),
            metadata_={"verdict": verdict, "model": "deterministic", "degraded": False},
        )
    )
    session.flush()


def seed_company(session: Session, **kwargs) -> Company:
    """A complete, fully public company: accounts, prices, thesis and debate."""
    company = make_company(session, **kwargs)
    add_accounts(session, company)
    add_prices(session, company)
    thesis = add_thesis(session, company)
    add_debate(session, thesis)
    session.commit()
    return company
