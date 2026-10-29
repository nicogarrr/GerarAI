from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.services.esef_fact_quarantine import (
    EBRO_LEI,
    LOG_LEI,
    REASON,
    fact_quarantine_reason,
    reviewed_eps_conflict,
)
from app.services.esef_shares import ShareSkip, _derive_period


@pytest.mark.parametrize('end,value', [('2024-12-31','1351'),('2025-01-01','1351'),('2023-12-31','1215'),('2024-01-01','1215')])
def test_exact_reviewed_conflicts(end,value):
    assert reviewed_eps_conflict(EBRO_LEI,end,'ifrs-full:DilutedEarningsLossPerShare',value)


@pytest.mark.parametrize('lei,end,concept,value', [
    ('OTHER','2024-12-31','ifrs-full:DilutedEarningsLossPerShare','1351'),
    (EBRO_LEI,'2022-12-31','ifrs-full:DilutedEarningsLossPerShare','1351'),
    (EBRO_LEI,'2024-12-31','ifrs-full:Revenue','1351'),
    (EBRO_LEI,'2024-12-31','ifrs-full:DilutedEarningsLossPerShare','1.351'),
    (EBRO_LEI,'2024-12-31','ifrs-full:DilutedEarningsLossPerShare','not-number'),
])
def test_never_quarantine_by_size_or_infer_rescaling(lei,end,concept,value):
    assert not reviewed_eps_conflict(lei,end,concept,value)


def fact(**changes):
    values=dict(source_type='ESEF',metric='eps_diluted',period='2025-01-01:FY',value=Decimal('1351'),is_reported=True,source=SimpleNamespace(metadata_={'lei':EBRO_LEI}))
    values.update(changes)
    return SimpleNamespace(**values)


def test_persisted_conflict_has_reason_without_mutation():
    row=fact()
    assert fact_quarantine_reason(row)==REASON
    assert row.value==Decimal('1351')
    assert fact_quarantine_reason(fact(source_type='SEC')) is None
    assert fact_quarantine_reason(fact(source=None)) is None


def test_persisted_derived_shares_blocked_only_with_exact_lineage():
    source=SimpleNamespace(metadata_={'lei':EBRO_LEI,'esef_shares':{'derived':[{'period':'2024-12-31','eps':'1351','shares':'153865'}]}})
    assert fact_quarantine_reason(fact(metric='shares_diluted',period='2024-12-31:FY',value=Decimal('153865'),is_reported=False,source=source))==REASON
    assert fact_quarantine_reason(fact(metric='shares_diluted',period='2024-12-31:FY',value=Decimal('153865392'),is_reported=False,source=source)) is None


def test_new_share_derivation_rejects_source_conflict():
    result=_derive_period('2024-12-31',{'val':'207867000'},{'lei':EBRO_LEI,'val':'1351','decimals':4},'diluted',max_rel_error=Decimal('.02'))
    assert isinstance(result,ShareSkip)
    assert result.reason=='bpa_esef_conflicto_escala_fuente_primaria'


def test_logista_source_scale_conflict_and_unreviewed_year_not_guessed():
    assert reviewed_eps_conflict(LOG_LEI,'2025-09-30','ifrs-full:BasicEarningsLossPerShare','2130')
    assert reviewed_eps_conflict(LOG_LEI,'2024-09-30','ifrs-full:BasicEarningsLossPerShare','2340')
    assert not reviewed_eps_conflict(LOG_LEI,'2023-09-30','ifrs-full:BasicEarningsLossPerShare','2070')
