"""Metricas de valoracion (P/B, yield TTM): calculo, fail-closed y desacuerdo.

Fixtures grabadas, sin red: los fetchers por defecto estan vetados bajo
pytest y aqui siempre se inyectan.
"""
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models import CalculatedMetric, FinancialFact, MarketPrice
from app.services.valuation_metrics_service import (
    METRIC_PB,
    METRIC_VERSION,
    METRIC_YIELD,
    STATUS_DISAGREE,
    STATUS_OK,
    compute_valuation_metrics,
    default_dividend_fetcher,
    default_finnhub_yield_fetcher,
    ttm_dividend_per_share,
)
from tests.test_propicks_prices import _company, _db

AS_OF = date(2026, 10, 27)
NO_FINNHUB = lambda ticker: None  # noqa: E731


def _fact(db, company, metric, value, fy, unit="USD", source_type="SEC"):
    db.add(
        FinancialFact(
            tenant_id=db.info["tenant_id"],
            company_id=company.id,
            metric=metric,
            value=Decimal(str(value)),
            unit=unit,
            period=f"{fy}-12-31:FY",
            fiscal_year=fy,
            fiscal_quarter="FY",
            source_type=source_type,
        )
    )
    db.flush()


def _price(db, company, day, close, source="test"):
    db.add(
        MarketPrice(
            company_id=company.id,
            date=day,
            close=Decimal(str(close)),
            adj_close=Decimal(str(close)),
            source=source,
        )
    )
    db.flush()


def _seed_pb(db, ticker="PB", equity="1000", shares="100", fy=2025, unit="USD",
             currency="USD", price="20", price_day=AS_OF):
    company = _company(ticker, currency=currency)
    db.add(company)
    db.flush()
    _fact(db, company, "total_equity", equity, fy, unit=unit)
    _fact(db, company, "shares_diluted", shares, fy, unit=unit)
    _price(db, company, price_day, price)
    return company


def _metric(db, company, metric):
    return db.scalar(
        select(CalculatedMetric).where(
            CalculatedMetric.company_id == company.id,
            CalculatedMetric.metric == metric,
            CalculatedMetric.period == AS_OF.isoformat(),
            CalculatedMetric.definition_version == METRIC_VERSION,
        )
    )


def _run(db, companies, events=None, finnhub=NO_FINNHUB):
    fetcher = (lambda symbol: events) if events is not None else (lambda symbol: [])
    return compute_valuation_metrics(
        db, companies, as_of=AS_OF, dividend_fetcher=fetcher,
        finnhub_yield_fetcher=finnhub,
    )


def test_pb_se_calcula_con_traza_completa():
    db = _db()
    company = _seed_pb(db)  # equity 1000, shares 100, close 20 -> P/B = 2
    stats = _run(db, [company])
    row = _metric(db, company, METRIC_PB)
    assert stats[METRIC_PB] == 1
    assert row is not None
    assert Decimal(row.value) == Decimal("2")
    trace = row.calculation_trace
    assert trace["fiscal_year"] == 2025
    assert trace["price_date"] == AS_OF.isoformat()
    assert trace["fact_unit"] == "USD"
    assert Decimal(trace["total_equity"]) == Decimal("1000")
    assert Decimal(trace["shares_diluted"]) == Decimal("100")
    assert row.status == STATUS_OK


def test_pb_equity_negativo_no_se_escribe():
    db = _db()
    company = _seed_pb(db, "NEG", equity="-500")
    stats = _run(db, [company])
    assert stats[METRIC_PB] == 0
    assert stats["skipped"]["sin_libros"] == 1
    assert _metric(db, company, METRIC_PB) is None


def test_pb_fy_viejo_no_se_escribe():
    db = _db()
    company = _seed_pb(db, "OLD", fy=2023)  # as_of 2026: FY2023 tiene 3 anos
    stats = _run(db, [company])
    assert stats[METRIC_PB] == 0
    assert _metric(db, company, METRIC_PB) is None


def test_pb_divisa_mezclada_no_se_escribe():
    db = _db()
    # Hechos en GBP pero la cotizacion es GBp (zona congelada): fail-closed.
    company = _seed_pb(db, "GBX", unit="GBP", currency="GBp")
    stats = _run(db, [company])
    assert stats[METRIC_PB] == 0
    assert _metric(db, company, METRIC_PB) is None


def test_pb_precio_stale_no_se_escribe():
    db = _db()
    company = _seed_pb(db, "STALE", price_day=AS_OF - timedelta(days=10))
    stats = _run(db, [company])
    assert stats[METRIC_PB] == 0
    assert stats["skipped"]["sin_precio_fresco"] == 1
    assert _metric(db, company, METRIC_PB) is None


def test_yield_ttm_suma_solo_la_ventana_12m():
    db = _db()
    company = _seed_pb(db, "YLD", price="10")
    events = [
        {"date": (AS_OF - timedelta(days=300)).isoformat(), "amount": "0.5"},  # dentro
        {"date": (AS_OF - timedelta(days=400)).isoformat(), "amount": "9.0"},  # fuera
    ]
    stats = _run(db, [company], events=events)
    row = _metric(db, company, METRIC_YIELD)
    assert stats[METRIC_YIELD] == 1
    assert row is not None
    assert Decimal(row.value) == Decimal("0.05")  # 0.5 / 10, el de 9.0 no entra
    assert row.calculation_trace["dividend_events"] == [
        {"date": (AS_OF - timedelta(days=300)).isoformat(), "amount": "0.5"}
    ]
    assert "fuente no oficial" in row.calculation_trace["yahoo_label"]


def test_yield_evento_posterior_al_as_of_excluido():
    db = _db()
    company = _seed_pb(db, "FUT", price="10")
    events = [{"date": (AS_OF + timedelta(days=5)).isoformat(), "amount": "1.0"}]
    _run(db, [company], events=events)
    row = _metric(db, company, METRIC_YIELD)
    assert Decimal(row.value) == Decimal("0")


def test_yield_sin_eventos_escribe_cero_rotulado():
    db = _db()
    company = _seed_pb(db, "ZERO", price="10")
    _run(db, [company], events=[])
    row = _metric(db, company, METRIC_YIELD)
    assert row is not None
    assert Decimal(row.value) == Decimal("0")
    assert row.status == STATUS_OK


def test_yield_error_de_fuente_no_escribe_nada():
    db = _db()
    company = _seed_pb(db, "FAIL", price="10")
    stats = compute_valuation_metrics(
        db, [company], as_of=AS_OF,
        dividend_fetcher=lambda symbol: None,  # la fuente fallo
        finnhub_yield_fetcher=NO_FINNHUB,
    )
    assert stats[METRIC_YIELD] == 0
    assert stats["skipped"]["dividendos_fuente_fallo"] == 1
    assert _metric(db, company, METRIC_YIELD) is None


def test_desacuerdo_finnhub_se_muestra_no_se_oculta():
    db = _db()
    company = _seed_pb(db, "DIS", price="10")
    events = [{"date": (AS_OF - timedelta(days=100)).isoformat(), "amount": "0.8"}]
    # Yahoo TTM 0.08 vs Finnhub indicado 0.05: desacuerdo relativo 37.5%.
    stats = _run(db, [company], events=events,
                 finnhub=lambda ticker: Decimal("0.05"))
    row = _metric(db, company, METRIC_YIELD)
    assert stats["desacuerdo_fuentes"] == 1
    assert row.status == STATUS_DISAGREE
    trace = row.calculation_trace
    assert trace["desacuerdo_fuentes"] is True
    assert trace["finnhub_yield_indicated"] == "0.05"  # ambas cifras visibles
    assert Decimal(row.value) == Decimal("0.08")


def test_concordancia_finnhub_status_ok():
    db = _db()
    company = _seed_pb(db, "AGR", price="10")
    events = [{"date": (AS_OF - timedelta(days=100)).isoformat(), "amount": "0.8"}]
    stats = _run(db, [company], events=events,
                 finnhub=lambda ticker: Decimal("0.082"))  # dif relativa ~2.4%
    row = _metric(db, company, METRIC_YIELD)
    assert stats["desacuerdo_fuentes"] == 0
    assert row.status == STATUS_OK
    assert row.calculation_trace["desacuerdo_fuentes"] is False


def test_yield_extremo_se_marca_para_revision():
    db = _db()
    company = _seed_pb(db, "EXT", price="10")
    events = [{"date": (AS_OF - timedelta(days=50)).isoformat(), "amount": "4.0"}]
    stats = _run(db, [company], events=events)
    row = _metric(db, company, METRIC_YIELD)
    assert stats["yield_extremo_revisar"] == 1
    assert row.calculation_trace["yield_extremo_revisar"] is True


def test_as_of_historico_no_usa_datos_posteriores():
    db = _db()
    company = _company("PIT")
    db.add(company)
    db.flush()
    _fact(db, company, "total_equity", "1000", 2024)
    _fact(db, company, "shares_diluted", "100", 2024)
    past = AS_OF - timedelta(days=300)
    _price(db, company, past, "20")
    _price(db, company, AS_OF, "100")  # posterior al corte historico: prohibido
    events = [
        {"date": (past - timedelta(days=10)).isoformat(), "amount": "0.5"},  # era conocible
        {"date": AS_OF.isoformat(), "amount": "9.0"},  # aun no existia en el corte
    ]
    compute_valuation_metrics(
        db, [company], as_of=past,
        dividend_fetcher=lambda symbol: events, finnhub_yield_fetcher=NO_FINNHUB,
    )
    row_pb = db.scalar(
        select(CalculatedMetric).where(
            CalculatedMetric.company_id == company.id,
            CalculatedMetric.metric == METRIC_PB,
            CalculatedMetric.period == past.isoformat(),
        )
    )
    row_y = db.scalar(
        select(CalculatedMetric).where(
            CalculatedMetric.company_id == company.id,
            CalculatedMetric.metric == METRIC_YIELD,
            CalculatedMetric.period == past.isoformat(),
        )
    )
    assert Decimal(row_pb.value) == Decimal("2")  # close 20 del corte, no 100
    assert row_pb.calculation_trace["price_date"] == past.isoformat()
    assert Decimal(row_y.value) == Decimal("0.025")  # 0.5/20, el dividendo de 9 no entra


def test_upsert_idempotente_mismo_as_of():
    db = _db()
    company = _seed_pb(db, "IDEM")
    _run(db, [company])
    _price(db, company, AS_OF + timedelta(days=1), "40")  # precio mas nuevo, mismo as_of no...
    # segundo run con el mismo as_of y otro precio disponible <= as_of no cambia
    stats = _run(db, [company])
    rows = db.scalars(
        select(CalculatedMetric).where(
            CalculatedMetric.company_id == company.id,
            CalculatedMetric.metric == METRIC_PB,
        )
    ).all()
    assert len([r for r in rows if r.period == AS_OF.isoformat()]) == 1
    assert stats[METRIC_PB] == 1


def test_ttm_dividend_per_share_descarta_importes_invalidos():
    total, used = ttm_dividend_per_share(
        [
            {"date": AS_OF.isoformat(), "amount": "1.5"},
            {"date": AS_OF.isoformat(), "amount": "-3"},  # negativo: no es un dividendo
            {"date": "no-es-fecha", "amount": "1"},
            {"amount": "1"},  # sin fecha
        ],
        AS_OF,
    )
    assert total == Decimal("1.5")
    assert len(used) == 1


def test_fetchers_por_defecto_vetados_bajo_pytest():
    with pytest.raises(RuntimeError):
        default_dividend_fetcher("AAPL")
    with pytest.raises(RuntimeError):
        default_finnhub_yield_fetcher("AAPL")



def test_pb_de_un_adr_usa_libros_por_adr():
    """BABA: 1 ADR = 8 ordinarias (tabla citada). Hechos por ordinaria.

    Calculo independiente: libros/ordinaria = 1000/100 = 10; por ADR = 80;
    ADR a 160 -> P/B = 160/80 = 2 (en main 160/10 = 16).
    """
    db = _db()
    company = _seed_pb(db, ticker="BABA", price="160")
    _run(db, [company])
    row = _metric(db, company, METRIC_PB)
    assert row is not None
    assert Decimal(row.value) == Decimal("2")
    assert row.calculation_trace["adr_ratio"] == 8


def test_pb_adr_etiquetado_sin_ratio_no_se_escribe():
    db = _db()
    company = _seed_pb(db, ticker="XADR", price="160")
    company.factor_tags = ["adr"]
    db.flush()
    _run(db, [company])
    assert _metric(db, company, METRIC_PB) is None
