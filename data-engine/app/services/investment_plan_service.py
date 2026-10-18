"""Investment plan tracking and rebalancing drift analysis.

The plan records a monthly contribution target and target allocations by
sector / asset class / ticker with tolerance bands. Drift analysis compares
current market values against targets and returns concrete buy/sell
suggestions to stay inside the bands.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    CashBalance,
    Company,
    InvestmentPlan,
    PlanContribution,
    Position,
)
from app.services.portfolio_fx_service import PortfolioFXService

DEFAULT_BAND = Decimal("0.05")  # ±5 percentage points


class InvestmentPlanService:
    def __init__(self) -> None:
        self.fx = PortfolioFXService()

    def get_plan(self, db: Session) -> InvestmentPlan | None:
        return db.scalar(
            select(InvestmentPlan)
            .order_by(InvestmentPlan.created_at.asc())
            .limit(1)
        )

    def upsert_plan(
        self,
        db: Session,
        *,
        monthly_contribution: Decimal,
        start_date: date,
        horizon_years: int,
        target_allocations: list[dict],
    ) -> InvestmentPlan:
        portfolio = self.fx.ensure_portfolio(db)
        plan = self.get_plan(db)
        if plan is None:
            plan = InvestmentPlan(
                portfolio_id=portfolio.id,
                monthly_contribution=monthly_contribution,
                start_date=start_date,
                horizon_years=horizon_years,
                target_allocations=target_allocations,
                status="active",
            )
            db.add(plan)
        else:
            plan.monthly_contribution = monthly_contribution
            plan.start_date = start_date
            plan.horizon_years = horizon_years
            plan.target_allocations = target_allocations
            plan.status = "active"
        db.commit()
        db.refresh(plan)
        return plan

    def add_contribution(
        self,
        db: Session,
        *,
        date_: date,
        amount: Decimal,
        currency: str = "EUR",
        external_id: str | None = None,
        note: str = "",
    ) -> PlanContribution:
        plan = self.get_plan(db)
        if plan is None:
            raise ValueError("Investment plan does not exist yet; create it first")
        if external_id:
            existing = db.scalar(
                select(PlanContribution).where(
                    PlanContribution.external_id == external_id,
                    PlanContribution.plan_id == plan.id,
                )
            )
            if existing is not None:
                return existing
        contribution = PlanContribution(
            plan_id=plan.id,
            date=date_,
            amount=amount,
            currency=currency,
            external_id=external_id,
            note=note,
        )
        db.add(contribution)
        db.commit()
        db.refresh(contribution)
        return contribution

    def list_contributions(self, db: Session, *, limit: int = 500) -> list[PlanContribution]:
        plan = self.get_plan(db)
        if plan is None:
            return []
        return list(
            db.scalars(
                select(PlanContribution)
                .where(PlanContribution.plan_id == plan.id)
                .order_by(PlanContribution.date)
                .limit(limit)
            )
        )

    def delete_contribution(self, db: Session, contribution_id: int) -> bool:
        contribution = db.get(PlanContribution, contribution_id)
        if contribution is None:
            return False
        db.delete(contribution)
        db.commit()
        return True

    def plan_metrics(self, db: Session) -> dict:
        """Expected contributions vs actual, from plan start to today."""
        plan = self.get_plan(db)
        if plan is None:
            return {"plan_exists": False}
        # F369: sin tope silencioso de filas y con cada aportacion convertida a la
        # divisa base con el FX de su fecha; sin FX no se suma a la par.
        contributions = list(
            db.scalars(
                select(PlanContribution)
                .where(PlanContribution.plan_id == plan.id)
                .order_by(PlanContribution.date)
            )
        )
        portfolio = self.fx.portfolio(db)
        base_currency = portfolio.base_currency.upper() if portfolio else None
        total_actual = Decimal("0")
        missing_fx: list[dict] = []
        for contribution in contributions:
            currency = (contribution.currency or "").upper()
            if base_currency is not None and currency == base_currency:
                total_actual += contribution.amount
                continue
            rate = (
                self.fx.rate(
                    db,
                    quote_currency=currency,
                    base_currency=base_currency,
                    as_of=contribution.date,
                )
                if base_currency is not None
                else None
            )
            if rate is None:
                missing_fx.append(
                    {
                        "contribution_id": contribution.id,
                        "quote_currency": currency,
                        "base_currency": base_currency,
                        "as_of": contribution.date.isoformat(),
                    }
                )
                continue
            total_actual += contribution.amount * rate
        complete = not missing_fx
        months_elapsed = self._months_between(plan.start_date, date.today())
        total_expected = plan.monthly_contribution * Decimal(months_elapsed)
        return {
            "plan_exists": True,
            "base_currency": base_currency,
            "monthly_contribution": float(plan.monthly_contribution),
            "start_date": plan.start_date.isoformat(),
            "horizon_years": plan.horizon_years,
            "months_elapsed": months_elapsed,
            "expected_contributions_base": float(total_expected),
            "actual_contributions_base": float(total_actual) if complete else None,
            "actual_contributions_converted_base": float(total_actual),
            "contributions_complete": complete,
            "contributions_missing_fx": missing_fx,
            "gap_base": float(total_expected - total_actual) if complete else None,
            "on_track": (total_actual >= total_expected) if complete else None,
            "target_allocations": plan.target_allocations,
        }

    def drift_analysis(self, db: Session) -> dict:
        """Current weights vs targets with rebalancing suggestions."""
        plan = self.get_plan(db)
        portfolio = self.fx.portfolio(db)
        if plan is None or portfolio is None:
            return {"plan_exists": False}

        positions = db.execute(
            select(Position, Company).join(Company, Position.company_id == Company.id)
        ).all()
        cash_rows = db.scalars(select(CashBalance)).all()

        cash_total = Decimal("0")
        missing_fx: list[dict] = []
        for row in cash_rows:
            rate = self.fx.rate(
                db,
                quote_currency=row.currency,
                base_currency=portfolio.base_currency,
                as_of=row.as_of,
            )
            if rate is None:
                # Never count unpriced FX at par: exclude and report, same
                # honesty contract as RiskService.dashboard.
                missing_fx.append(
                    {
                        "kind": "cash",
                        "quote_currency": row.currency,
                        "base_currency": portfolio.base_currency,
                        "as_of": row.as_of.isoformat(),
                    }
                )
                continue
            cash_total += row.balance * rate

        by_label: dict[str, Decimal] = {}
        positions_total = Decimal("0")
        for position, company in positions:
            if position.market_value_base is None:
                # F368: una posicion sin valor en divisa base no se descarta en
                # silencio: se registra y la cobertura pasa a parcial.
                missing_fx.append(
                    {
                        "kind": "position",
                        "ticker": company.ticker,
                        "quote_currency": position.currency,
                        "base_currency": portfolio.base_currency,
                        "as_of": position.as_of.isoformat() if position.as_of else None,
                    }
                )
                continue
            value = Decimal(position.market_value_base)
            if value <= 0:
                continue
            positions_total += value
            by_label[company.sector or "Unknown"] = (
                by_label.get(company.sector or "Unknown", Decimal("0")) + value
            )
            by_label[f"ticker:{company.ticker}"] = (
                by_label.get(f"ticker:{company.ticker}", Decimal("0")) + value
            )
        by_label["asset_class:Cash"] = cash_total

        # The portfolio total counts each euro once: sector and ticker are two
        # views of the same positions, so summing every label would double the
        # invested value and distort every weight, deviation and suggestion.
        total = positions_total + cash_total
        current_weights = {
            label: float((value / total * 100).quantize(Decimal("0.01")))
            for label, value in by_label.items()
            if total > 0
        }

        targets = plan.target_allocations or []
        suggestions = []
        deviations = []
        for target in targets:
            kind = target.get("kind", "sector")
            label = target.get("label", "")
            # Weights are keyed sector name / ticker:X / asset_class:Y; the
            # lookup must use the same namespacing or every non-sector target
            # silently reads 0 and suggests buying from nothing.
            key = label if kind == "sector" else f"{kind}:{label}"
            target_pct = Decimal(str(target.get("target_pct", 0)))
            band_pct = Decimal(str(target.get("band_pct", DEFAULT_BAND)))
            current = Decimal(str(current_weights.get(key, 0)))
            deviation = current - target_pct
            lower = target_pct - band_pct
            upper = target_pct + band_pct
            deviations.append(
                {
                    "kind": kind,
                    "label": label,
                    "target_pct": float(target_pct),
                    "band_pct": float(band_pct),
                    "current_pct": float(current),
                    "deviation_pct": float(deviation),
                    "within_band": lower <= current <= upper,
                }
            )
            if current < lower:
                amount = (target_pct - current) / Decimal(100) * total
                suggestions.append(
                    {
                        "kind": kind,
                        "label": label,
                        "direction": "buy",
                        "amount_base": float(amount.quantize(Decimal("0.01"))),
                        "detail": f"{label} esta {float(target_pct - current):+.1f} puntos por debajo del objetivo",
                    }
                )
            elif current > upper:
                amount = (current - target_pct) / Decimal(100) * total
                suggestions.append(
                    {
                        "kind": kind,
                        "label": label,
                        "direction": "sell",
                        "amount_base": float(amount.quantize(Decimal("0.01"))),
                        "detail": f"{label} esta {float(current - target_pct):+.1f} puntos por encima del objetivo",
                    }
                )

        if missing_fx:
            # Con cobertura parcial los pesos y el total no son los de la cartera
            # real: no se publican importes de compra/venta calculados sobre ellos.
            suggestions = []
        return {
            "plan_exists": True,
            "status": "incomplete_fx" if missing_fx else "ok",
            "suggestions_blocked": bool(missing_fx),
            "base_currency": portfolio.base_currency,
            "portfolio_value_base": float(total.quantize(Decimal("0.01"))),
            "cash_base": float(cash_total.quantize(Decimal("0.01"))),
            "missing_fx": missing_fx,
            "current_weights": current_weights,
            "deviations": deviations,
            "suggestions": suggestions,
            "next_contribution": float(plan.monthly_contribution),
        }

    @staticmethod
    def _months_between(start: date, end: date) -> int:
        months = (end.year - start.year) * 12 + (end.month - start.month)
        return max(months, 0)