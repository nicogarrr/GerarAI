"""Dated, in-app portfolio checks. No invented allocation limits or trades."""
from __future__ import annotations

import hashlib
import json
from decimal import Decimal, InvalidOperation

from sqlalchemy import select

from app.core.local_date import local_today
from app.core.tenancy import tenant_filters
from app.models import (
    CashBalance,
    Company,
    InvestmentPlan,
    PortfolioDailySnapshot,
    PositionDailySnapshot,
    ResearchAlert,
)
from app.services.review_alert_service import ReviewAlertService


def _emit(db, *, kind, key, title, message, metadata):
    service = ReviewAlertService()
    fingerprint = service.fingerprint_for(db, ['portfolio_data_review', kind, key])
    if db.scalar(select(ResearchAlert.id).where(ResearchAlert.fingerprint == fingerprint,
            *tenant_filters(db, ResearchAlert))) is not None:
        return 0
    service.emit_alert(db, company_id=None, alert_type='portfolio_data_review', severity='low',
        title=title, message=message, fingerprint_parts=['portfolio_data_review', kind, key],
        channels=['in_app'], metadata={'source': '/portfolio', 'reason': kind,
            'orders_enabled': False, **metadata})
    return 1


def review_portfolio_data(db) -> dict:
    """Read stored data only; no network, no currency conversion, no orders.

    Negative cash is not proof of debt. An allocation warning requires an
    explicit saved ticker target AND band, and a fully priced dated snapshot.
    Historical snapshots are labelled with their date, never called live.
    """
    emitted = 0
    for cash in db.scalars(select(CashBalance).where(*tenant_filters(db, CashBalance))):
        if cash.balance is None or cash.balance >= 0 or cash.as_of > local_today():  # día de Madrid
            continue
        currency = (cash.currency or '').upper()
        if not currency:
            continue
        # Same recorded amount does not alert again just because its date changes.
        key = f'{currency}:{cash.balance}'
        emitted += _emit(db, kind='negative_cash_record', key=key,
            title=f'Revisa la caja registrada en {currency}',
            message=f'Hay un saldo de {cash.balance} {currency} fechado {cash.as_of.isoformat()} '
                f'(fuente {cash.source}). Puede ser margen, un apunte pendiente o un dato antiguo: '
                'no confirma deuda ni caja disponible hoy. Concílialo con tu broker antes de interpretar compras o el plan.',
            metadata={'currency': currency, 'recorded_balance': str(cash.balance),
                'as_of': cash.as_of.isoformat(), 'record_source': cash.source,
                'current_balance_verified': False, 'debt_confirmed': False})
    plan = db.scalar(select(InvestmentPlan).where(*tenant_filters(db, InvestmentPlan))
        .order_by(InvestmentPlan.created_at.asc(), InvestmentPlan.id.asc()).limit(1))
    if plan is None:
        return {'new_in_app_alerts': emitted, 'concentration_status': 'no_plan'}
    snapshot = db.scalar(select(PortfolioDailySnapshot).where(
        PortfolioDailySnapshot.portfolio_id == plan.portfolio_id,
        PortfolioDailySnapshot.snapshot_date <= local_today(),
        *tenant_filters(db, PortfolioDailySnapshot))
        .order_by(PortfolioDailySnapshot.snapshot_date.desc(), PortfolioDailySnapshot.id.desc()).limit(1))
    if snapshot is None or snapshot.pricing_coverage != Decimal('1') or snapshot.total_value_base <= 0:
        return {'new_in_app_alerts': emitted, 'concentration_status': 'incomplete_snapshot'}
    rows = db.execute(select(PositionDailySnapshot, Company.ticker).join(Company,
        Company.id == PositionDailySnapshot.company_id).where(
        PositionDailySnapshot.portfolio_snapshot_id == snapshot.id,
        *tenant_filters(db, PositionDailySnapshot))).all()
    if not rows or any(row.market_value_base is None or row.snapshot_date != snapshot.snapshot_date for row, _ in rows):
        return {'new_in_app_alerts': emitted, 'concentration_status': 'incomplete_snapshot'}
    values = {}
    for row, ticker in rows:
        values[ticker.upper()] = values.get(ticker.upper(), Decimal('0')) + row.market_value_base
    explicit_targets = 0
    for target in plan.target_allocations or []:
        if target.get('kind') != 'ticker' or 'target_pct' not in target or 'band_pct' not in target:
            continue
        ticker = str(target.get('label') or '').strip().upper()
        try:
            target_pct, band = Decimal(str(target['target_pct'])), Decimal(str(target['band_pct']))
        except (InvalidOperation, ValueError):
            continue
        if not ticker or not target_pct.is_finite() or not band.is_finite() or not 0 <= target_pct <= 100 or not 0 <= band <= 50:
            continue
        explicit_targets += 1
        current = values.get(ticker, Decimal('0')) / snapshot.total_value_base * 100
        if current <= target_pct + band:
            continue
        config = {'plan_id': plan.id, 'ticker': ticker, 'target_pct': str(target_pct), 'band_pct': str(band)}
        key = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
        emitted += _emit(db, kind='above_saved_ticker_band', key=key,
            title=f'{ticker} supera la banda que guardaste en el plan',
            message=f'En la foto del {snapshot.snapshot_date.isoformat()}, {ticker} pesa {current:.2f}% '
                f'sobre patrimonio neto con caja ({snapshot.base_currency}). Tu objetivo guardado es '
                f'{target_pct}% con banda de {band} puntos. Revisa el reparto y los datos; '
                'no es una orden de venta ni un límite de inversión recomendado.',
            metadata={**config, 'snapshot_id': snapshot.id, 'as_of': snapshot.snapshot_date.isoformat(),
                'weight_pct': str(current), 'weight_basis': 'nav_with_cash',
                'base_currency': snapshot.base_currency, 'plan_url': '/plan',
                'snapshot_is_live': False})
    return {'new_in_app_alerts': emitted,
        'concentration_status': 'reviewed_explicit_targets' if explicit_targets else 'no_explicit_ticker_band'}
