"""Exact reference parity: freeze the three pre-optimization projections."""
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select

from app.core.tenancy import tenant_filters
from app.models import FinancialFact
from app.services import propicks_funnel_service as funnel
from app.services import propicks_gems_service as gems
from tests.test_propicks_funnel import _company, _db

CONSISTENCY_YEARS = 5
MIN_GROWTH_YEARS = 3


def reference_earnings_consistency(db) -> dict[int, tuple[int, int]]:
    """Positive-net-income years out of the last CONSISTENCY_YEARS fiscal years.

    Returns company_id -> (positive_years, years_with_data).
    """
    fy_rows = db.execute(
        select(
            FinancialFact.company_id,
            FinancialFact.fiscal_year,
            FinancialFact.value,
        )
        .where(FinancialFact.metric == "net_income")
        .where(FinancialFact.fiscal_quarter.in_(["FY", ""]))
        .where(FinancialFact.fiscal_year.isnot(None))
        .where(*tenant_filters(db, FinancialFact))
        .order_by(
            FinancialFact.company_id,
            FinancialFact.fiscal_year.desc(),
            FinancialFact.created_at.desc(),
        )
    ).all()
    by_company: dict[int, list[tuple[int, float]]] = {}
    seen: set[tuple[int, int]] = set()
    for cid, fy, value in fy_rows:
        if (cid, fy) in seen:  # keep newest-created row per fiscal year
            continue
        seen.add((cid, fy))
        by_company.setdefault(cid, []).append((fy, float(value)))
    out: dict[int, tuple[int, int]] = {}
    for cid, years in by_company.items():
        window = years[:CONSISTENCY_YEARS]
        positive = sum(1 for _, v in window if v > 0)
        out[cid] = (positive, len(window))
    return out


def reference_revenue_cagr(db) -> dict[int, float]:
    """Revenue CAGR over the available FY span (needs >= MIN_GROWTH_YEARS)."""
    rows = db.execute(
        select(
            FinancialFact.company_id,
            FinancialFact.fiscal_year,
            FinancialFact.value,
        )
        .where(FinancialFact.metric == "revenue")
        .where(FinancialFact.fiscal_quarter.in_(["FY", ""]))
        .where(FinancialFact.fiscal_year.isnot(None))
        .where(*tenant_filters(db, FinancialFact))
        .order_by(
            FinancialFact.company_id,
            FinancialFact.fiscal_year.asc(),
            FinancialFact.created_at.desc(),
        )
    ).all()
    by_company: dict[int, list[tuple[int, float]]] = {}
    seen: set[tuple[int, int]] = set()
    for cid, fy, value in rows:
        if (cid, fy) in seen:
            continue
        seen.add((cid, fy))
        by_company.setdefault(cid, []).append((fy, float(value)))
    out: dict[int, float] = {}
    for cid, years in by_company.items():
        if len(years) < MIN_GROWTH_YEARS:
            continue
        first_fy, first_val = years[0]
        last_fy, last_val = years[-1]
        span = int(last_fy) - int(first_fy)
        if span < 1 or first_val <= 0 or last_val <= 0:
            continue
        out[cid] = (last_val / first_val) ** (1.0 / span) - 1.0
    return out


def reference_latest_fcf_and_shares(db, min_fiscal_year: int) -> dict[int, tuple[float, float, str]]:
    rows = db.execute(
        select(
            FinancialFact.company_id, FinancialFact.metric, FinancialFact.fiscal_year,
            FinancialFact.value, FinancialFact.period,
        )
        .where(FinancialFact.metric.in_(["free_cash_flow", "shares_diluted"]))
        .where(FinancialFact.fiscal_quarter.in_(["FY", ""]))
        .where(FinancialFact.fiscal_year.isnot(None))
        # Un FY de hace más de 2 años no es un dato actual: VOYA entraba en
        # joyas con FCF de FY2016 contra precio de hoy. Sin FY reciente la
        # empresa se queda sin fcf_yield y no entra (fail-closed, N/D).
        .where(FinancialFact.fiscal_year >= min_fiscal_year)
        .where(*tenant_filters(db, FinancialFact))
        .order_by(FinancialFact.fiscal_year.desc(), FinancialFact.created_at.desc())
    ).all()
    fcf: dict[int, tuple[int, float, str]] = {}
    sh: dict[int, tuple[int, float]] = {}
    for cid, metric, fy, value, period in rows:
        if metric == "free_cash_flow":
            fcf.setdefault(cid, (fy, float(value), period))
        else:
            sh.setdefault(cid, (fy, float(value)))
    # Mismo ejercicio para FCF y acciones (doctrina del P/B: ejercicios
    # distintos no se mezclan): una recompra o dilucion entre FYs haria el
    # fcf_yield no verificable. Sin par del mismo FY: N/D (fail-closed).
    return {
        cid: (f[1], sh[cid][1], f[2])
        for cid, f in fcf.items()
        if cid in sh and sh[cid][1] > 0 and sh[cid][0] == f[0]
    }


def test_projection_parity_revisions_old_gaps_and_tenants():
    with _db() as db:
        companies = [_company(f'PAR{i}') for i in range(6)]
        db.add_all(companies)
        db.flush()
        tenant = db.info['tenant_id']
        for idx, company in enumerate(companies):
            for metric in ['net_income', 'revenue', 'free_cash_flow', 'shares_diluted']:
                for year in range(1990, 2027):
                    if (year + idx) % (idx + 2) == 0:
                        continue
                    for revision in range(4):
                        value = Decimal(year + revision)
                        if idx == 1 and metric == 'net_income':
                            value = -value
                        if idx == 2 and metric == 'revenue':
                            value = Decimal(0)
                        db.add(FinancialFact(company_id=company.id, metric=metric,
                            value=value, fiscal_year=year, fiscal_quarter='FY',
                            period=f'FY{year}', source_type='test',
                            created_at=datetime(2026, 1, 1, tzinfo=UTC)+timedelta(seconds=revision)))
            # Newer quarterly data cannot replace an annual row.
            db.add(FinancialFact(company_id=company.id, metric='revenue', value=Decimal('9999'),
                fiscal_year=2030, fiscal_quarter='Q1', period='Q12030', source_type='test'))
        db.commit()
        for reader, reference in [(funnel._earnings_consistency, reference_earnings_consistency),
                                   (funnel._revenue_cagr, reference_revenue_cagr)]:
            assert reader(db) == reference(db)
        for cutoff in [1980, 2024, 2027, 2100]:
            assert gems._latest_fcf_and_shares(db, cutoff) == reference_latest_fcf_and_shares(db, cutoff)
        db.info['tenant_id'] = tenant + 999
        assert funnel._earnings_consistency(db) == reference_earnings_consistency(db) == {}
        assert funnel._revenue_cagr(db) == reference_revenue_cagr(db) == {}
        assert gems._latest_fcf_and_shares(db, 2024) == {}


def test_smart_money_counts_only_increases_with_verified_cusip_and_tenant():
    from datetime import date

    from app.models.entities import FundManager, InstrumentReference, ManagerHolding

    with _db() as db:
        manager = FundManager(cik='TEST13F', name='Manager')
        db.add(manager)
        db.flush()
        prior, latest = date(2026, 3, 31), date(2026, 6, 30)
        for i, (day, shares, put_call) in enumerate([
            (prior, 10, ''), (latest, 20, ''), (latest, 1000, 'CALL'),
        ]):
            db.add(ManagerHolding(manager_id=manager.id, accession_number=f'Q{i}',
                report_date=day, cusip='123456789', shares=Decimal(shares), put_call=put_call))
        db.commit()
        assert gems._smart_money(db, {'X'}) == ({}, latest)
        db.add(InstrumentReference(ticker_normalized='X', cusip='123456789'))
        db.commit()
        assert gems._smart_money(db, {'X'}) == ({'X': 1}, latest)
        # No increase is not a buy signal.
        row = db.query(ManagerHolding).filter(ManagerHolding.accession_number == 'Q1').one()
        row.shares = Decimal('5')
        db.commit()
        assert gems._smart_money(db, {'X'}) == ({'X': 0}, latest)
        db.info['tenant_id'] += 1
        assert gems._smart_money(db, {'X'}) == ({}, None)
