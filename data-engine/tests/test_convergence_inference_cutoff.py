"""Una inferencia creada después del corte no puede valorar el pasado."""
from datetime import date
from decimal import Decimal

from app.services.inferred_input_service import InferredInputService
from app.valuation.engines.base import ValuationContext
from app.valuation.engines.standard_dcf import StandardDCFEngine
from tests.test_inferred_global_coherent_wiring import _Snap
from tests.test_tesis_metodos_alternativos import BASE, URLS, VALUES, _company, db  # noqa: F401


def test_future_margin_target_is_not_used_in_historical_dcf(db):
    company = _company(db)
    InferredInputService().create(db, company, input_key="fcf_margin", value=Decimal("0.12"),
                                  base=BASE, source_urls=URLS)
    ctx = ValuationContext(db=db, company=company, snapshot=_Snap(VALUES), current_price=15.,
                           engine_key="standard_dcf", as_of=date(2020, 1, 1))
    out = StandardDCFEngine().value(ctx)
    assert out["status"] == "insufficient_data"
    assert "non_negative_fcf_margin" in out["missing_inputs"]


def test_cutoff_selects_older_inference_before_limit(db):
    from datetime import UTC, datetime

    company = _company(db)
    service = InferredInputService()
    old = service.create(db, company, input_key="fcf_margin", value=Decimal("0.10"),
                         base=BASE, source_urls=URLS)
    old.created_at = datetime(2019, 1, 1, tzinfo=UTC)
    db.commit()
    service.create(db, company, input_key="fcf_margin", value=Decimal("0.20"),
                   base=BASE, source_urls=URLS)
    assert service.latest_valid(db, company.id, "fcf_margin", as_of=date(2020, 1, 1)).id == old.id
    assert float(service.latest_valid(db, company.id, "fcf_margin").value) == .20


def test_historical_rates_ignore_future_inference(db):
    from app.valuation.engines.base import resolve_rates

    company = _company(db)
    service = InferredInputService()
    baseline = resolve_rates(db, company, as_of=date(2020, 1, 1))
    service.create(db, company, input_key="wacc", value=Decimal("0.20"), base=BASE, source_urls=URLS)
    assert resolve_rates(db, company, as_of=date(2020, 1, 1)) == baseline
    assert resolve_rates(db, company)[1] == "inferred_input"
