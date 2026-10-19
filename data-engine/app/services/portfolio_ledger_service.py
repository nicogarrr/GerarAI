from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import Company, Position, Transaction
from app.services.portfolio_fx_service import PortfolioFXService

_UNSET = object()

#: Acciones válidas del ledger (enum cerrado: buy/sell mueven posición,
#: el resto son movimientos de caja/ajuste que no tocan cantidad).
LEDGER_ACTIONS = frozenset(
    {"buy", "sell", "dividend", "interest", "fee", "cash_misc", "withholding"}
)
BUY_ACTIONS = frozenset({"buy", "bot", "b"})
SELL_ACTIONS = frozenset({"sell", "sold"})


class PortfolioOversellError(ValueError):
    """Venta sin acciones suficientes. La ruta la mapea a 409."""


class PortfolioMixedCurrencyError(ValueError):
    """Posición mult/divisa. La ruta la mapea a 422."""


class PortfolioLedgerService:
    """Canonical transaction ledger and derived positions for one tenant."""

    def __init__(self) -> None:
        self.fx = PortfolioFXService()

    def ensure_company(self, db: Session, ticker: str, name: str | None = None) -> Company:
        normalized = ticker.strip().upper()
        company = db.scalar(select(Company).where(Company.ticker == normalized))
        if company:
            if name and company.name == company.ticker:
                company.name = name.strip()[:255]
            return company
        company = Company(
            ticker=normalized,
            name=(name or normalized).strip()[:255],
            exchange="UNKNOWN",
            currency="USD",
            sector="Unknown",
            industry="Unknown",
            company_type="research_candidate",
            valuation_model="unassigned",
            special_sources=[],
            special_risks=[],
            factor_tags=[],
        )
        db.add(company)
        db.flush()
        return company

    def create_transaction(
        self,
        db: Session,
        *,
        ticker: str,
        action: str,
        quantity: Decimal,
        price: Decimal,
        trade_date: date,
        fees: Decimal = Decimal("0"),
        currency: str = "USD",
        notes: str | None = None,
    ) -> Transaction:
        normalized_action = (action or "").lower()
        if normalized_action not in LEDGER_ACTIONS:
            raise ValueError(f"Unsupported ledger action: {normalized_action or 'empty'}")
        if quantity is None:
            raise ValueError("Transaction quantity is required")
        if normalized_action in {"buy", "sell"}:
            # buy/sell mueven posición: cantidad estrictamente positiva.
            if Decimal(quantity) <= 0:
                raise ValueError("Transaction quantity must be positive")
        elif Decimal(quantity) < 0:
            # dividend/interest/fee/cash_misc son movimientos de caja: el
            # cero es legítimo (p. ej. dividendo con importe en precio).
            raise ValueError("Transaction quantity cannot be negative")
        if price is None or Decimal(price) < 0:
            raise ValueError("Transaction price cannot be negative")
        if fees is None or Decimal(fees) < 0:
            raise ValueError("Transaction fees cannot be negative")
        if trade_date is None or trade_date > date.today():
            raise ValueError("Transaction trade_date cannot be in the future")
        company = self.ensure_company(db, ticker)
        portfolio = self.fx.ensure_portfolio(db)

        if normalized_action == "sell":
            # Validate BEFORE writing anything. The oversell was previously
            # detected by rebuild_position AFTER the row had been added and
            # flushed, so the caller that swallowed the PortfolioOversellError
            # (the CSV importer) kept the impossible sale in the session and
            # committed it: a phantom gain entered the tax report.
            held = self._held_quantity(db, company.id)
            if Decimal(quantity) > held:
                raise PortfolioOversellError(
                    f"Cannot sell {quantity} {ticker.upper()}: only {held} shares are "
                    "available on the ledger."
                )

        row = Transaction(
            portfolio_id=portfolio.id,
            company_id=company.id,
            trade_date=trade_date,
            action=normalized_action,
            quantity=quantity,
            price=price,
            fees=fees,
            currency=currency.upper(),
            external_id=f"manual-{uuid4().hex}",
            raw_payload={"notes": notes} if notes else {},
        )
        db.add(row)
        db.flush()
        self.rebuild_position(db, company.id)
        # Los hechos son por tenant: al entrar una empresa en cartera se
        # siembran sus fundamentales sin esperar al boton de la ficha.
        from app.services.fundamentals_seed_service import enqueue_fundamentals_seed

        enqueue_fundamentals_seed(db, company.ticker)
        return row

    @staticmethod
    def _held_quantity(db: Session, company_id: int) -> Decimal:
        """Shares currently on the ledger, from the buy/sell legs only."""
        total = Decimal("0")
        for action, quantity in db.execute(
            select(Transaction.action, Transaction.quantity).where(
                Transaction.company_id == company_id,
                Transaction.action.in_(BUY_ACTIONS | SELL_ACTIONS),
            )
        ).all():
            amount = Decimal(quantity or 0)
            total += amount if str(action).lower() in BUY_ACTIONS else -amount
        return total

    def rebuild_position(
        self, db: Session, company_id: int, *, as_of: date | None = None
    ) -> Position | None:
        transactions = list(
            db.scalars(
                select(Transaction)
                .where(
                    Transaction.company_id == company_id,
                    Transaction.action.in_(["buy", "sell"]),
                )
                .order_by(Transaction.trade_date, Transaction.created_at, Transaction.id)
            ).all()
        )
        currencies = {transaction.currency.upper() for transaction in transactions}
        if len(currencies) > 1:
            raise PortfolioMixedCurrencyError(
                "A position cannot mix transaction currencies; split the instrument or normalize the ledger"
            )
        portfolio = self.fx.ensure_portfolio(db)
        base_currency = portfolio.base_currency.upper()
        quantity = Decimal("0")
        cost = Decimal("0")
        cost_base = Decimal("0")
        base_cost_complete = True
        realized = Decimal("0")
        realized_base = Decimal("0")
        last_price = Decimal("0")
        currency = "USD"
        last_transaction_date = max(
            (transaction.trade_date for transaction in transactions), default=None
        )
        valuation_date = as_of or last_transaction_date
        if valuation_date is None:
            return None

        for transaction in transactions:
            last_price = transaction.price
            currency = transaction.currency
            if transaction.action == "buy":
                quantity += transaction.quantity
                native_purchase = transaction.quantity * transaction.price + transaction.fees
                cost += native_purchase
                historical_rate = self.fx.rate(
                    db,
                    quote_currency=transaction.currency,
                    base_currency=base_currency,
                    as_of=transaction.trade_date,
                )
                if historical_rate is None:
                    base_cost_complete = False
                elif base_cost_complete:
                    cost_base += native_purchase * historical_rate
                continue
            if transaction.quantity > quantity:
                raise PortfolioOversellError(
                    f"Cannot sell {transaction.quantity}; only {quantity} shares are available"
                )
            average_cost = cost / quantity if quantity else Decimal("0")
            realized += (transaction.price - average_cost) * transaction.quantity - transaction.fees
            historical_rate = self.fx.rate(
                db,
                quote_currency=transaction.currency,
                base_currency=base_currency,
                as_of=transaction.trade_date,
            )
            if historical_rate is None or not base_cost_complete:
                base_cost_complete = False
            else:
                average_cost_base = cost_base / quantity
                proceeds_base = (
                    transaction.price * transaction.quantity - transaction.fees
                ) * historical_rate
                realized_base += proceeds_base - average_cost_base * transaction.quantity
                cost_base -= average_cost_base * transaction.quantity
            cost -= average_cost * transaction.quantity
            quantity -= transaction.quantity

        position = db.scalar(select(Position).where(Position.company_id == company_id))
        if quantity <= 0:
            if position:
                db.delete(position)
                db.flush()
            return None

        if position is None:
            position = Position(company_id=company_id, portfolio_id=portfolio.id)
            db.add(position)
        existing_price = position.market_price or Decimal("0")
        market_price = existing_price if existing_price > 0 else last_price
        if existing_price > 0 and as_of is None and position.as_of is not None:
            # F366: se conserva la cotización guardada, así que su fecha NO se
            # mueve a la de la última operación del ledger ni se valora el FX
            # con esa fecha (valor base y snapshots quedarían stale).
            valuation_date = position.as_of
        position.quantity = quantity
        position.average_cost = cost / quantity
        position.market_price = market_price
        position.market_value = quantity * market_price
        position.unrealized_pnl = position.market_value - cost
        position.realized_pnl = realized
        position.currency = currency
        current_rate = self.fx.rate(
            db,
            quote_currency=currency,
            base_currency=base_currency,
            as_of=valuation_date,
        )
        position.portfolio_id = portfolio.id
        position.base_currency = base_currency
        position.market_value_native = position.market_value
        position.cost_basis_native = cost
        position.market_value_base = (
            position.market_value * current_rate if current_rate is not None else None
        )
        position.cost_basis_base = cost_base if base_cost_complete else None
        position.unrealized_pnl_base = (
            position.market_value_base - cost_base
            if position.market_value_base is not None and base_cost_complete
            else None
        )
        position.realized_pnl_base = realized_base if base_cost_complete else None
        position.fx_rate = current_rate
        position.source = "postgres_ledger"
        position.as_of = valuation_date
        db.flush()
        return position

    def delete_holding(self, db: Session, company_id: int) -> int:
        tenant_id = db.info.get("tenant_id")
        if tenant_id is None:
            raise RuntimeError("Tenant context is required")
        deleted = db.execute(
            delete(Transaction).where(
                Transaction.tenant_id == tenant_id,
                Transaction.company_id == company_id,
            )
        ).rowcount
        position = db.scalar(select(Position).where(Position.company_id == company_id))
        if position:
            db.delete(position)
        db.flush()
        return int(deleted or 0)

    def update_market_price(
        self,
        db: Session,
        *,
        company_id: int,
        price: Decimal,
        as_of: date | None = None,
        position: Position | None = None,
        fx_rate: Decimal | None | object = _UNSET,
    ) -> Position:
        if position is None:
            position = db.scalar(select(Position).where(Position.company_id == company_id))
        if position is None:
            raise ValueError("Holding not found")
        position.market_price = price
        position.market_value = position.quantity * price
        # Zero/missing cost is unknown, not a free acquisition. Never turn
        # the entire market value into a reported profit after a price refresh.
        has_cost = position.average_cost > 0 and (position.cost_basis_base or 0) > 0
        position.unrealized_pnl = (
            position.market_value - position.quantity * position.average_cost
            if position.average_cost > 0 else Decimal("0")
        )
        position.as_of = as_of or date.today()
        position.market_value_native = position.market_value
        position.cost_basis_native = position.quantity * position.average_cost
        base_currency = position.base_currency or self.fx.base_currency(db)
        if fx_rate is _UNSET:
            current_rate = self.fx.rate(
                db,
                quote_currency=position.currency,
                base_currency=base_currency,
                as_of=position.as_of,
            )
        else:
            current_rate = fx_rate
        position.fx_rate = current_rate
        position.market_value_base = (
            position.market_value * current_rate if current_rate is not None else None
        )
        position.unrealized_pnl_base = (
            position.market_value_base - position.cost_basis_base
            if position.market_value_base is not None
            and has_cost
            else None
        )
        db.flush()
        return position
