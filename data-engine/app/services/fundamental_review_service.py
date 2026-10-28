from __future__ import annotations

import re
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.core.database import batch_refresh
from app.models import (
    CalculatedMetric,
    Company,
    DecisionJournalEntry,
    ExpectationReview,
    FinancialFact,
    FundamentalForecast,
    FundamentalModelVersion,
    MarketPrice,
)
from app.services.claim_scope import latest_thesis_version
from app.services.metric_semantics import MetricSemanticsRegistry


class DecisionJournalService:
    def create(
        self,
        db: Session,
        company: Company,
        *,
        decision: str,
        rationale: str,
        what_must_be_true: list[str],
        transaction_id: int | None = None,
    ) -> DecisionJournalEntry:
        from app.services.journal_trade_link import resolve_decision_trade

        # La operacion se valida ANTES de escribir nada (ValueError -> 422).
        trade = resolve_decision_trade(db, company, transaction_id, decision) if transaction_id else None
        thesis = latest_thesis_version(db, company)
        model = db.scalar(
            select(FundamentalModelVersion)
            .where(FundamentalModelVersion.company_id == company.id)
            .order_by(desc(FundamentalModelVersion.version))
            .limit(1)
        )
        price = db.scalar(
            select(MarketPrice)
            .where(MarketPrice.company_id == company.id)
            .order_by(desc(MarketPrice.date))
            .limit(1)
        )
        entry = DecisionJournalEntry(
            company_id=company.id,
            thesis_version_id=thesis.id if thesis else None,
            model_version_id=model.id if model else None,
            decision=decision,
            rationale=rationale,
            what_must_be_true=what_must_be_true,
            price=price.close if price else None,
            metadata_={
                "thesis_version": thesis.version if thesis else None,
                "model_version": model.version if model else None,
            },
        )
        if trade is not None:
            # Decision ejecutada: su fecha y su precio son los de la operacion.
            entry.transaction_id = trade.id
            entry.decision_date = trade.trade_date
            entry.price = trade.price
        db.add(entry)
        db.commit()
        db.refresh(entry)
        if trade is None:
            # Decision de compra/venta sin operacion indicada: si ya existe UNA
            # operacion inequivoca (p. ej. importada de IBKR), se enlaza sola.
            from app.services.journal_trade_link import auto_link_journal_trades_best_effort

            auto_link_journal_trades_best_effort(db, {company.id})
            db.refresh(entry)
        return entry

    def link_transaction(
        self,
        db: Session,
        company: Company,
        entry_id: int,
        transaction_id: int | None,
    ) -> DecisionJournalEntry:
        """Enlaza (o desenlaza con None) una entrada existente a una operacion.

        No reescribe la fecha ni el precio de la decision: la entrada ya
        existia y su fecha es la de la decision, no la de la ejecucion.
        """
        from app.services.journal_trade_link import resolve_decision_trade

        entry = db.scalar(
            select(DecisionJournalEntry).where(
                DecisionJournalEntry.id == entry_id,
                DecisionJournalEntry.company_id == company.id,
            )
        )
        if entry is None:
            raise LookupError("Entrada del diario no encontrada")
        entry.transaction_id = (
            resolve_decision_trade(db, company, transaction_id, entry.decision).id
            if transaction_id else None
        )
        if transaction_id is None:
            # Desenlazar a mano es una decision del usuario: no se vuelve a
            # enlazar automaticamente.
            meta = dict(entry.metadata_ or {})
            meta["auto_link"] = {"status": "user_unlinked"}
            entry.metadata_ = meta
        else:
            meta = dict(entry.metadata_ or {})
            meta.pop("auto_link", None)
            entry.metadata_ = meta
        db.commit()
        db.refresh(entry)
        return entry

    def list(self, db: Session, company: Company) -> list[DecisionJournalEntry]:
        return list(
            db.scalars(
                select(DecisionJournalEntry)
                .where(DecisionJournalEntry.company_id == company.id)
                .order_by(
                    desc(DecisionJournalEntry.decision_date),
                    desc(DecisionJournalEntry.id),
                )
            ).all()
        )


class ExpectationRealityService:
    def review(self, db: Session, company: Company) -> list[ExpectationReview]:
        rows = list(
            db.execute(
                select(FundamentalForecast, FundamentalModelVersion)
                .join(
                    FundamentalModelVersion,
                    FundamentalModelVersion.id == FundamentalForecast.model_version_id,
                )
                .where(
                    FundamentalModelVersion.company_id == company.id,
                    FundamentalForecast.scenario == "base",
                )
                .order_by(
                    FundamentalForecast.fiscal_year,
                    FundamentalForecast.metric,
                    FundamentalModelVersion.created_at,
                )
            ).all()
        )
        grouped: dict[
            tuple[int, str], list[tuple[FundamentalForecast, FundamentalModelVersion]]
        ] = {}
        for forecast, model in rows:
            grouped.setdefault((forecast.fiscal_year, forecast.metric), []).append(
                (forecast, model)
            )
        # Batch-fetch actuals once: two queries total instead of two per
        # (year, metric) group, then pick the latest per group in Python.
        group_keys = set(grouped)
        metrics = {metric for _, metric in group_keys}
        years = {fiscal_year for fiscal_year, _ in group_keys}
        fact_rows = db.scalars(
            select(FinancialFact)
            .where(
                FinancialFact.company_id == company.id,
                FinancialFact.metric.in_(metrics),
                FinancialFact.fiscal_year.in_(years),
            )
            .order_by(desc(FinancialFact.created_at), desc(FinancialFact.id))
        ).all()
        facts_by_key: dict[tuple[int, str], FinancialFact] = {}
        for row in fact_rows:
            key = (row.fiscal_year, row.metric)
            # Los forecasts son anuales: un trimestre no es un actual comparable.
            if key in group_keys and self._is_annual_period(row):
                facts_by_key.setdefault(key, row)
        metric_rows = db.scalars(
            select(CalculatedMetric)
            .where(
                CalculatedMetric.company_id == company.id,
                CalculatedMetric.metric.in_(metrics),
                CalculatedMetric.fiscal_year.in_(years),
                CalculatedMetric.value.is_not(None),
            )
            .order_by(desc(CalculatedMetric.created_at), desc(CalculatedMetric.id))
        ).all()
        metrics_by_key: dict[tuple[int, str], CalculatedMetric] = {}
        for row in metric_rows:
            key = (row.fiscal_year, row.metric)
            if key in group_keys and self._is_annual_period(row):
                metrics_by_key.setdefault(key, row)

        # First pass: pure eligibility per group against the prefetched
        # actuals, so reviews can also be batch-fetched in one query.
        selected: list[tuple[tuple[int, str], object, FundamentalForecast, FundamentalModelVersion]] = []
        for key, candidates in grouped.items():
            actual = self._preferred_actual(facts_by_key.get(key), metrics_by_key.get(key))
            actual_created_at = actual.created_at if actual is not None else None
            eligible = [
                item
                for item in candidates
                if actual_created_at is None
                or self._is_before(item[1].created_at, actual_created_at)
            ]
            if not eligible:
                # A model created after the result is known is not a forecast.
                continue
            forecast, model = eligible[-1]
            selected.append((key, actual, forecast, model))

        review_rows = db.scalars(
            select(ExpectationReview).where(
                ExpectationReview.forecast_id.in_(
                    [forecast.id for _, _, forecast, _ in selected]
                )
            )
        ).all() if selected else []
        reviews_by_forecast: dict[int, ExpectationReview] = {}
        for row in review_rows:
            reviews_by_forecast.setdefault(row.forecast_id, row)

        reviews: list[ExpectationReview] = []
        for (fiscal_year, metric), actual, forecast, model in selected:
            review = reviews_by_forecast.get(forecast.id)
            if review is None:
                review = ExpectationReview(
                    company_id=company.id,
                    model_version_id=model.id,
                    forecast_id=forecast.id,
                    fiscal_year=forecast.fiscal_year,
                    metric=forecast.metric,
                    expected_value=forecast.value,
                    semantics=MetricSemanticsRegistry.get(metric).direction,
                    status="pending_actual",
                )
                db.add(review)

            if actual is None:
                review.status = "pending_actual"
                review.actual_fact_id = None
                review.actual_metric_id = None
                review.actual_source_type = None
                review.actual_value = None
                review.variance = None
                review.variance_percent = None
            else:
                actual_value = Decimal(actual.value)
                variance = actual_value - forecast.value
                status, variance_percent = MetricSemanticsRegistry.classify(
                    metric, forecast.value, actual_value
                )
                is_calculated = isinstance(actual, CalculatedMetric)
                review.actual_fact_id = None if is_calculated else actual.id
                review.actual_metric_id = actual.id if is_calculated else None
                review.actual_source_type = (
                    "calculated_metric" if is_calculated else "financial_fact"
                )
                review.actual_value = actual_value
                review.variance = variance
                review.variance_percent = variance_percent
                rule = MetricSemanticsRegistry.get(metric)
                review.semantics = rule.direction
                review.status = status
                review.trace = {
                    "tolerance": str(rule.tolerance),
                    "semantics": rule.direction,
                    "actual_source_type": (
                        "calculated_metric"
                        if is_calculated
                        else actual.source_type
                    ),
                    "actual_period": actual.period,
                    "selection_policy": "latest model created before actual",
                    "forecast_model_created_at": model.created_at.isoformat(),
                    "actual_created_at": actual.created_at.isoformat(),
                }
            review.reviewed_at = datetime.now(UTC)
            reviews.append(review)
        db.commit()
        batch_refresh(db, reviews)
        return reviews

    @staticmethod
    def _is_annual_period(row: FinancialFact | CalculatedMetric) -> bool:
        quarter = (getattr(row, "fiscal_quarter", None) or "").strip().upper()
        period = (row.period or "").strip().upper()
        return quarter == "FY" or bool(
            re.fullmatch(r"(.*:)?(FY\d{0,4}|ANNUAL|\d{4}:FY)", period)
        )

    @staticmethod
    def _preferred_actual(
        fact: FinancialFact | None,
        metric: CalculatedMetric | None,
    ) -> FinancialFact | CalculatedMetric | None:
        if fact is None:
            return metric
        if metric is None:
            return fact
        # Raw reported observations win ties; otherwise use the newest canonical value.
        return fact if fact.created_at >= metric.created_at else metric

    @staticmethod
    def _is_before(model_time: datetime, actual_time: datetime) -> bool:
        model_value = model_time.replace(tzinfo=None)
        actual_value = actual_time.replace(tzinfo=None)
        return model_value < actual_value

    def list(self, db: Session, company: Company) -> list[ExpectationReview]:
        return list(
            db.scalars(
                select(ExpectationReview)
                .where(ExpectationReview.company_id == company.id)
                .order_by(
                    desc(ExpectationReview.fiscal_year),
                    ExpectationReview.metric,
                )
            ).all()
        )
