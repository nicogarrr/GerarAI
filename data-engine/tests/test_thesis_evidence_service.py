"""ThesisEvidenceService contract tests.

Thesis evidence is the raw material of professional theses: SEC annual
facts must prefer 10-K over 10-Q, market data must land dated and
sourced, and refresh passes must never duplicate rows or cross tenant
boundaries.
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.models.entities import (
    Base,
    Company,
    Document,
    FinancialFact,
    MarketPrice,
)
from app.services.thesis_evidence_service import ThesisEvidenceService


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _company(db: Session, *, name: str = "") -> Company:
    company = Company(
        ticker="AAPL", name=name, exchange="", currency="USD",
        sector="Tech", industry="Tech", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


def _gaap(entries_by_tag: dict[str, list[dict]]) -> dict:
    return {tag: {"units": {"USD": entries}} for tag, entries in entries_by_tag.items()}


# -- SEC annual extraction ----------------------------------------------------

def test_extract_latest_annual_prefers_10k_over_newer_10q():
    us_gaap = _gaap(
        {
            "Revenues": [
                {"form": "10-K", "val": 100, "start": "2024-09-28", "end": "2025-09-27", "filed": "2025-11-01"},
                {"form": "10-Q", "val": 30, "end": "2026-06-27", "filed": "2026-08-01"},
            ]
        }
    )
    out = ThesisEvidenceService()._extract_latest_annual(us_gaap)
    assert out["revenue"]["value"] == 100
    assert out["revenue"]["period"] == "2025-09-27:FY"
    assert out["revenue"]["fiscal_year"] == 2025
    assert out["revenue"]["fiscal_quarter"] == "FY"
    assert out["revenue"]["concept"] == "Revenues"


def test_extract_latest_annual_falls_back_to_latest_quarter():
    us_gaap = _gaap(
        {
            "Assets": [
                {"form": "10-Q", "val": 10, "end": "2026-03-28", "filed": "2026-05-01"},
                {"form": "10-Q", "val": 12, "end": "2026-06-27", "filed": "2026-08-01"},
            ]
        }
    )
    out = ThesisEvidenceService()._extract_latest_annual(us_gaap)
    assert out["total_assets"]["value"] == 12
    assert out["total_assets"]["period"] == "2026-06-27:10-Q"
    assert out["total_assets"]["fiscal_quarter"] is None


def test_extract_latest_annual_first_tag_wins_never_sums():
    us_gaap = _gaap(
        {
            "Revenues": [{"form": "10-K", "val": 100, "end": "2025-09-27", "filed": "2025-11-01"}],
            "SalesRevenueNet": [{"form": "10-K", "val": 90, "end": "2025-09-27", "filed": "2025-11-01"}],
        }
    )
    out = ThesisEvidenceService()._extract_latest_annual(us_gaap)
    assert out["revenue"]["value"] == 100
    assert out["revenue"]["concept"] == "Revenues"


def test_extract_latest_annual_prefers_current_tag_over_stale_preferred_tag():
    """F133 (MSFT tenant 5): "Revenues" dejo de informarse tras FY2010 y
    el extractor lo elegia por preferencia, dejando FY2010 como "Latest
    Results" aunque RevenueFromContract... tenia FY2026."""
    us_gaap = _gaap(
        {
            "Revenues": [
                {
                    "form": "10-K",
                    "val": 62484000000,
                    "start": "2009-07-01",
                    "end": "2010-06-30",
                    "filed": "2010-07-30",
                },
            ],
            "RevenueFromContractWithCustomerExcludingAssessedTax": [
                {
                    "form": "10-K",
                    "val": 331839000000,
                    "start": "2025-07-01",
                    "end": "2026-06-30",
                    "filed": "2026-07-29",
                },
            ],
        }
    )
    out = ThesisEvidenceService()._extract_latest_annual(us_gaap)
    assert out["revenue"]["value"] == 331839000000
    assert out["revenue"]["concept"] == "RevenueFromContractWithCustomerExcludingAssessedTax"
    assert out["revenue"]["period"] == "2026-06-30:FY"


def test_extract_latest_annual_excludes_quarter_republished_in_10k():
    """F133: el 10-K republica trimestres; un Q4 (start 2010-04-01,
    16.039B - el valor exacto que prod guardo como "FY2010") no es un
    dato anual aunque venga con form 10-K."""
    us_gaap = _gaap(
        {
            "Revenues": [
                {
                    "form": "10-K",
                    "val": 62484000000,
                    "start": "2009-07-01",
                    "end": "2010-06-30",
                    "filed": "2010-07-30",
                },
                {
                    "form": "10-K",
                    "val": 16039000000,
                    "start": "2010-04-01",
                    "end": "2010-06-30",
                    "filed": "2010-07-30",
                },
            ]
        }
    )
    out = ThesisEvidenceService()._extract_latest_annual(us_gaap)
    assert out["revenue"]["value"] == 62484000000
    assert out["revenue"]["fiscal_year"] == 2010


def test_extract_latest_annual_q4_only_in_10k_is_not_labeled_fy():
    """Auditor F133: si el tag SOLO tiene un Q4 republicado en 10-K, el
    fallback no puede volver a etiquetarlo FY."""
    us_gaap = _gaap(
        {
            "Revenues": [
                {
                    "form": "10-K",
                    "val": 16039000000,
                    "start": "2010-04-01",
                    "end": "2010-06-30",
                    "filed": "2010-07-30",
                },
            ]
        }
    )
    out = ThesisEvidenceService()._extract_latest_annual(us_gaap)
    assert out["revenue"]["period"] == "2010-06-30:10-K"
    assert out["revenue"]["fiscal_quarter"] is None


def test_extract_latest_annual_annual_beats_newer_quarter_across_tags():
    """Auditor F133: un anual valido en un tag gana a un trimestre mas
    reciente de otro tag."""
    us_gaap = _gaap(
        {
            "Revenues": [
                {
                    "form": "10-K",
                    "val": 245122000000,
                    "start": "2023-07-01",
                    "end": "2024-06-30",
                    "filed": "2024-07-30",
                },
            ],
            "RevenueFromContractWithCustomerExcludingAssessedTax": [
                {
                    "form": "10-Q",
                    "val": 90000000000,
                    "start": "2026-04-01",
                    "end": "2026-06-30",
                    "filed": "2026-07-29",
                },
            ],
        }
    )
    out = ThesisEvidenceService()._extract_latest_annual(us_gaap)
    assert out["revenue"]["value"] == 245122000000
    assert out["revenue"]["concept"] == "Revenues"
    assert out["revenue"]["period"] == "2024-06-30:FY"


def test_extract_latest_annual_amendment_does_not_displace_newer_period():
    """Auditor F133: una enmienda (filed reciente) de un periodo antiguo
    no desplaza al periodo mas reciente: se elige por periodo cubierto."""
    us_gaap = _gaap(
        {
            "Revenues": [
                {
                    "form": "10-K",
                    "val": 100,
                    "start": "2023-01-01",
                    "end": "2023-12-31",
                    "filed": "2026-03-01",
                },
                {
                    "form": "10-K",
                    "val": 200,
                    "start": "2025-01-01",
                    "end": "2025-12-31",
                    "filed": "2026-02-01",
                },
            ]
        }
    )
    out = ThesisEvidenceService()._extract_latest_annual(us_gaap)
    assert out["revenue"]["value"] == 200
    assert out["revenue"]["period"] == "2025-12-31:FY"


def test_extract_latest_annual_flow_without_start_is_not_annual():
    """Auditor F133: una metrica de flujo sin start no puede probar
    duracion anual; una instantanea sin start si."""
    us_gaap = _gaap(
        {
            "Revenues": [
                {"form": "10-K", "val": 100, "end": "2025-12-31", "filed": "2026-02-01"},
            ],
            "Assets": [
                {"form": "10-K", "val": 500, "end": "2025-12-31", "filed": "2026-02-01"},
            ],
        }
    )
    out = ThesisEvidenceService()._extract_latest_annual(us_gaap)
    assert out["revenue"]["period"] == "2025-12-31:10-K"
    assert out["revenue"]["fiscal_quarter"] is None
    assert out["total_assets"]["period"] == "2025-12-31:FY"
    assert out["total_assets"]["fiscal_quarter"] == "FY"


def test_extract_latest_annual_skips_entries_without_value_or_end():
    us_gaap = _gaap(
        {
            "NetIncomeLoss": [
                {"form": "10-K", "val": None, "end": "2025-09-27", "filed": "2025-11-01"},
                {"form": "10-K", "val": 42, "filed": "2025-11-01"},
            ]
        }
    )
    assert ThesisEvidenceService()._extract_latest_annual(us_gaap) == {}


# -- Finnhub market ingest -----------------------------------------------------

def _stub_market(service, quote=None, profile=None, quote_exc=None):
    if quote_exc is not None:
        service._fetch_quote = lambda ticker: (_ for _ in ()).throw(quote_exc)
    else:
        service._fetch_quote = lambda ticker: quote
    service._fetch_profile = lambda ticker: profile


def test_ingest_market_persists_dated_sourced_price_and_market_cap(db):
    company = _company(db, name="AAPL")
    service = ThesisEvidenceService()
    friday = datetime(2026, 9, 25, 20, 0, tzinfo=UTC)  # viernes de mercado
    _stub_market(
        service,
        quote={"c": 190.5, "t": int(friday.timestamp()), "v": 12345},
        profile={"name": "Apple Inc.", "marketCapitalization": 2900.0, "exchange": "NASDAQ"},
    )
    result = service._ingest_market(db, company)
    db.commit()

    assert result["status"] == "ok"
    assert result["price"] == 190.5
    assert result["price_as_of"] == "2026-09-25"
    # La barra se fecha con el timestamp del proveedor, no con el dia de la
    # ingesta: una ingesta de domingo escribe la barra del viernes.
    price_row = db.scalar(
        select(MarketPrice).where(
            MarketPrice.company_id == company.id, MarketPrice.date == friday.date()
        )
    )
    assert price_row is not None
    assert price_row.close == Decimal("190.5")
    assert price_row.volume == 12345
    # Spot no es barra ajustada: la fila nueva no afirma ajuste.
    assert price_row.adj_close is None
    assert price_row.source == "Finnhub"
    assert db.scalar(
        select(func.count()).select_from(MarketPrice).where(
            MarketPrice.company_id == company.id
        )
    ) == 1

    cap = db.scalar(
        select(FinancialFact).where(
            FinancialFact.company_id == company.id,
            FinancialFact.metric == "market_cap",
        )
    )
    assert cap is not None
    # Finnhub reports millions of USD; the fact stores full USD.
    assert cap.value == Decimal("2900000000")
    assert cap.source_type == "Finnhub"
    assert cap.confidence == Decimal("0.75")
    # Fechado con la sesion del proveedor (viernes), no con el dia de ingesta.
    assert cap.period == "2026-09-25"

    # Placeholder name (== ticker) and empty exchange get filled from profile.
    assert company.name == "Apple Inc."
    assert company.exchange == "NASDAQ"


def test_ingest_market_without_quote_keeps_honest_pending_state(db):
    company = _company(db)
    service = ThesisEvidenceService()
    _stub_market(service, quote_exc=RuntimeError("no key"), profile=None)
    result = service._ingest_market(db, company)
    db.commit()

    assert result["status"] == "pending"
    assert "detail" in result
    assert db.scalar(
        select(func.count())
        .select_from(MarketPrice)
        .where(MarketPrice.company_id == company.id)
    ) == 0


def test_ingest_market_is_idempotent_within_a_day(db):
    company = _company(db)
    service = ThesisEvidenceService()
    friday = int(datetime(2026, 9, 25, 20, 0, tzinfo=UTC).timestamp())
    _stub_market(
        service,
        quote={"c": 190.5, "t": friday},
        profile={"name": "Apple Inc.", "marketCapitalization": 2900.0, "exchange": "NASDAQ"},
    )
    service._ingest_market(db, company)
    _stub_market(service, quote={"c": 191.0, "t": friday}, profile={"marketCapitalization": 2900.0})
    service._ingest_market(db, company)
    db.commit()

    rows = db.scalars(
        select(MarketPrice).where(MarketPrice.company_id == company.id)
    ).all()
    assert len(rows) == 1
    assert rows[0].close == Decimal("191.0")
    assert rows[0].date == datetime(2026, 9, 25, 20, 0, tzinfo=UTC).date()
    assert rows[0].close == Decimal("191.0")
    assert db.scalar(
        select(func.count())
        .select_from(FinancialFact)
        .where(
            FinancialFact.company_id == company.id,
            FinancialFact.metric == "market_cap",
        )
    ) == 1


# -- document dedupe + tenant-scoped fact replacement --------------------------

def test_get_or_create_document_is_idempotent(db):
    company = _company(db)
    service = ThesisEvidenceService()
    first = service._get_or_create_document(
        db, company, title="10-K 2025", source_type="SEC", source_url="https://sec.gov/x"
    )
    second = service._get_or_create_document(
        db, company, title="10-K 2025", source_type="SEC", source_url="https://sec.gov/x"
    )
    db.commit()
    assert first.id == second.id
    assert second.metadata_["auto_ingested"] is True
    assert db.scalar(
        select(func.count()).select_from(Document).where(Document.company_id == company.id)
    ) == 1


def test_replace_facts_scoped_to_source_type_and_tenant(db):
    company = _company(db)
    today = datetime.now(UTC).date().isoformat()

    def _fact(metric, source_type, tenant_id):
        return FinancialFact(
            company_id=company.id, metric=metric, value=Decimal("1"), unit="USD",
            period=today, source_type=source_type, is_reported=True,
            confidence=Decimal("0.5"), tenant_id=tenant_id,
        )

    db.add(_fact("revenue", "SEC", "tenant-test"))
    db.add(_fact("assets", "Finnhub", "tenant-test"))
    db.flush()

    # Cross-tenant rows cannot be written from a tenant-scoped session
    # (the before_flush hook forbids it), so seed the other tenant's fact
    # through a separate tenant-less session, as a different tenant's own
    # connection would.
    engine = db.get_bind()
    with Session(engine) as other_db:
        other_db.add(_fact("revenue", "SEC", "other-tenant"))
        other_db.commit()

    ThesisEvidenceService()._replace_facts(db, company, "SEC")
    db.commit()

    remaining = db.scalars(
        select(FinancialFact).where(FinancialFact.company_id == company.id)
    ).all()
    assert {(f.metric, f.source_type) for f in remaining} == {("assets", "Finnhub")}

    with Session(engine) as verify_db:
        survivor = verify_db.scalar(
            select(FinancialFact).where(
                FinancialFact.company_id == company.id,
                FinancialFact.source_type == "SEC",
            )
        )
    assert survivor is not None
    assert survivor.tenant_id == "other-tenant"


def test_ingest_fundamentals_preserva_historico_sec(db, monkeypatch):
    """El ingest de evidencia NO debe borrar el historico SEC de refresh/sec:
    solo rellena el ultimo anual cuando falta (bug: borraba todo y dejaba
    1 ano por metrica, rompiendo el DCF tras cada tesis)."""
    company = _company(db)
    for year in (2023, 2024, 2025):
        db.add(
            FinancialFact(
                company_id=company.id, metric="revenue",
                value=Decimal(str(year)), unit="USD",
                period=f"{year}-12-31:FY", fiscal_year=year,
                source_type="SEC", is_reported=True, confidence=Decimal("0.95"),
            )
        )
    db.commit()

    service = ThesisEvidenceService()
    monkeypatch.setattr(service, "_fetch_company_facts", lambda cik: {
        "facts": {"us-gaap": _gaap({
            "Revenues": [
                {"form": "10-K", "val": 999, "start": "2025-01-01", "end": "2025-12-31", "fy": "2025", "fp": "FY", "filed": "2026-02-01"},
            ],
        })},
    })

    result = service._ingest_fundamentals(db, company, "0000320193")
    assert result["status"] == "ok"

    periods = {
        f.period
        for f in db.scalars(
            select(FinancialFact).where(
                FinancialFact.company_id == company.id,
                FinancialFact.source_type == "SEC",
                FinancialFact.metric == "revenue",
            )
        )
    }
    assert periods == {"2023-12-31:FY", "2024-12-31:FY", "2025-12-31:FY"}


def test_ingest_market_quote_sin_timestamp_no_fabrica_barra(db):
    """Sin timestamp del proveedor no hay fecha honesta: no se escribe nada.

    Adversarial: con el codigo viejo la quote se fechaba con el dia de la
    ingesta y aparecia una barra de hoy (domingo si hoy es domingo).
    """
    company = _company(db)
    service = ThesisEvidenceService()
    _stub_market(service, quote={"c": 190.5}, profile={"marketCapitalization": 2900.0})
    result = service._ingest_market(db, company)
    db.commit()

    assert result["status"] == "pending"
    assert "timestamp" in result["detail"]
    assert db.scalar(
        select(func.count()).select_from(MarketPrice).where(
            MarketPrice.company_id == company.id
        )
    ) == 0


def test_ingest_market_quote_fecha_futura_rechazada(db):
    company = _company(db)
    service = ThesisEvidenceService()
    future = datetime.now(UTC).timestamp() + 3 * 86400
    _stub_market(service, quote={"c": 190.5, "t": int(future)}, profile=None)
    result = service._ingest_market(db, company)
    db.commit()

    assert result["status"] == "pending"
    assert "futura" in result["detail"]
    assert db.scalar(
        select(func.count()).select_from(MarketPrice).where(
            MarketPrice.company_id == company.id
        )
    ) == 0


def test_ingest_market_quote_sin_volumen_deja_null_no_cero(db):
    friday = int(datetime(2026, 9, 25, 20, 0, tzinfo=UTC).timestamp())
    company = _company(db)
    service = ThesisEvidenceService()
    _stub_market(service, quote={"c": 190.5, "t": friday}, profile=None)
    service._ingest_market(db, company)
    db.commit()

    row = db.scalar(select(MarketPrice).where(MarketPrice.company_id == company.id))
    assert row is not None
    assert row.volume is None


def test_ingest_market_spot_no_pisa_adjusted_autentico(db):
    """La via OHLCV sembro una barra con adjusted real; una ingesta spot del
    mismo dia actualiza el close y no toca adj_close ni OHLC."""
    friday = datetime(2026, 9, 25, 20, 0, tzinfo=UTC)
    company = _company(db)
    db.add(
        MarketPrice(
            company_id=company.id,
            date=friday.date(),
            open=Decimal("185.0"),
            high=Decimal("191.0"),
            low=Decimal("184.0"),
            close=Decimal("189.0"),
            adj_close=Decimal("181.75"),
            volume=50000,
            source="Finnhub",
        )
    )
    db.flush()
    service = ThesisEvidenceService()
    _stub_market(
        service,
        quote={"c": 190.5, "t": int(friday.timestamp())},
        profile=None,
    )
    service._ingest_market(db, company)
    db.commit()

    rows = db.scalars(select(MarketPrice).where(MarketPrice.company_id == company.id)).all()
    assert len(rows) == 1
    row = rows[0]
    assert row.close == Decimal("190.5")
    assert row.adj_close == Decimal("181.75")
    assert row.open == Decimal("185.0")
    assert row.high == Decimal("191.0")
    assert row.low == Decimal("184.0")
    assert row.volume == 50000


def test_ingest_market_quote_malformada_no_propaga_excepcion(db):
    company = _company(db)
    service = ThesisEvidenceService()
    _stub_market(service, quote={"c": 190.5, "t": "no-es-un-numero"}, profile=None)
    result = service._ingest_market(db, company)
    db.commit()

    assert result["status"] == "pending"
    assert "timestamp" in result["detail"]
    assert db.scalar(
        select(func.count()).select_from(MarketPrice).where(
            MarketPrice.company_id == company.id
        )
    ) == 0


def test_collect_earnings_error_no_expone_detalle_interno(db):
    company = _company(db)
    service = ThesisEvidenceService()

    def boom():
        raise RuntimeError("Task <Task pending name='x' coro=<_fetch_day_pooled() at earnings_calendar.py:198>>")

    service._fetch_earnings = boom
    result = service._collect_earnings(db, company)
    text = str(result)
    assert "Calendario de resultados inaccesible ahora mismo." in text
    assert "RuntimeError" not in text
    assert "_fetch_day_pooled" not in text
    assert "earnings_calendar.py" not in text


def test_ingest_market_sin_timestamp_no_escribe_market_cap(db):
    company = _company(db)
    service = ThesisEvidenceService()
    _stub_market(service, quote={"c": 190.5}, profile={"marketCapitalization": 2900.0})
    service._ingest_market(db, company)
    db.commit()

    assert db.scalar(
        select(func.count()).select_from(FinancialFact).where(
            FinancialFact.company_id == company.id,
            FinancialFact.metric == "market_cap",
        )
    ) == 0


@pytest.mark.parametrize("adjusted", [None, Decimal("4200")])
def test_market_rejected_unitless_spot_does_not_publish_ok(db, adjusted):
    company = _company(db)
    company.ticker = "CGEO.L"
    company.currency = "GBP"
    friday = datetime(2026, 9, 25, 20, tzinfo=UTC)
    bar = MarketPrice(company_id=company.id, date=friday.date(), open=4200, high=4300, low=4150,
                      close=4255, adj_close=adjusted, quote_currency="GBX", source="yfinance")
    db.add(bar)
    db.commit()
    service = ThesisEvidenceService()
    _stub_market(service, quote={"c": 42.55, "t": int(friday.timestamp())}, profile=None)
    result = service._ingest_market(db, company)
    assert result["status"] == "unknown_price_unit"
    assert "price" not in result
    assert (bar.open, bar.high, bar.low, bar.close) == (4200, 4300, 4150, 4255)
    assert bar.quote_currency == "GBX"
