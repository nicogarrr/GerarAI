"""Source-backed plan notices. In-app only, no orders, no external delivery.

Content-addressed fingerprints persist dismissal: an unchanged state never
reopens an alert. New plan state is a distinct notice. No guessed investment
thresholds, future yields or personal concentration preferences.
"""
from __future__ import annotations

import hashlib
import json
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.tenancy import tenant_filters
from app.models import InvestmentPlan, ResearchAlert
from app.services.review_alert_service import ReviewAlertService
from app.services.savings_projection import savings_contract


def plan_state(plan: InvestmentPlan | None) -> dict | None:
    if plan is None:
        return None
    return {'monthly': str(Decimal(plan.monthly_contribution).quantize(Decimal('.01'))),
        'currency': (plan.monthly_contribution_currency or '').upper() or None,
        'years': plan.horizon_years, 'targets': plan.target_allocations or []}


def emit_plan_notice(db: Session, plan: InvestmentPlan, *, changed: bool = False) -> int | None:
    state = plan_state(plan)
    if not state:
        return None
    missing_currency = not state['currency']
    if not changed and not missing_currency:
        return None
    reason = 'currency_missing' if missing_currency else 'plan_changed'
    digest = hashlib.sha256(json.dumps(state, sort_keys=True, default=str).encode()).hexdigest()
    parts = ['savings_plan', str(plan.id), reason, digest]
    service = ReviewAlertService()
    fingerprint = service.fingerprint_for(db, parts)
    # Do not call emit_alert for a known state: its general contract reopens
    # resolved alerts, which is wrong for a dismissed savings notice.
    existing = db.scalar(select(ResearchAlert).where(
        ResearchAlert.fingerprint == fingerprint, *tenant_filters(db, ResearchAlert)))
    if existing is not None:
        return None
    projection = savings_contract(db)
    title = 'Tu plan necesita una divisa registrada' if missing_currency else 'Tu plan y tus proyecciones se han actualizado'
    message = (
        'La aportación no tiene divisa registrada: no calculamos previsiones monetarias ni asumimos euros. '
        'Revisa el plan antes de interpretar un reparto DCA.' if missing_currency else
        f"Aportación {state['monthly']} {state['currency']} al mes, horizonte {state['years']} años. "
        'Cartera, Cerebro y reparto DCA leen el mismo plan. Revisa los escenarios de ahorro: '
        'son hipótesis, no promesas de rentabilidad ni instrucciones de compra.'
    )
    # Only the current plan state remains open. Dismissed states stay dismissed.
    for old in db.scalars(select(ResearchAlert).where(
        ResearchAlert.alert_type == 'savings_plan_review',
        ResearchAlert.status == 'open', *tenant_filters(db, ResearchAlert))):
        if (old.metadata_ or {}).get('plan_id') == plan.id:
            service.transition_alert(old, action='resolve', actor='savings-plan')
            # ResearchAlert has no resolved_by column. Keep automation provenance
            # in its existing metadata, without changing user acknowledgement.
            old.metadata_ = {**(old.metadata_ or {}), 'resolved_by': 'savings-plan',
                'resolution_reason': 'superseded_plan_state',
                'superseded_by_fingerprint': fingerprint}
    alert = service.emit_alert(db, company_id=None, alert_type='savings_plan_review',
        severity='medium' if missing_currency else 'low', title=title, message=message,
        fingerprint_parts=parts, channels=['in_app'], metadata={
            'source': '/plan', 'projection_url': '/portfolio?tab=prevision',
            'dca_url': '/plan', 'reason': reason, 'plan_id': plan.id,
            'plan_state': state, 'projection_status': projection['status'],
            'portfolio_included': False, 'orders_enabled': False,
        })
    return alert.id


def review_savings_plan(db: Session) -> dict:
    """Daily DCA worker also reviews plan data, without sending email."""
    plan = db.scalar(select(InvestmentPlan).where(*tenant_filters(db, InvestmentPlan))
        .order_by(InvestmentPlan.created_at.asc(), InvestmentPlan.id.asc()).limit(1))
    if plan is None:
        return {'plan_exists': False, 'new_in_app_alerts': 0}
    alert_id = emit_plan_notice(db, plan)
    return {'plan_exists': True, 'new_in_app_alerts': int(alert_id is not None)}
