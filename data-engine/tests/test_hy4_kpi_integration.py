from decimal import Decimal

import pytest

from app.services.kpi_extraction_service import KPIExtractionService
from tests import test_kpi_grounding_contracts as fixture


def test_hy4_kpi_skips_external_jev_and_records_verified_zero(monkeypatch):
    from app.services import jev_gates
    from app.services.budget import BudgetController
    seen=[]
    monkeypatch.setattr(fixture._StaticProvider,'name','hy4-go-zero')
    async def forbidden(*args): raise AssertionError('Jev must not run for Hy4 KPI')
    monkeypatch.setattr(jev_gates,'kpi_chunk_keep_flags',forbidden)
    def can_spend(self, db, amount):
        seen.append(amount)
        return amount==0
    monkeypatch.setattr(BudgetController,'can_spend',can_spend)
    def estimate(*args): raise AssertionError('Hy4 cost must come from guarded zero, not heuristic')
    monkeypatch.setattr(BudgetController,'estimate_cost_eur',estimate)
    candidate=fixture._extraction('La penetración alcanza el 12,5% del mercado.', '12,5')
    assert candidate.status=='pending_approval'
    assert seen==[0]


@pytest.mark.parametrize('status',[429,402])
def test_hy4_kpi_failure_is_one_attempt_and_stops(monkeypatch,status):
    from app.llm.errors import ProviderHTTPError
    calls=[]
    monkeypatch.setattr(fixture._StaticProvider,'name','hy4-go-zero')
    async def complete(self,request):
        calls.append(request)
        raise ProviderHTTPError('hy4-go-zero',status)
    monkeypatch.setattr(fixture._StaticProvider,'complete',complete)
    with pytest.raises(ProviderHTTPError): fixture._extraction('La penetración alcanza el 12,5%.','12,5')
    assert len(calls)==1


def test_numeric_boundaries_cannot_turn_missing_into_zero():
    assert KPIExtractionService._integer(None) is None
    assert KPIExtractionService._quote_figures('')==[]
    zero=KPIExtractionService._quote_figures('Resultado 0 euros.')
    assert KPIExtractionService._value_supported(Decimal('0'),zero,'EUR')
    assert not KPIExtractionService._value_supported(Decimal('1'),zero,'EUR')
    negative=KPIExtractionService._quote_figures('Resultado -10 euros.')
    assert not KPIExtractionService._value_supported(Decimal('10'),negative,'EUR')
