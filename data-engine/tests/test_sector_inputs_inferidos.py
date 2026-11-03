"""Inputs sectoriales INFERIDOS por el modelo (cap rate, ratio combinado,
descuento holding): el motor los usa solo sin hecho ni extraccion, y viajan
etiquetados («inferido», base y URLs) en ``estimated_inputs``."""

from __future__ import annotations

from decimal import Decimal

from app.core.database import SessionLocal, init_db
from app.services import sector_inputs
from app.services.inferred_input_service import InferredInputService
from app.services.valuation_service import ValuationService
from tests.test_sector_inputs import _company, _fact

BASE = "dado cartera multifamiliar en Sun Belt (extracto src:1), inferimos cap rate de mercado 5,25 %"
URLS = ["https://www.sec.gov/Archives/edgar/data/906345/000162828026007697/cpt-20251231.htm"]


def _session():
    init_db()
    db = SessionLocal()
    db.info["tenant_id"] = 1
    return db


def test_reit_values_with_inferred_cap_rate_labeled():
    db = _session()
    try:
        with _company(db, "SECREITINF", "reit") as company:
            for metric, value in (
                ("net_operating_income", 1_006_834_000),
                ("net_debt", 3_500_000_000),
                ("shares_diluted", 108_000_000),
            ):
                _fact(db, company, metric, value)
            db.commit()
            before = ValuationService().value_company(db, company)
            assert before["missing_inputs"] == ["cap_rate"]
            InferredInputService().create(
                db, company, input_key="cap_rate", value=Decimal("0.0525"), base=BASE, source_urls=URLS
            )
            result = ValuationService().value_company(db, company)
            assert result["status"] == "ok"
            (item,) = [i for i in result["estimated_inputs"] if i["metric"] == "cap_rate"]
            assert item["status"] == "inferido" and BASE in item["method"]
            assert item["note"].startswith("una sola fuente, no oficial")
            assert item["sources"][0]["url"] == URLS[0]
            nav = (1_006_834_000 / 0.0525 - 3_500_000_000) / 108_000_000
            assert abs(result["base_value"] - nav) < 1e-6
    finally:
        db.close()


def test_cap_rate_out_of_range_is_not_inferable():
    assert InferredInputService.__module__
    from app.services.inferred_input_service import validate

    assert validate("cap_rate", 0.40, BASE, URLS) == ["valor fuera de rango"]
    assert validate("holding_company_discount", 0.0, BASE, URLS) == []


def test_reported_nav_entity_uses_inferred_discount_labeled():
    db = _session()
    try:
        with _company(db, "SECNAVINF", "investment_entity") as company:
            company.company_type = "holding_company_investment_entity"
            _fact(db, company, "total_equity", 5_194_527_000)
            _fact(db, company, "shares_diluted", 35_029_723)
            db.commit()
            at_par = ValuationService().value_company(db, company)
            assert at_par["status"] == "ok", at_par.get("missing_inputs")
            assert at_par["trace"]["holding_discount_source"] == "none_reported_nav_at_par"
            InferredInputService().create(
                db,
                company,
                input_key="holding_company_discount",
                value=Decimal("0.25"),
                base=BASE.replace("cap rate", "descuento"),
                source_urls=URLS,
            )
            result = ValuationService().value_company(db, company)
            assert result["trace"]["holding_discount_source"] == "inferred_input"
            assert result["estimated_inputs"][0]["metric"] == "holding_company_discount"
            assert abs(result["base_value"] - at_par["base_value"] * 0.75) < 1e-6
    finally:
        db.close()


def test_prepare_sector_inputs_asks_only_for_what_is_missing(monkeypatch):
    db = _session()
    calls: list[str] = []

    async def fake_infer(db_, ticker, *, input_key, **_):
        calls.append(input_key)
        company = db_.get(type(the_company), the_company.id)
        return InferredInputService().create(
            db_, company, input_key=input_key, value=Decimal("0.055"), base=BASE, source_urls=URLS
        )

    monkeypatch.setattr("app.services.inferred_input_llm_service.infer_input", fake_infer)
    try:
        with _company(db, "SECPREP", "reit") as the_company:
            out = sector_inputs.prepare_sector_inputs(
                db, the_company, {"missing_inputs": ["cap_rate", "net_debt"], "trace": {}}
            )
            assert out == {"cap_rate": {"status": "inferido", "value": 0.055}}
            again = sector_inputs.prepare_sector_inputs(db, the_company, {"missing_inputs": ["cap_rate"]})
            assert again == {"cap_rate": "ya_inferido"}
            assert calls == ["cap_rate"]
    finally:
        db.close()
