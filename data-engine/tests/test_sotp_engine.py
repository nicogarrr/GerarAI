from decimal import Decimal

from sqlalchemy import delete, select

from app.core.database import SessionLocal, init_db
from app.models import Company, FinancialFact
from app.services.valuation_service import ValuationService


def test_sotp_requires_sourced_segment_metrics_multiples_and_discount():
    init_db()
    db = SessionLocal()
    company_id: int | None = None
    ticker = "SOTPE"
    try:
        existing = db.scalar(select(Company).where(Company.ticker == ticker))
        if existing:
            db.execute(delete(FinancialFact).where(FinancialFact.company_id == existing.id))
            db.delete(existing)
            db.commit()

        company = Company(
            ticker=ticker,
            name="SOTP evidence test",
            exchange="TEST",
            currency="USD",
            sector="Industrials",
            industry="Conglomerate",
            company_type="multi_segment",
            valuation_model="sotp",
            special_sources=[],
            special_risks=[],
            factor_tags=["sotp"],
        )
        db.add(company)
        db.flush()
        company_id = company.id
        facts = {
            "shares_diluted": 100,
            "net_debt": 250,
            "holding_company_discount": 0.12,
            "segment_services_operating_metric": 80,
            "segment_services_valuation_multiple": 12,
            "segment_assets_operating_metric": 500,
            "segment_assets_valuation_multiple": 1.1,
        }
        for metric, value in facts.items():
            db.add(
                FinancialFact(
                    company_id=company.id,
                    metric=metric,
                    value=Decimal(str(value)),
                    unit="decimal",
                    period="FY2025",
                    fiscal_year=2025,
                    fiscal_quarter="FY",
                    source_type="sotp_engine_test",
                    confidence=Decimal("0.91"),
                )
            )
        db.commit()

        result = ValuationService().value_company(db, company)
        probabilities = [
            result["trace"]["scenarios"][name]["definition"]["probability"]
            for name in ("bear", "base", "bull")
        ]

        assert result["status"] == "ok"
        assert result["publishable"] is True
        assert result["trace"]["holding_discount_source"] == "financial_facts"
        assert "segment_services_valuation_multiple" in result["trace"]["fact_ids"]
        assert probabilities != [0.25, 0.50, 0.25]
        assert abs(sum(probabilities) - 1.0) < 1e-9
    finally:
        if company_id is not None:
            db.execute(delete(FinancialFact).where(FinancialFact.company_id == company_id))
            db.execute(delete(Company).where(Company.id == company_id))
            db.commit()
        db.close()


BASE_FACTS = {
    "shares_diluted": 100,
    "net_debt": 250,
    "holding_company_discount": 0.12,
    "segment_services_operating_metric": 80,
    "segment_services_valuation_multiple": 12,
    "segment_assets_operating_metric": 500,
    "segment_assets_valuation_multiple": 1.1,
}


def _sotp_result(
    facts_overrides: dict, *, tags=None, price=None, fiscal_years: dict | None = None
) -> dict:
    """Valida SOTPE con `facts_overrides` aplicando encima de BASE_FACTS.

    `None` como valor borra el fact: es la forma de expresar "no existe".
    """
    init_db()
    db = SessionLocal()
    try:
        company = db.scalar(select(Company).where(Company.ticker == "SOTPE"))
        if company:
            db.execute(delete(FinancialFact).where(FinancialFact.company_id == company.id))
            db.delete(company)
            db.commit()
        company = Company(
            ticker="SOTPE",
            name="SOTP evidence test",
            exchange="TEST",
            currency="USD",
            sector="Industrials",
            industry="Conglomerate",
            company_type="multi_segment",
            valuation_model="sotp",
            factor_tags=tags if tags is not None else ["sotp"],
        )
        db.add(company)
        db.flush()
        for metric, value in {**BASE_FACTS, **facts_overrides}.items():
            if value is None:
                continue
            db.add(
                FinancialFact(
                    company_id=company.id,
                    metric=metric,
                    value=Decimal(str(value)),
                    unit="decimal",
                    period=f"FY{(fiscal_years or {}).get(metric, 2025)}",
                    fiscal_year=(fiscal_years or {}).get(metric, 2025),
                    fiscal_quarter="FY",
                    source_type="sotp_engine_test",
                    confidence=Decimal("0.91"),
                )
            )
        db.commit()
        if price is not None:
            from app.valuation.engines.sotp_engine import SOTPEngine
            engine = SOTPEngine()
            return engine.value(engine.build_context(db, company, price))
        return ValuationService().value_company(db, company)
    finally:
        db.execute(delete(FinancialFact).where(FinancialFact.company_id == company.id))
        db.execute(delete(Company).where(Company.id == company.id))
        db.commit()
        db.close()


def test_every_blocking_input_is_named_in_missing_inputs():
    """Cada condicion que bloquea tiene que DECIRSE en `missing_inputs`.

    El motor decidia con `missing or not segments or shares is None or
    shares <= 0 or net_debt is None`: los disjuntos repetidos no anadian
    cobertura (todo lo que bloqueaba ya estaba en la lista) y hacia
    imposible saber que habia bloqueado leyendo el motivo. Este test ata una
    etiqueta por condicion.
    """
    # Shares ausentes.
    result = _sotp_result({"shares_diluted": None})
    assert result["status"] == "insufficient_data"
    assert result["missing_inputs"] == ["shares_diluted"]

    # Shares inutilizables (cero o negativo): tampoco son acciones.
    result = _sotp_result({"shares_diluted": 0})
    assert result["status"] == "insufficient_data"
    assert result["missing_inputs"] == ["shares_diluted"]

    # Deuda neta ausente: el NAV no se puede cerrar.
    result = _sotp_result({"net_debt": None})
    assert result["status"] == "insufficient_data"
    assert result["missing_inputs"] == ["net_debt"]

    # Descuento fuera de [0, 1): no es un descuento de holding.
    result = _sotp_result({"holding_company_discount": 1.4})
    assert result["status"] == "insufficient_data"
    assert result["missing_inputs"] == ["holding_company_discount"]

    # Ningun segmento valorable.
    result = _sotp_result(
        {
            "segment_services_operating_metric": None,
            "segment_services_valuation_multiple": None,
            "segment_assets_operating_metric": None,
            "segment_assets_valuation_multiple": None,
        }
    )
    assert result["status"] == "insufficient_data"
    assert result["missing_inputs"] == [
        "segment_*_operating_metric",
        "segment_*_valuation_multiple",
    ]
    assert result["trace"]["segment_fact_contract"]["operating_metric"] == (
        "segment_{name}_operating_metric"
    )

    # Completo: ninguna de esas condiciones aparece como bloqueo.
    result = _sotp_result({})
    assert result["status"] == "ok"
    assert result["publishable"] is True



def test_sotp_adr_price_uses_ordinary_share_basis():
    import pytest
    ordinary = _sotp_result({}, price=10)
    adr = _sotp_result({}, tags=["sotp", "adr:8"], price=80)
    assert adr["expected_value"] == pytest.approx(ordinary["expected_value"])
    assert adr["margin_of_safety"] == pytest.approx(ordinary["margin_of_safety"])
    assert adr["adr_ratio"] == 8
    assert adr["trace"]["comparable_price"] == 10


def test_sotp_adr_without_valid_ratio_refuses():
    for tag in ("adr", "adr:0", "adr:invalid", "adr:inf", "adr:Infinity", "adr:1e309", "adr:NaN"):
        result = _sotp_result({}, tags=["sotp", tag], price=80)
        assert result["status"] == "insufficient_data"
        assert result["publishable"] is False
        assert "adr_ratio" in result["missing_inputs"]


def test_sotp_adr_conflicting_tags_refuse_in_either_order():
    for tags in (["sotp", "adr:8", "adr:2"], ["sotp", "adr:2", "adr:8"]):
        result = _sotp_result({}, tags=tags, price=80)
        assert result["status"] == "insufficient_data"
        assert "adr_ratio" in result["missing_inputs"]


def test_shared_adr_helper_only_admits_positive_finite_unambiguous_ratios():
    from types import SimpleNamespace

    from app.valuation.engines.base import adr_ratio, is_adr_without_ratio
    for tags in (["adr:inf"], ["adr:Infinity"], ["adr:1e309"], ["adr:NaN"], ["adr:8", "adr:2"], ["adr:2", "adr:8"], ["adr:8", "adr:inf"]):
        company = SimpleNamespace(factor_tags=tags)
        assert adr_ratio(company) is None
        assert is_adr_without_ratio(company)
    assert adr_ratio(SimpleNamespace(factor_tags=["adr:8", "adr:8.0"])) == 8


def test_sotp_blocks_segments_from_different_periods():
    result = _sotp_result({}, fiscal_years={"segment_assets_operating_metric": 2022})
    assert result["status"] != "ok"
    assert result["publishable"] is False
    assert "consistent_segment_periods" in result["missing_inputs"]


def test_sotp_same_period_segments_still_value():
    result = _sotp_result({})
    assert result["status"] == "ok"
    assert "consistent_segment_periods" not in result["missing_inputs"]


def _seed_sotp(db, ticker, units):
    existing = db.scalar(select(Company).where(Company.ticker == ticker))
    if existing:
        db.execute(delete(FinancialFact).where(FinancialFact.company_id == existing.id))
        db.delete(existing)
        db.commit()
    company = Company(
        ticker=ticker, name="SOTP currency test", exchange="TEST", currency="USD",
        sector="Industrials", industry="Conglomerate", company_type="multi_segment",
        valuation_model="sotp", special_sources=[], special_risks=[], factor_tags=["sotp"],
    )
    db.add(company)
    db.flush()
    facts = {
        "shares_diluted": (100, "shares"),
        "net_debt": (250, units["net_debt"]),
        "holding_company_discount": (0.12, "decimal"),
        "segment_services_operating_metric": (80, units["services"]),
        "segment_services_valuation_multiple": (12, "decimal"),
        "segment_assets_operating_metric": (500, units["assets"]),
        "segment_assets_valuation_multiple": (1.1, "decimal"),
    }
    for metric, (value, unit) in facts.items():
        db.add(FinancialFact(
            company_id=company.id, metric=metric, value=Decimal(str(value)), unit=unit,
            period="FY2025", fiscal_year=2025, fiscal_quarter="FY",
            source_type="sotp_engine_test", confidence=Decimal("0.91"),
        ))
    db.commit()
    return company


def test_sotp_blocks_segments_and_net_debt_in_different_currencies():
    """Un segmento en EUR sumado a otro en USD menos deuda en USD no es un NAV.

    Antes: (80x12 USD + 500x1,1 EUR - 250 USD) / 100 = 12,60 "USD" por accion,
    11,09 tras el 12 % de descuento, con margen de seguridad publicado.
    Ahora: N/D con ``single_reporting_currency`` en lo que falta.
    """
    init_db()
    db = SessionLocal()
    ids = []
    try:
        mixed = _seed_sotp(db, "SOTPFX", {"net_debt": "USD", "services": "USD", "assets": "EUR"})
        ids.append(mixed.id)
        result = ValuationService().value_company(db, mixed)
        assert result["status"] != "ok"
        assert result.get("expected_value") is None
        assert "single_reporting_currency" in result["missing_inputs"]

        same = _seed_sotp(db, "SOTPUS", {"net_debt": "USD", "services": "USD", "assets": "USD"})
        ids.append(same.id)
        ok = ValuationService().value_company(db, same)
        assert ok["status"] == "ok"
        # (960 + 550 - 250) / 100 = 12,60 NAV; x (1 - 0,12) = 11,088 base.
        rows = ok["trace"]["sensitivity"]["rows"] if "sensitivity" in ok["trace"] else None
        assert "single_reporting_currency" not in (ok.get("missing_inputs") or [])
        if rows:
            base = next(r for r in rows if r["scenario"] == "base_discount")
            assert abs(base["nav_per_share"] - 12.60) < 1e-9
    finally:
        for cid in ids:
            db.execute(delete(FinancialFact).where(FinancialFact.company_id == cid))
            db.execute(delete(Company).where(Company.id == cid))
        db.commit()
        db.close()


def test_sotp_currency_inputs_preserve_segment_and_debt_units(monkeypatch):
    from types import SimpleNamespace
    from app.valuation.engines import sotp_engine
    facts = {
        'segment_services_operating_metric': SimpleNamespace(unit='USD'),
        'net_debt': SimpleNamespace(unit='EUR'),
    }
    monkeypatch.setattr(sotp_engine, '_latest_facts_by_metric', lambda _: facts)
    assert sotp_engine.SOTPEngine().currency_input_units(SimpleNamespace()) == ['USD', 'EUR']
