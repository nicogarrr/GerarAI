from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, desc, select
from sqlalchemy.orm import Session

from app.core.tenancy import tenant_filters
from app.models import (
    CashBalance,
    CashDailySnapshot,
    FxConversion,
    PortfolioDailySnapshot,
    Position,
    PositionDailySnapshot,
    Transaction,
)
from app.services.portfolio_fx_service import PortfolioFXService, currency_key


class PortfolioSnapshotService:
    """Persist end-of-day position, cash and valuation inputs for reproducible returns."""

    def __init__(self) -> None:
        self.fx = PortfolioFXService()

    def capture(
        self,
        db: Session,
        *,
        as_of: date | None = None,
        source: str = "market_refresh",
    ) -> PortfolioDailySnapshot:
        snapshot_date = as_of or date.today()
        portfolio = self.fx.ensure_portfolio(db)
        db.flush()  # autoflush=False: incluir posiciones/caja pendientes del caller
        positions = list(
            db.scalars(
                select(Position)
                .where(Position.portfolio_id == portfolio.id)
                .order_by(Position.company_id)
            ).all()
        )
        cash_rows = list(db.scalars(select(CashBalance).order_by(CashBalance.currency)).all())
        existing = db.scalar(
            select(PortfolioDailySnapshot).where(
                PortfolioDailySnapshot.portfolio_id == portfolio.id,
                PortfolioDailySnapshot.snapshot_date == snapshot_date,
            )
        )
        if existing:
            db.execute(
                delete(PositionDailySnapshot).where(
                    PositionDailySnapshot.portfolio_snapshot_id == existing.id
                )
            )
            db.execute(
                delete(CashDailySnapshot).where(
                    CashDailySnapshot.portfolio_snapshot_id == existing.id
                )
            )
            snapshot = existing
        else:
            snapshot = PortfolioDailySnapshot(
                portfolio_id=portfolio.id,
                snapshot_date=snapshot_date,
                base_currency=portfolio.base_currency,
                positions_value_base=Decimal("0"),
                cash_value_base=Decimal("0"),
                total_value_base=Decimal("0"),
                metadata_={},
            )
            db.add(snapshot)
            db.flush()

        position_values: list[tuple[Position, Decimal | None, Decimal | None]] = []
        positions_value = Decimal("0")
        missing_pricing: list[dict[str, Any]] = []
        # Lote FX: 1 query para todas las posiciones (anti N+1).
        position_rates = self.fx.rates_for(
            db,
            quote_currencies={position.currency for position in positions},
            base_currency=portfolio.base_currency,
            as_of=snapshot_date,
        )
        for position in positions:
            native = position.quantity * position.market_price
            rate = position_rates.get(currency_key(position.currency))
            base = native * rate if rate is not None and position.market_price > 0 else None
            if base is None or position.as_of != snapshot_date or position.valuation_hold_reason:
                missing_pricing.append(
                    {
                        "company_id": position.company_id,
                        "currency": position.currency,
                        "valuation_date": position.as_of.isoformat(),
                    }
                )
            else:
                positions_value += base
            position_values.append((position, rate, base))

        cash_values: list[tuple[CashBalance, Decimal | None, Decimal | None]] = []
        cash_value = Decimal("0")
        # Lote FX: 1 query para todas las cajas (anti N+1).
        cash_rates = self.fx.rates_for(
            db,
            quote_currencies={cash.currency for cash in cash_rows},
            base_currency=portfolio.base_currency,
            as_of=snapshot_date,
        )
        cash_carried_forward: list[dict[str, Any]] = []
        for cash in cash_rows:
            rate = cash_rates.get(currency_key(cash.currency))
            base = cash.balance * rate if rate is not None else None
            carried = (
                base is not None
                and cash.as_of < snapshot_date
                and self._cash_unchanged_since(db, portfolio.id, cash.as_of, snapshot_date)
            )
            if carried:
                cash_carried_forward.append(
                    {"cash_currency": cash.currency, "valuation_date": cash.as_of.isoformat()}
                )
            if base is None or (cash.as_of != snapshot_date and not carried):
                missing_pricing.append(
                    {
                        "cash_currency": cash.currency,
                        "valuation_date": cash.as_of.isoformat(),
                    }
                )
            else:
                cash_value += base
            cash_values.append((cash, rate, base))

        total_value = positions_value + cash_value
        previous = db.scalar(
            select(PortfolioDailySnapshot)
            .where(
                PortfolioDailySnapshot.portfolio_id == portfolio.id,
                PortfolioDailySnapshot.snapshot_date < snapshot_date,
            )
            .order_by(desc(PortfolioDailySnapshot.snapshot_date))
            .limit(1)
        )
        net_flow, ambiguous_flows = self._external_flows(
            db,
            portfolio_id=portfolio.id,
            as_of=snapshot_date,
            base_currency=portfolio.base_currency,
            after=previous.snapshot_date if previous else None,
        )
        observations = len(position_values) + len(cash_values)
        pricing_coverage = Decimal(observations - len(missing_pricing)) / Decimal(
            observations or 1
        )
        daily_return: Decimal | None = None
        cumulative_twr: Decimal | None = None
        interval_days = (snapshot_date - previous.snapshot_date).days if previous else None
        intermediate_flows = 0
        if previous is not None and interval_days and interval_days > 1:
            # Flujos en dias sin foto: sin valoracion en ese punto no se puede
            # enlazar sub-periodos; se bloquea el retorno en vez de aproximarlo.
            intermediate_flows = len(
                db.scalars(
                    select(Transaction.id).where(
                        Transaction.portfolio_id == portfolio.id,
                        Transaction.trade_date > previous.snapshot_date,
                        Transaction.trade_date < snapshot_date,
                        Transaction.action.in_(["deposit", "withdrawal", "cash_misc"]),
                        *tenant_filters(db, Transaction),
                    )
                ).all()
            )
        previous_is_base = False
        if previous is not None and previous.cumulative_twr is None:
            # Solo la primera foto de la serie es una base genuina; si hay fotos
            # anteriores y falta el acumulado, la serie esta rota y no se reinicia.
            # Excepcion declarada: la primera foto real tras una serie
            # reconstruida solo-posiciones (twr_rebuild) es base nueva, porque
            # encadenarla mezclaria posiciones+caja con solo-posiciones.
            previous_is_base = bool((previous.metadata_ or {}).get("twr_base_after_scope_change")) or (
                db.scalar(
                    select(PortfolioDailySnapshot.id)
                    .where(
                        PortfolioDailySnapshot.portfolio_id == portfolio.id,
                        PortfolioDailySnapshot.snapshot_date < previous.snapshot_date,
                        *tenant_filters(db, PortfolioDailySnapshot),
                    )
                    .limit(1)
                )
                is None
            )
        if previous is not None and not previous_is_base:
            previous_is_base = self._restart_base(db, portfolio.id, previous)
        previous_positions_only = previous is not None and bool(
            (previous.metadata_ or {}).get("positions_only")
        )
        if (
            previous
            and not previous_positions_only
            and previous.total_value_base > 0
            and previous.pricing_coverage == Decimal("1")
            and previous.base_currency == portfolio.base_currency
            and pricing_coverage == Decimal("1")
            and not ambiguous_flows
            and not intermediate_flows
            and (previous.cumulative_twr is not None or previous_is_base)
        ):
            daily_return = (
                total_value - net_flow
            ) / previous.total_value_base - Decimal("1")
            prior_cumulative = previous.cumulative_twr or Decimal("0")
            cumulative_twr = (
                (Decimal("1") + prior_cumulative) * (Decimal("1") + daily_return)
                - Decimal("1")
            )

        snapshot.base_currency = portfolio.base_currency
        snapshot.positions_value_base = positions_value
        snapshot.cash_value_base = cash_value
        snapshot.total_value_base = total_value
        snapshot.net_external_flow_base = net_flow
        snapshot.daily_return = daily_return
        snapshot.cumulative_twr = cumulative_twr
        snapshot.pricing_coverage = pricing_coverage
        snapshot.source = source
        snapshot.metadata_ = {
            "missing_pricing": missing_pricing,
            "cash_carried_forward": cash_carried_forward,
            "ambiguous_external_flows": ambiguous_flows,
            "flow_timing": "end_of_day",
            "interval_days": interval_days,
            "unvalued_intermediate_flows": intermediate_flows,
            "twr_blocked_by_gap_flows": bool(intermediate_flows),
            "twr_blocked_by_scope_change": bool(previous_positions_only),
            "twr_base_after_scope_change": bool(previous_positions_only),
            "flow_window": "after_previous_snapshot_through_as_of",
            "flow_fx_policy": "rate_at_as_of",
            "position_as_of_dates": sorted(
                {position.as_of.isoformat() for position, _, _ in position_values}
            ),
        }
        db.flush()

        # Auditoria A: con caja neta negativa (margen) el NAV es menor que las
        # posiciones y base/NAV daba pesos de 133 %. Igual que el panel de
        # riesgo (portfolio_risk.weight_basis="gross_equity"), con margen el
        # peso se calcula sobre la exposicion bruta de las posiciones valoradas;
        # la caja/margen queda aparte con su signo en cash_value_base.
        gross_positions = sum(
            (abs(base) for _, _, base in position_values if base is not None),
            Decimal("0"),
        )
        gross_basis = cash_value < 0 and gross_positions > 0
        weight_denominator = gross_positions if gross_basis else total_value
        snapshot.metadata_ = {
            **(snapshot.metadata_ or {}),
            "weight_basis": "gross_positions" if gross_basis else "total_with_cash",
        }
        for position, rate, base in position_values:
            db.add(
                PositionDailySnapshot(
                    portfolio_snapshot_id=snapshot.id,
                    portfolio_id=portfolio.id,
                    company_id=position.company_id,
                    snapshot_date=snapshot_date,
                    quantity=position.quantity,
                    market_price_native=position.market_price,
                    currency=position.currency,
                    fx_rate=rate,
                    market_value_native=position.quantity * position.market_price,
                    market_value_base=base,
                    weight=(base / weight_denominator if base is not None and weight_denominator else None),
                    source=source,
                )
            )
        for cash, rate, base in cash_values:
            db.add(
                CashDailySnapshot(
                    portfolio_snapshot_id=snapshot.id,
                    portfolio_id=portfolio.id,
                    snapshot_date=snapshot_date,
                    currency=cash.currency,
                    balance_native=cash.balance,
                    fx_rate=rate,
                    balance_base=base,
                    source=source,
                )
            )
        db.flush()
        # A new historical snapshot changes the next snapshot's predecessor
        # just as a recapture changes its value. Relink both cases, using only
        # saved valuations (never today's balances for a later historical day).
        self._relink_following(db, portfolio.id, snapshot_date)
        return snapshot

    @staticmethod
    def _restart_base(db: Session, portfolio_id: int, previous: PortfolioDailySnapshot) -> bool:
        """``previous`` abre un tramo nuevo tras un tramo no valorable.

        La foto esta completa pero sin acumulado porque la suya anterior no se
        podia valorar (cobertura < 1 o valor <= 0). Sirve de base del tramo
        nuevo; NO se une con el tramo roto (no hay retorno entre ambos).
        """
        if (
            previous.cumulative_twr is not None
            or previous.pricing_coverage != Decimal("1")
            or previous.total_value_base <= 0
        ):
            return False
        before = db.scalar(
            select(PortfolioDailySnapshot)
            .where(
                PortfolioDailySnapshot.portfolio_id == portfolio_id,
                PortfolioDailySnapshot.snapshot_date < previous.snapshot_date,
                *tenant_filters(db, PortfolioDailySnapshot),
            )
            .order_by(desc(PortfolioDailySnapshot.snapshot_date))
            .limit(1)
        )
        return before is not None and (
            before.pricing_coverage != Decimal("1") or before.total_value_base <= 0
        )

    @staticmethod
    def _cash_unchanged_since(
        db: Session, portfolio_id: int, cash_as_of: date, snapshot_date: date
    ) -> bool:
        """True si el saldo de caja sigue siendo valido en ``snapshot_date``.

        Un saldo es un stock: el extracto de IBKR (Flex, diario, no en tiempo
        real) lo fecha en su ultimo cierre y vale hasta que algo lo mueva.
        Exigir ``as_of == dia`` dejaba la caja fuera de toda foto tomada otro
        dia (valor 0, cobertura < 1) y bloqueaba el retorno encadenado. Se
        arrastra solo si no hay ninguna operacion (compra, venta, deposito,
        retirada, divisa...) posterior a la fecha del saldo; si la hay, el
        saldo es dudoso y la foto sigue marcandolo como sin valorar.
        """
        later = db.scalar(
            select(Transaction.id)
            .where(
                Transaction.portfolio_id == portfolio_id,
                Transaction.trade_date > cash_as_of,
                Transaction.trade_date <= snapshot_date,
                *tenant_filters(db, Transaction),
            )
            .limit(1)
        )
        later_fx = db.scalar(
            select(FxConversion.id)
            .where(
                FxConversion.trade_date > cash_as_of,
                FxConversion.trade_date <= snapshot_date,
                *tenant_filters(db, FxConversion),
            )
            .limit(1)
        )
        return later is None and later_fx is None

    def _relink_following(self, db: Session, portfolio_id: int, after: date) -> None:
        following = list(
            db.scalars(
                select(PortfolioDailySnapshot)
                .where(
                    PortfolioDailySnapshot.portfolio_id == portfolio_id,
                    PortfolioDailySnapshot.snapshot_date >= after,
                )
                .order_by(PortfolioDailySnapshot.snapshot_date)
            ).all()
        )
        for previous, current in zip(following, following[1:], strict=False):
            meta = current.metadata_ or {}
            if meta.get("positions_only"):
                # Foto reconstruida (twr_rebuild): su cadena la calcula la
                # herramienta desde operaciones y cierres; no tiene contrato de
                # flujos y relinkearla aquí la borraría entera.
                continue
            # Misma regla que capture() (#2890): un día real tras una foto
            # solo-posiciones no encadena y queda como base nueva declarada.
            previous_positions_only = bool((previous.metadata_ or {}).get("positions_only"))
            if bool(meta.get("twr_base_after_scope_change")) != previous_positions_only:
                meta = {
                    **meta,
                    "twr_blocked_by_scope_change": previous_positions_only,
                    "twr_base_after_scope_change": previous_positions_only,
                }
                current.metadata_ = meta
            previous_is_base = bool(
                (previous.metadata_ or {}).get("twr_base_after_scope_change")
            ) or previous.cumulative_twr is None and (
                db.scalar(
                    select(PortfolioDailySnapshot.id)
                    .where(
                        PortfolioDailySnapshot.portfolio_id == portfolio_id,
                        PortfolioDailySnapshot.snapshot_date < previous.snapshot_date,
                        *tenant_filters(db, PortfolioDailySnapshot),
                    )
                    .limit(1)
                )
                is None
            ) or self._restart_base(db, portfolio_id, previous)
            # Only snapshots with an explicit interval-flow contract may
            # have their window recomputed. A legacy snapshot without that
            # evidence never proves zero flow and stays unlinked.
            intermediate = meta.get("unvalued_intermediate_flows")
            window_proven = (
                meta.get("flow_window") == "after_previous_snapshot_through_as_of"
                and isinstance(intermediate, int)
                and not isinstance(intermediate, bool)
                and intermediate >= 0
                and "ambiguous_external_flows" in meta
            )
            if window_proven:
                # A backfill narrows (previous, current]. Reusing the old
                # net flow would subtract a deposit twice, or keep a resolved
                # gap blocked. Recompute the flow window, not the valuation.
                net_flow, ambiguous = self._external_flows(
                    db, portfolio_id=portfolio_id, as_of=current.snapshot_date,
                    base_currency=current.base_currency,
                    after=previous.snapshot_date,
                )
                interval_days = (current.snapshot_date - previous.snapshot_date).days
                intermediate = len(db.scalars(select(Transaction.id).where(
                    Transaction.portfolio_id == portfolio_id,
                    Transaction.trade_date > previous.snapshot_date,
                    Transaction.trade_date < current.snapshot_date,
                    Transaction.action.in_(["deposit", "withdrawal", "cash_misc"]),
                    *tenant_filters(db, Transaction),
                )).all()) if interval_days > 1 else 0
                current.net_external_flow_base = net_flow
                meta = {
                    **meta,
                    "ambiguous_external_flows": ambiguous,
                    "interval_days": interval_days,
                    "unvalued_intermediate_flows": intermediate,
                    "twr_blocked_by_gap_flows": bool(intermediate),
                }
                current.metadata_ = meta
            linkable = (
                window_proven
                and intermediate == 0
                and not previous_positions_only
                and previous.total_value_base > 0
                and previous.pricing_coverage == Decimal("1")
                and previous.base_currency == current.base_currency
                and current.pricing_coverage == Decimal("1")
                and not meta.get("ambiguous_external_flows")
                and (previous.cumulative_twr is not None or previous_is_base)
            )
            if linkable:
                net_flow = current.net_external_flow_base or Decimal("0")
                daily = (current.total_value_base - net_flow) / previous.total_value_base - Decimal("1")
                prior = previous.cumulative_twr or Decimal("0")
                current.daily_return = daily
                current.cumulative_twr = (Decimal("1") + prior) * (Decimal("1") + daily) - Decimal("1")
            else:
                current.daily_return = None
                current.cumulative_twr = None
        db.flush()

    def history(
        self,
        db: Session,
        *,
        start: date | None = None,
        limit: int = 5000,
    ) -> list[PortfolioDailySnapshot]:
        portfolio = self.fx.portfolio(db)
        if portfolio is None:
            return []
        statement = select(PortfolioDailySnapshot).where(
            PortfolioDailySnapshot.portfolio_id == portfolio.id
        )
        if start:
            statement = statement.where(PortfolioDailySnapshot.snapshot_date >= start)
        return list(
            db.scalars(
                statement.order_by(PortfolioDailySnapshot.snapshot_date).limit(limit)
            ).all()
        )

    def _external_flows(
        self,
        db: Session,
        *,
        portfolio_id: int,
        as_of: date,
        base_currency: str,
        after: date | None = None,
    ) -> tuple[Decimal, list[int]]:
        conditions = [
            Transaction.portfolio_id == portfolio_id,
            Transaction.trade_date <= as_of,
            Transaction.action.in_(["deposit", "withdrawal", "cash_misc"]),
        ]
        # Ventana (anterior, as_of]: si falta una foto intermedia, todos los
        # flujos del intervalo se descuentan, no solo los del dia actual.
        conditions.append(
            Transaction.trade_date > after if after is not None else Transaction.trade_date == as_of
        )
        transactions = db.scalars(select(Transaction).where(*conditions)).all()
        total = Decimal("0")
        ambiguous: list[int] = []
        # Lote FX: 1 query para todos los flujos (anti N+1).
        flow_rates = self.fx.rates_for(
            db,
            quote_currencies={transaction.currency for transaction in transactions},
            base_currency=base_currency,
            as_of=as_of,
        )
        for transaction in transactions:
            if transaction.action == "cash_misc":
                ambiguous.append(transaction.id)
                continue
            rate = flow_rates.get(currency_key(transaction.currency))
            if rate is None:
                ambiguous.append(transaction.id)
                continue
            amount = transaction.quantity * transaction.price * rate
            total += amount if transaction.action == "deposit" else -amount
        return total, ambiguous
