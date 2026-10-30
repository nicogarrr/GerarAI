"""Investment plan tracking and rebalancing drift analysis.

The plan records a monthly contribution target and target allocations by
sector / asset class / ticker with tolerance bands. Drift analysis compares
current market values against targets and returns concrete buy/sell
suggestions to stay inside the bands.
"""

from __future__ import annotations

import os
from calendar import monthrange
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.local_date import local_today
from app.models import (
    CashBalance,
    Company,
    InvestmentPlan,
    PlanContribution,
    Position,
)
from app.services.portfolio_fx_service import PortfolioFXService


class ContributionConflict(ValueError):
    """An import key already identifies a different recorded contribution."""


DEFAULT_BAND = Decimal("0.05")  # ±5 percentage points

# Omiso != None: un cliente viejo que OMITE la divisa no debe borrar la ya
# registrada al actualizar; un None EXPLICITO si la desregistra (queda como
# legacy «divisa no registrada»).
PLAN_CURRENCY_UNSET: Any = object()


def plan_currency_enforced() -> bool:
    """Capability «contrato de divisa del plan» (default OFF, solo dev).

    ON: la divisa de la cuota se registra y los totales previstos se
    convierten por cuota. OFF: contrato anterior (cuota == divisa base) SOLO
    donde es seguro: plan sin divisa registrada o con divisa == base. Un plan
    con divisa registrada distinta de la base NUNCA se reinterpreta como base:
    sus totales quedan null con expected_basis=blocked_contract_disabled. Las
    escrituras con divisa explicita se rechazan (409) en vez de ignorarse.
    """
    return os.getenv("PLAN_CURRENCY_ENFORCED") == "1"


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
        monthly_contribution_currency: Any = PLAN_CURRENCY_UNSET,
    ) -> InvestmentPlan:
        portfolio = self.fx.ensure_portfolio(db)
        plan = self.get_plan(db)
        from app.services.plan_proactivity import emit_plan_notice, plan_state
        previous_state = plan_state(plan)
        if plan is None:
            plan = InvestmentPlan(
                portfolio_id=portfolio.id,
                monthly_contribution=monthly_contribution,
                # Plan nuevo via cliente viejo (omiso) o null explicito:
                # NULL = «divisa no registrada», nunca se inventa una.
                monthly_contribution_currency=(
                    None
                    if monthly_contribution_currency is PLAN_CURRENCY_UNSET
                    else monthly_contribution_currency
                ),
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
            if monthly_contribution_currency is not PLAN_CURRENCY_UNSET:
                plan.monthly_contribution_currency = monthly_contribution_currency
            plan.status = "active"
        db.flush()
        emit_plan_notice(db, plan, changed=previous_state != plan_state(plan))
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
        # Normalize before BOTH persistence and retry comparison. Letting the
        # DB/driver round a float first differs at half cents across backends.
        amount = amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        # Una divisa en minusculas es la misma divisa: se guarda normalizada
        # para que el reintento con la misma referencia no sea un «conflicto».
        currency = (currency or "").strip().upper()
        if amount <= 0:
            raise ValueError("El importe de la aportación debe ser positivo con precisión de céntimos.")
        # Una aportación futura contaría hoy como dinero ya aportado («En camino»
        # adelantado) y leería una tasa de cambio que aún no existe. Un día de
        # margen: el usuario en Madrid puede ir por delante del reloj del servidor.
        if date_ > date.today() + timedelta(days=1):
            raise ValueError("La fecha de la aportación no puede ser futura.")
        plan = self.get_plan(db)
        if plan is None:
            raise ValueError("Investment plan does not exist yet; create it first")
        # Una referencia vacía o en blanco no identifica nada: se guarda NULL
        # (el UNIQUE tenant/plan/external_id no choca con NULL). Antes se
        # guardaba "" y la segunda aportación manual sin referencia daba 500.
        external_id = (external_id or "").strip() or None
        if external_id:
            existing = db.scalar(
                select(PlanContribution).where(
                    PlanContribution.external_id == external_id,
                    PlanContribution.plan_id == plan.id,
                )
            )
            if existing is not None:
                # Compare at the stored monetary precision, but do not rewrite
                # historical rows or reinterpret currency units/case.
                if (
                    existing.date != date_
                    or existing.amount != amount
                    or existing.currency != currency
                ):
                    raise ContributionConflict(
                        "La referencia ya identifica otra aportación con fecha, importe o divisa distintos."
                    )
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

    def plan_metrics(self, db: Session, *, today: date | None = None) -> dict:
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
        # «Este mes» es el del usuario (Europe/Madrid), no el día UTC del servidor:
        # entre las 00:00 y las 02:00 del día 1 en Madrid la cuota nueva ya cuenta.
        today = today or local_today()
        months_elapsed = self._months_between(plan.start_date, today)
        plan_currency = (plan.monthly_contribution_currency or "").upper() or None
        enforced = plan_currency_enforced()
        if enforced:
            expected, expected_partial, expected_missing_fx, expected_periods = (
                self._expected_base(
                    db,
                    plan=plan,
                    plan_currency=plan_currency,
                    base_currency=base_currency,
                    months_elapsed=months_elapsed,
                    today=today,
                )
            )
            expected_basis = "plan_currency" if plan_currency else "unknown_currency"
        elif plan_currency is not None and plan_currency != base_currency:
            # Capability OFF con divisa registrada distinta de la base: el
            # contrato anterior no puede representarla. Bloqueo honesto.
            expected, expected_partial, expected_missing_fx, expected_periods = (
                None, None, [], [],
            )
            expected_basis = "blocked_contract_disabled"
        else:
            # Contrato anterior, seguro aqui: sin divisa registrada o == base.
            legacy_total = plan.monthly_contribution * Decimal(
                self._due_periods(plan.start_date, today, months_elapsed)
            )
            expected, expected_partial = legacy_total, legacy_total
            expected_missing_fx, expected_periods = [], []
            expected_basis = "legacy_monthly_as_base"
        totals_known = expected is not None
        return {
            "plan_exists": True,
            "base_currency": base_currency,
            "monthly_contribution": float(plan.monthly_contribution),
            "monthly_contribution_currency": plan_currency,
            # False = plan legacy o dado de alta por API vieja: la divisa es
            # DESCONOCIDA y los totales quedan sin inventar hasta que el
            # usuario la fije conscientemente.
            "monthly_currency_recorded": plan_currency is not None,
            "currency_contract_enabled": enforced,
            "expected_basis": expected_basis,
            "start_date": plan.start_date.isoformat(),
            "horizon_years": plan.horizon_years,
            "months_elapsed": months_elapsed,
            "expected_contributions_base": float(expected) if totals_known else None,
            "expected_contributions_converted_base": (
                float(expected_partial) if expected_partial is not None else None
            ),
            "expected_missing_fx": expected_missing_fx,
            "expected_periods": expected_periods,
            "expected_conversion_complete": expected is not None,
            "actual_contributions_base": float(total_actual) if complete else None,
            "actual_contributions_converted_base": float(total_actual),
            "contributions_complete": complete,
            "contributions_missing_fx": missing_fx,
            "gap_base": (
                float(expected - total_actual) if totals_known and complete else None
            ),
            "on_track": (
                (total_actual >= expected) if totals_known and complete else None
            ),
            "target_allocations": plan.target_allocations,
        }

    def _expected_base(
        self,
        db: Session,
        *,
        plan: InvestmentPlan,
        plan_currency: str | None,
        base_currency: str | None,
        months_elapsed: int,
        today: date,
    ) -> tuple[Decimal | None, Decimal | None, list[dict], list[dict]]:
        """Cuotas previstas en divisa base, con tri-estado honesto.

        - Sin divisa registrada (legacy): (None, None, []). El total no se
          inventa.
        - Divisa del plan == base: la multiplicacion de siempre, sin FX.
        - Divisa distinta: conversion POR PERIODO en el aniversario mensual
          de start_date (clamp a fin de mes; la fecha se acota a hoy para no
          leer tasas con lookahead). Un periodo sin tasa no suma y se
          declara en expected_missing_fx; el total queda None (nunca un
          parcial disfrazado de completo, espejo de las aportaciones).
        """
        periods: list[dict] = []
        if plan_currency is None or base_currency is None:
            return None, None, [], periods
        if plan_currency == base_currency:
            # Compat: monthly x meses de CALENDARIO (months_elapsed), igual
            # que siempre; no depende del dia de vencimiento.
            total = plan.monthly_contribution * Decimal(
                self._due_periods(plan.start_date, today, months_elapsed)
            )
            return total, total, [], periods
        total = Decimal("0")
        missing: list[dict] = []
        for period in range(1, months_elapsed + 1):
            due_date = self._add_months_clamped(plan.start_date, period)
            if due_date > today:
                # Cuota contada por el calendario pero aun no vencida: no se
                # convierte (ni FX futura ni la tasa de hoy atribuida a una
                # fecha futura). Estado propio, distinto de «falta tasa».
                periods.append(
                    {
                        "period": period,
                        "due_date": due_date.isoformat(),
                        "status": "pending_due_date",
                        "rate_date": None,
                        "rate": None,
                        "source": None,
                    }
                )
                continue
            found = self.fx.rate_with_provenance(
                db,
                quote_currency=plan_currency,
                base_currency=base_currency,
                as_of=due_date,
            )
            rate = found["rate"] if found else None
            if rate is None:
                missing.append(
                    {
                        "period": period,
                        "due_date": due_date.isoformat(),
                        "reason": "no_rate_on_or_before_due_date",
                        "quote_currency": plan_currency,
                        "base_currency": base_currency,
                    }
                )
                periods.append(
                    {
                        "period": period,
                        "due_date": due_date.isoformat(),
                        "status": "missing_rate",
                        "rate_date": None,
                        "rate": None,
                        "source": None,
                    }
                )
                continue
            assert found is not None  # rate no es None => hubo cotizacion
            total += plan.monthly_contribution * rate
            periods.append(
                {
                    "period": period,
                    "due_date": due_date.isoformat(),
                    "status": "converted",
                    "rate_date": (
                        found["rate_date"].isoformat() if found["rate_date"] else None
                    ),
                    "rate": float(rate),
                    "source": found["source"],
                    "direction": found["direction"],
                }
            )
        if missing:
            return None, total, missing, periods
        # Una cuota con aniversario futuro aun no es exigible (igual que la via
        # sin FX, `_due_periods`): queda listada como pending_due_date pero no
        # bloquea el total. Antes dejaba «En camino» en N/D casi todo el mes.
        return total, total, [], periods

    @staticmethod
    def _add_months_clamped(anchor: date, months: int) -> date:
        """Aniversario mensual de ``anchor``: mismo dia, clamp a fin de mes
        (31 de enero a 28/29 de febrero)."""
        month_index = anchor.month - 1 + months
        year = anchor.year + month_index // 12
        month = month_index % 12 + 1
        last_day = monthrange(year, month)[1]
        return date(year, month, min(anchor.day, last_day))

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
        sector_order: list[str] = []
        tickers_by_sector: dict[str, list[str]] = {}
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
            sector = company.sector or "Unknown"
            if sector not in by_label:
                sector_order.append(sector)
            tickers_by_sector.setdefault(sector, [])
            if company.ticker not in tickers_by_sector[sector]:
                tickers_by_sector[sector].append(company.ticker)
            by_label[sector] = by_label.get(sector, Decimal("0")) + value
            by_label[f"ticker:{company.ticker}"] = (
                by_label.get(f"ticker:{company.ticker}", Decimal("0")) + value
            )
        by_label["asset_class:Cash"] = cash_total

        # The portfolio total counts each euro once: sector and ticker are two
        # views of the same positions, so summing every label would double the
        # invested value and distort every weight, deviation and suggestion.
        total = positions_total + cash_total
        # Orden de lectura: cada sector seguido de SUS tickers. Con el orden de
        # insercion un ticker de un sector ya visto (MSFT de Tecnologia tras
        # Servicios financieros) quedaba visualmente dentro del grupo equivocado.
        ordered_labels: list[str] = []
        for sector in sector_order:
            if sector in by_label:
                ordered_labels.append(sector)
                ordered_labels.extend(
                    f"ticker:{ticker}" for ticker in tickers_by_sector[sector] if f"ticker:{ticker}" in by_label
                )
        ordered_labels.extend(label for label in by_label if label.startswith("asset_class:"))
        current_weights = {
            label: float((by_label[label] / total * 100).quantize(Decimal("0.01")))
            for label in ordered_labels
            if total > 0
        }

        targets = plan.target_allocations or []
        suggestions = []
        deviations = []
        # Un objetivo por ticker guardado en minusculas («nvda») tambien es NVDA:
        # sin esto leia 0 % y sugeria comprar una posicion que ya existe.
        ticker_weights_ci = {
            "ticker:" + label.removeprefix("ticker:").upper(): weight
            for label, weight in current_weights.items()
            if label.startswith("ticker:")
        }
        for target in targets:
            kind = target.get("kind", "sector")
            label = target.get("label", "")
            # Weights are keyed sector name / ticker:X / asset_class:Y; the
            # lookup must use the same namespacing or every non-sector target
            # silently reads 0 and suggests buying from nothing.
            key = label if kind == "sector" else f"{kind}:{label}"
            target_pct = Decimal(str(target.get("target_pct", 0)))
            band_pct = Decimal(str(target.get("band_pct", DEFAULT_BAND)))
            weight = current_weights.get(key)
            if weight is None and kind == "ticker":
                weight = ticker_weights_ci.get(f"ticker:{str(label).strip().upper()}")
            current = Decimal(str(weight if weight is not None else 0))
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
                        "detail": f"{label} está {float(target_pct - current):.1f} puntos por debajo del objetivo",
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
                        "detail": f"{label} está {float(current - target_pct):.1f} puntos por encima del objetivo",
                    }
                )

        empty_portfolio = total <= 0 and not missing_fx
        if empty_portfolio:
            # Cartera vacia: no hay nada que reequilibrar y cada sugerencia
            # saldria con importe 0. El reparto de la cuota del mes lo da
            # /api/plan/contribution-split.
            suggestions = []
        if missing_fx:
            # Con cobertura parcial los pesos y el total no son los de la cartera
            # real: no se publican importes de compra/venta calculados sobre ellos.
            suggestions = []
        registered_currency = (plan.monthly_contribution_currency or "").upper() or None
        # Capability OFF con divisa registrada distinta de la base: el valor
        # crudo no se presenta como importe en divisa base.
        next_blocked = (
            not plan_currency_enforced()
            and registered_currency is not None
            and registered_currency != portfolio.base_currency.upper()
        )
        return {
            "plan_exists": True,
            "status": "incomplete_fx" if missing_fx else "empty_portfolio" if empty_portfolio else "ok",
            "suggestions_blocked": bool(missing_fx),
            "base_currency": portfolio.base_currency,
            "portfolio_value_base": float(total.quantize(Decimal("0.01"))),
            "cash_base": float(cash_total.quantize(Decimal("0.01"))),
            "missing_fx": missing_fx,
            "current_weights": current_weights,
            "deviations": deviations,
            "suggestions": suggestions,
            "next_contribution": (
                None if next_blocked else float(plan.monthly_contribution)
            ),
            "next_contribution_basis": (
                "blocked_contract_disabled" if next_blocked else "plan_value"
            ),
            # La cuota es en la divisa DEL PLAN (o desconocida si legacy):
            # nunca se presenta como divisa base.
            "next_contribution_currency": (
                (plan.monthly_contribution_currency or "").upper() or None
            ),
        }

    def _due_periods(self, start: date, today: date, months_elapsed: int) -> int:
        """Cuotas ya VENCIDAS: la del mes en curso cuenta solo desde su aniversario.

        months_elapsed son meses de calendario; si el aniversario mensual de
        start_date (con clamp a fin de mes) aun no ha llegado, esa cuota esta
        pendiente y no se exige. Misma regla que la via con conversion FX.
        """
        if months_elapsed > 0 and self._add_months_clamped(start, months_elapsed) > today:
            return months_elapsed - 1
        return months_elapsed

    @staticmethod
    def _months_between(start: date, end: date) -> int:
        months = (end.year - start.year) * 12 + (end.month - start.month)
        return max(months, 0)