"""Bordes de financial_ingestion_service.py (lote A3): metodos con BD.

SQLite real en memoria (patron de tests/test_ingest_service_guards.py), datos
sinteticos, sin red. Cada test llama al metodo aislado del servicio
(precedente: test_ingest_service_guards llama a _add_derived_facts y
test_cb_insurer_sec_metrics inserta FinancialFact a mano). La config de
compania aseguradora replica la de test_cb_insurer_sec_metrics._company
(Chubb): resolve_engine_key la clasifica "insurer" y habilita las derivadas
de equity.

DECLARADA inalcanzable hoy (acotacion estatica; NO aplica fuzz: el espacio
de entrada son los call sites del propio modulo, no datos de un parser):
- 3328 (`add_ratio` devuelve 0 con denominador None/<=0) en
  _derive_esef_metrics: los 5 call sites actuales (fcf_margin, gross_margin,
  operating_margin, net_margin, effective_tax_rate) guardan
  `denominador.value > 0` en la misma iteracion inmediatamente antes de
  llamar. Enumeracion exhaustiva de call sites sobre el codigo de esta
  rama, tablas sin mutar. Si un futuro call site olvida la guarda, la
  linea vuelve a ser alcanzable y habra que testearla.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models.entities import Base, Company, Document, FinancialFact, MarketPrice
from app.services.financial_ingestion_service import FinancialIngestionService


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    with factory() as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _company(db, ticker="ACME", sector="Technology", industry="Software"):
    company = Company(
        ticker=ticker,
        name=ticker,
        exchange="NASDAQ",
        currency="USD",
        sector=sector,
        industry=industry,
        company_type="holding",
        valuation_model="unassigned",
        special_sources=[],
        special_risks=[],
        factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


def _company_aseguradora(db):
    """Misma clasificacion que test_cb_insurer_sec_metrics._company (Chubb):
    resolve_engine_key -> "insurer", habilita roe/book_value_growth. El
    company_type es determinante: "holding" resuelve a holding_company y
    NO derivaria ratios de equity."""
    company = Company(
        ticker="CB",
        name="CB",
        exchange="NYSE",
        currency="USD",
        sector="Financials",
        industry="Insurance - Property & Casualty",
        company_type="research_candidate",
        valuation_model="unassigned",
        special_sources=[],
        special_risks=[],
        factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


def _document(db, company, source_type="SEC"):
    document = Document(company_id=company.id, title="test", source_type=source_type)
    db.add(document)
    db.commit()
    return document


def _fact(db, company, metric, value, *, period, fiscal_year, source_type, is_reported=True):
    fact = FinancialFact(
        company_id=company.id,
        metric=metric,
        value=Decimal(str(value)),
        unit="USD",
        period=period,
        fiscal_year=fiscal_year,
        fiscal_quarter="FY",
        source_type=source_type,
        is_reported=is_reported,
        confidence=Decimal("0.9"),
    )
    db.add(fact)
    db.commit()
    return fact


def _metrics(db, company):
    return sorted(
        f.metric for f in db.scalars(select(FinancialFact).where(FinancialFact.company_id == company.id))
    )


# --- _add_facts (arco 3736->3741: seen=None, sin bloque de dedupe) ---


def test_add_facts_sin_seen_inserta_sin_pasar_por_dedupe(db):
    """Con seen=None la deduplicacion FIX5-4 no aplica (cada fila del payload
    entra tal cual): el arco salta del guard al _drop_stale_derived."""
    company = _company(db)
    document = _document(db, company, source_type="FMP")
    row = {
        "date": "2025-12-31",
        "calendarYear": 2025,
        "period": "FY",
        "revenue": 100,
        "reportedCurrency": "USD",
    }
    specs = [("revenue", "revenue", "USD")]
    count = FinancialIngestionService()._add_facts(db, company, document, row, specs, seen=None)
    assert count == 1
    db.flush()
    fact = db.scalar(
        select(FinancialFact).where(
            FinancialFact.company_id == company.id,
            FinancialFact.metric == "revenue",
        )
    )
    assert fact is not None
    assert fact.value == Decimal("100")
    assert fact.period == "2025-12-31:FY"
    assert fact.is_reported is True


# --- _add_derived_facts (3777 ownership, 3789 sin fiscal_year, 3791->3780) ---


def test_add_derived_facts_salta_sin_ano_y_conserva_la_fila_ya_persistida(db):
    """3789: un hecho FMP-FY sin fiscal_year no entra en el panel. 3791->3780:
    a misma fuente y (metrica, ano), la fila ya persistida (id menor) gana a
    la nueva (ownership: misma prioridad, id mayor pierde)."""
    company = _company(db)
    document = _document(db, company, source_type="FMP")
    _fact(db, company, "revenue", 1, period="2024-12-31:FY", fiscal_year=None, source_type="FMP")
    persistida = _fact(
        db, company, "revenue", 100, period="2024-12-31:FY", fiscal_year=2024, source_type="FMP"
    )
    _fact(db, company, "revenue", 999, period="2024-12-31:FY", fiscal_year=2024, source_type="FMP")
    derived = FinancialIngestionService()._add_derived_facts(db, company, document)
    # revenue sola no deriva ningun par: nada nuevo, y ninguna fila tocada.
    assert derived == 0
    assert _metrics(db, company) == ["revenue", "revenue", "revenue"]
    assert db.get(FinancialFact, persistida.id).value == Decimal("100")


# --- _derive_sec_metrics (2981-2982 periodo no ISO, 3018->3034 avg_equity<=0) ---


def test_derive_sec_metrics_periodo_no_iso_y_equity_media_no_positiva(db):
    """2981-2982: un periodo no parseable se salta en el calculo del ejercicio
    mas reciente. 3018->3034 (motor insurer): con patrimonio medio <= 0 no se
    publica ROE (y con patrimonio previo <= 0 tampoco book_value_growth)."""
    company = _company_aseguradora(db)
    document = _document(db, company)
    _fact(db, company, "revenue", 100, period="no-es-fecha", fiscal_year=2024, source_type="SEC")
    _fact(db, company, "net_income", 10, period="2024-12-31:FY", fiscal_year=2024, source_type="SEC")
    _fact(db, company, "total_equity", -50, period="2024-12-31:FY", fiscal_year=2024, source_type="SEC")
    _fact(db, company, "total_equity", -50, period="2023-12-31:FY", fiscal_year=2023, source_type="SEC")
    derived = FinancialIngestionService()._derive_sec_metrics(db, company, document)
    assert derived == 0
    assert "roe" not in _metrics(db, company)
    assert "book_value_growth" not in _metrics(db, company)
    assert "net_debt" not in _metrics(db, company)


# --- _derive_esef_metrics (arco 3320->3313 sin fiscal_year; 3328 declarada) ---


def test_derive_esef_metrics_salta_sin_ano_y_deriva_crecimiento(db):
    """3320->3313: un hecho ESEF sin fiscal_year no entra en el panel. El resto
    deriva con normalidad: revenue 50 -> 100 da revenue_growth = 1 exacto."""
    company = _company(db)
    document = _document(db, company, source_type="ESEF")
    _fact(db, company, "revenue", 7, period="2024-12-31:FY", fiscal_year=None, source_type="ESEF")
    _fact(db, company, "revenue", 100, period="2024-12-31:FY", fiscal_year=2024, source_type="ESEF")
    _fact(db, company, "revenue", 50, period="2023-12-31:FY", fiscal_year=2023, source_type="ESEF")
    derived = FinancialIngestionService()._derive_esef_metrics(db, company, document)
    assert derived == 1
    growth = db.scalar(
        select(FinancialFact).where(
            FinancialFact.company_id == company.id,
            FinancialFact.metric == "revenue_growth",
        )
    )
    assert growth is not None
    assert growth.value == Decimal("1")
    assert growth.is_reported is False
    assert growth.fiscal_year == 2024
    assert growth.source_type == "ESEF"


# --- _restore_sec_quarters (3584 metrica sin ventana nueva, 3586 unidad) ---


def test_restore_sec_quarters_descarta_metrica_sin_ventana_y_unidad_cambiada(db):
    """3584: una metrica que el import actual no re-escribio no resucita.
    3586: si la unidad cambio (otra moneda de reporte) no se mezcla con la
    serie nueva."""
    company = _company(db)
    document = _document(db, company)
    fila_base = {
        "value": Decimal("1"),
        "period": "2020-12-31:Q4",
        "fiscal_year": 2020,
        "fiscal_quarter": "Q4",
        "is_reported": True,
        "is_adjusted": False,
        "confidence": Decimal("0.9"),
        "accession_number": "0000320193-21-000001",
        "filed": None,
    }
    prior = [
        {**fila_base, "metric": "revenue", "unit": "USD"},
        {**fila_base, "metric": "total_debt", "unit": "EUR"},
    ]
    restored = FinancialIngestionService()._restore_sec_quarters(
        db=db,
        company=company,
        document=document,
        prior=prior,
        new_ends_by_metric={"total_debt": {"2024-12-31"}},
        new_unit_by_metric={"total_debt": "USD"},
    )
    assert restored == 0
    assert _metrics(db, company) == []


# --- _add_spot_price (3931-3932 quote lanza, 3938 precio invalido, 3950-3951 volumen) ---


class _FMPQuote:
    def __init__(self, behavior):
        self._behavior = behavior

    async def quote(self, ticker):
        if isinstance(self._behavior, Exception):
            raise self._behavior
        return self._behavior


def test_add_spot_price_quote_que_falla_no_rompe_la_ingesta(db):
    """3931-3932: la quote es best-effort; una excepcion no tumba el refresh."""
    company = _company(db)
    fmp = _FMPQuote(RuntimeError("red caida"))
    asyncio.run(FinancialIngestionService()._add_spot_price(db, company, fmp, "ACME"))
    assert db.scalar(select(MarketPrice).where(MarketPrice.company_id == company.id)) is None


def test_add_spot_price_precio_no_positivo_no_escribe(db):
    """3938: precio ausente o <= 0 no se persiste (fail closed)."""
    company = _company(db)
    fmp = _FMPQuote([{"price": -3}])
    asyncio.run(FinancialIngestionService()._add_spot_price(db, company, fmp, "ACME"))
    assert db.scalar(select(MarketPrice).where(MarketPrice.company_id == company.id)) is None


def test_add_spot_price_volumen_no_entero_queda_null(db):
    """3950-3951: un volumen no convertible no tumba la barra: se persiste con
    volume NULL (y adj_close NULL: una quote spot no es una barra ajustada)."""
    company = _company(db)
    ahora = int(datetime.now(UTC).timestamp())
    fmp = _FMPQuote([{"price": 10, "timestamp": ahora, "volume": "abc", "currency": "USD"}])
    asyncio.run(FinancialIngestionService()._add_spot_price(db, company, fmp, "ACME"))
    db.flush()
    barra = db.scalar(select(MarketPrice).where(MarketPrice.company_id == company.id))
    assert barra is not None
    assert barra.close == Decimal("10")
    assert barra.volume is None
    assert barra.adj_close is None
    assert barra.source == "FMP"
    assert barra.quote_currency == "USD"
