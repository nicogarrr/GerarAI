from decimal import Decimal

from sqlalchemy import delete, select

from app.core.database import SessionLocal, init_db
from app.models import Company, FinancialFact
from app.services.valuation_service import ValuationService

EXTREME = {
    "BKCAP": ("bank", "bank_residual_income", {
        "tangible_book_value": 1000, "shares_diluted": 100, "roe": 0.40,
        "cost_of_equity": 0.10, "book_value_growth": 0.03}),
    "INCAP": ("insurer", "insurance_book_value", {
        "book_value": 1200, "shares_diluted": 100, "roe": 0.40, "cost_of_equity": 0.10,
        "combined_ratio": 0.95, "book_value_growth": 0.03}),
    "RTCAP": ("reit", "reit_nav", {
        "net_operating_income": 100, "cap_rate": 0.05, "net_debt": 5000, "shares_diluted": 100}),
    "BKOKK": ("bank", "bank_residual_income", {
        "tangible_book_value": 1000, "shares_diluted": 100, "roe": 0.14,
        "cost_of_equity": 0.10, "book_value_growth": 0.03}),
}


def test_real_engines_surface_cap_warnings_in_result_and_trace():
    init_db()
    db = SessionLocal()
    ids: list[int] = []
    try:
        for ticker, (ctype, model, facts) in EXTREME.items():
            old = db.scalar(select(Company).where(Company.ticker == ticker))
            if old:
                db.execute(delete(FinancialFact).where(FinancialFact.company_id == old.id))
                db.delete(old)
                db.commit()
            company = Company(
                ticker=ticker, name=f"{ctype} test", exchange="TEST", currency="USD",
                sector="Financials" if ctype != "reit" else "Real Estate", industry="Test",
                company_type=ctype, valuation_model=model, special_sources=[],
                special_risks=[], factor_tags=[])
            db.add(company)
            db.flush()
            ids.append(company.id)
            for metric, value in facts.items():
                db.add(FinancialFact(
                    company_id=company.id, metric=metric, value=Decimal(str(value)),
                    unit="decimal" if abs(value) < 1 else "USD", period="FY2025",
                    fiscal_year=2025, fiscal_quarter="FY", source_type="sector_engine_test",
                    is_reported=True, confidence=Decimal("0.92")))
        db.commit()
        service = ValuationService()
        res = {t: service.value_company(db, db.scalar(select(Company).where(Company.ticker == t))) for t in EXTREME}
        for t in ("BKCAP", "INCAP"):
            codes = {w["code"] for w in res[t]["warnings"]}
            assert codes == {"pb_cap_applied"}, t
            assert res[t]["trace"]["warnings"] == res[t]["warnings"]
            assert res[t]["trace"]["assumptions"]["pb_caps_applied"]
            assert any("3,00x" in w["detail"] for w in res[t]["warnings"])
        reit = res["RTCAP"]
        assert {w["scenario"] for w in reit["warnings"] if w["code"] == "nav_floored_at_zero"} == {"bear", "base", "bull"}
        assert reit["trace"]["warnings"] == reit["warnings"]
        assert "warnings" not in res["BKOKK"] and "warnings" not in res["BKOKK"]["trace"]
    finally:
        if ids:
            db.execute(delete(FinancialFact).where(FinancialFact.company_id.in_(ids)))
            db.execute(delete(Company).where(Company.id.in_(ids)))
            db.commit()
        db.close()
