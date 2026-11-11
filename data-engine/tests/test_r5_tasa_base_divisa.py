"""r5-valor: emisores fuera de USD (TSM en TWD, CNQ en CAD, AIR.PA en EUR…) y tasa base.

Antes: los tramos de tamaño de la tasa base están en dólares y
- la comprobación «¿con qué frecuencia lo consiguieron?» quedaba N/D («ingresos en otra divisa») y
- el ancla de las estimaciones (``for_annual_revenue``) clasificaba la cifra en SU divisa como si
  fueran dólares: 50.000 M de yenes (≈ 330 M$) caían en «>10B».
Ahora: el tipo oficial del cierre del ejercicio (``fx_rates``, point-in-time) convierte el
último ingreso a USD SOLO para elegir el tramo; el crecimiento previo (un cociente) no cambia.
Sin tipo oficial: N/D con el motivo. Cálculo a mano (convención de la tabla: importe × rate = EUR):
  31-12-2025: 1 JPY = 0,0060 EUR; 1 USD = 0,9000 EUR → 1 JPY = 0,0060 / 0,9 = 0,006667 USD.
  50.000 M JPY × 0,006667 = 333 M$ → tramo «100M-1B».
"""
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, FinancialFact, FXRate
from app.services import own_consensus as svc
from app.services.estimate_base_rates import for_annual_revenue, usd_size_fx
from app.services.financial_health import HealthFact
from app.services.valuation_summary import _reverse_base_rate_check

GRID = [round(0.05 * i, 2) for i in range(1, 20)]


def _item(n=100, shift=0.0):
    q = [round(-0.10 + shift + 0.02 * i, 4) for i in range(19)]
    return {"growth": {"p10": q[1], "p25": q[4], "p50": q[9], "p75": q[14], "p90": q[17], "n": n, "q": q},
            "margin": {"p10": -0.05, "p25": -0.02, "p50": 0.0, "p75": 0.02, "p90": 0.05, "n": n, "q": q}}


DATA = {"version": "v2", "source": "fixture", "grid": GRID, "groups": {
    "h1|100M-1B|5-10 %|*": _item(shift=0.01),
    "h1|>10B|5-10 %|*": _item(shift=-0.03),
    "h1|*|5-10 %|*": _item(),
    "h1|*|*|*": _item(),
}}
# 40.000 → 50.000 M en 3 años: TCAC 7,7 % («5-10 %») en cualquier divisa.
JPY_REVENUE = {2022: 40e9, 2025: 50e9}


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _ecb(db, day, **eur_per_unit):
    for code, rate in eur_per_unit.items():
        db.add(FXRate(base_currency="EUR", quote_currency=code, rate=Decimal(str(rate)), rate_date=day, source="ECB"))
    db.flush()


def test_size_bucket_is_chosen_in_dollars_not_in_the_reporting_currency() -> None:
    as_if_usd = for_annual_revenue(JPY_REVENUE, data=DATA)  # lo que hacía el ancla con yenes
    assert as_if_usd is not None and "tamaño >10B" in as_if_usd.group
    converted = for_annual_revenue(JPY_REVENUE, data=DATA, usd_rate=0.0060 / 0.9, size_note="nota FX")
    assert converted is not None and "tamaño 100M-1B" in converted.group and "nota FX" in converted.group
    assert "crecimiento previo 5-10 %" in converted.group  # el cociente no depende de la divisa
    unknown = for_annual_revenue(JPY_REVENUE, data=DATA, usd_rate=None, size_note="nota FX")
    assert unknown is not None and "tamaño" not in unknown.group and "nota FX" not in unknown.group


def test_official_rate_at_the_close_point_in_time(db) -> None:
    close = date(2025, 12, 31)
    _ecb(db, close, JPY=0.0060, USD=0.9)
    _ecb(db, date(2026, 6, 30), JPY=0.0010, USD=0.9)  # posterior al cierre: nunca se usa para ese cierre
    fx = usd_size_fx(db, "JPY", close, today=date(2026, 11, 11))
    assert fx.rate == pytest.approx(0.0060 / 0.9) and fx.rate_date == close and fx.at_close
    assert "JPY→USD" in fx.note and "31-12-2025" in fx.note and "último publicado" not in fx.note
    assert usd_size_fx(db, "USD", close, today=date(2026, 11, 11)).rate == 1.0


def test_without_close_rate_uses_latest_official_with_its_date_or_nd_with_reason(db) -> None:
    today = date(2026, 11, 11)
    _ecb(db, date(2026, 11, 10), TWD=0.028, USD=0.9)  # solo el refresco diario de ayer
    recent = usd_size_fx(db, "TWD", date(2025, 12, 31), today=today)
    assert recent.rate == pytest.approx(0.028 / 0.9) and not recent.at_close
    assert "10-11-2026" in recent.note and "no había del cierre" in recent.note
    old = usd_size_fx(db, "TWD", date(2024, 6, 30), today=today)  # cierre de hace > 400 días
    assert old.rate is None and "sin tipo oficial TWD→USD al cierre del 30-06-2024" in old.reason
    nothing = usd_size_fx(db, "GEL", date(2025, 12, 31), today=today)
    assert nothing.rate is None and "GEL→USD" in nothing.reason


def _company(db, unit, values):
    company = Company(ticker="TEST.T", name="Test KK", exchange="TSE", currency=unit, cik=None,
                      company_type="operating", valuation_model="dcf")
    db.add(company)
    db.flush()
    for year, value in values.items():
        db.add(FinancialFact(company_id=company.id, metric=svc.FACT_METRIC["revenue"], value=Decimal(str(value)),
                             unit=unit, period=f"{year}-01-01:{year}-12-31", fiscal_year=year, fiscal_quarter="FY"))
    db.flush()
    return company


def _actuals(values):
    return {f"fy{y}": svc.Actual(f"fy{y}", date(y, 12, 31), v) for y, v in values.items()}


def test_consensus_size_fx_reads_the_single_reporting_currency(db) -> None:
    _ecb(db, date(2025, 12, 31), JPY=0.0060, USD=0.9)
    company = _company(db, "JPY", JPY_REVENUE)
    fx = svc._revenue_size_fx(db, company, _actuals(JPY_REVENUE), date(2026, 11, 11))
    assert fx.currency == "JPY" and fx.rate == pytest.approx(0.0060 / 0.9)
    mixed = _company_mixed(db)
    nd = svc._revenue_size_fx(db, mixed, _actuals(JPY_REVENUE), date(2026, 11, 11))
    assert nd.rate is None and "varias divisas (EUR, JPY)" in nd.reason


def _company_mixed(db):
    company = Company(ticker="MIX", name="Mix SA", exchange="XPAR", currency="EUR", cik=None,
                      company_type="operating", valuation_model="dcf")
    db.add(company)
    db.flush()
    for year, unit in ((2024, "EUR"), (2025, "JPY")):
        db.add(FinancialFact(company_id=company.id, metric=svc.FACT_METRIC["revenue"], value=Decimal("1e9"),
                             unit=unit, period=f"{year}-01-01:{year}-12-31", fiscal_year=year, fiscal_quarter="FY"))
    db.flush()
    return company


def test_reverse_dcf_check_converts_non_usd_revenue_with_the_close_rate(db) -> None:
    _ecb(db, date(2025, 12, 31), JPY=0.0060, USD=0.9)
    facts = [HealthFact(i, "revenue", y, v, "JPY", date(y, 12, 31), "u", "sec")
             for i, (y, v) in enumerate(JPY_REVENUE.items())]
    rev = {"status": "ok", "trace": {"horizon_years": 1}}
    import app.services.estimate_base_rates as ebr

    seen = {}

    def spy(annual, **kw):
        seen.update(kw)
        return for_annual_revenue(annual, data=DATA, **kw)

    mp = pytest.MonkeyPatch()
    mp.setattr(ebr, "for_annual_revenue", spy)
    try:
        out = _reverse_base_rate_check(SimpleNamespace(cik=None), facts, rev, 0.05,  # type: ignore[arg-type]
                                       db=db, today=date(2026, 11, 11))
        no_db = _reverse_base_rate_check(SimpleNamespace(cik=None), facts, rev, 0.05)  # type: ignore[arg-type]
    finally:
        mp.undo()
    assert seen["usd_rate"] == pytest.approx(0.0060 / 0.9)
    assert out is not None and out["share"] is not None and "tamaño 100M-1B" in out["group"]
    assert "JPY→USD" in out["formula"]
    assert no_db == {"share": None, "reason": "ingresos en otra divisa: los tramos de tamaño de la tasa base "
                                             "están en dólares"}
