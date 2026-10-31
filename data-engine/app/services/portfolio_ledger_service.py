from __future__ import annotations

import logging
import os
from collections.abc import Callable
from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.local_date import local_today
from app.core.tenancy import tenant_filters
from app.models import Company, Position, Transaction
from app.services.portfolio_fx_service import PortfolioFXService, currency_key
from app.valuation.currency import canonical_currency_code

_UNSET = object()

logger = logging.getLogger(__name__)

#: Divisas/fecha de inicio ya intentadas en este proceso: si el BCE no responde
#: o no publica la divisa, no se reintenta en cada reconstruccion.
_ECB_BACKFILL_TRIED: set[tuple[str, date]] = set()


def _default_fx_backfill(db: Session, currencies: set[str], start: date, end: date) -> dict:
    from app.services.connectors.ecb_history import backfill_ecb_rates_sync

    return backfill_ecb_rates_sync(db, currencies=currencies, start=start, end=end)

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


class ValuationHeldError(ValueError):
    """La posicion tiene la valoracion en suspension: un precio no la levanta."""


class PortfolioLedgerService:
    """Canonical transaction ledger and derived positions for one tenant."""

    def __init__(
        self,
        *,
        fx_backfill: Callable[[Session, set[str], date, date], dict] | None = None,
    ) -> None:
        self.fx = PortfolioFXService()
        # realqa-10 (27-oct-2026): una cuenta EUR con compras en USD del
        # 02/03/2026 salia sin coste ni G/P («Conversion o coste no disponible»)
        # porque `fx_rates` solo tenia los tipos que guarda el refresco diario
        # desde que se desplego, y la descarga historica del BCE (#2349) no la
        # llamaba nadie. Ahora, si falta el tipo de la fecha de una operacion,
        # se descarga la serie oficial del BCE desde esa fecha y se usa el
        # ultimo tipo publicado en o antes de ella (fin de semana/festivo).
        # En tests no hay red: solo se descarga con un `fx_backfill` inyectado.
        if fx_backfill is None and os.environ.get("APP_ENV", "").lower() != "test":
            fx_backfill = _default_fx_backfill
        self._fx_backfill = fx_backfill

    def ensure_historical_fx(
        self,
        db: Session,
        *,
        currencies: set[str],
        base_currency: str,
        since: date,
    ) -> dict | None:
        """Descarga del BCE los tipos que faltan para valorar operaciones desde ``since``.

        Solo actua si NO hay ningun tipo (directo o inverso) en o antes de
        ``since`` para alguna divisa: la busqueda de :class:`PortfolioFXService`
        ya usa el ultimo tipo publicado en o antes de cada fecha. Base EUR
        unicamente (el BCE publica contra el euro). Nunca lanza: si el BCE no
        responde, la posicion sigue marcando el coste como no disponible.
        """
        if self._fx_backfill is None or base_currency.upper() != "EUR":
            return None
        missing = {
            code
            for code in currencies
            if code.upper() != "EUR"
            and (code.upper(), since) not in _ECB_BACKFILL_TRIED
            and self.fx.rate(db, quote_currency=code, base_currency="EUR", as_of=since) is None
        }
        if not missing:
            return None
        for code in missing:
            _ECB_BACKFILL_TRIED.add((code.upper(), since))
        # Unos dias antes: si la operacion cae en fin de semana o festivo
        # TARGET, el tipo valido es el del ultimo dia publicado.
        start = since - timedelta(days=10)
        try:
            summary = self._fx_backfill(db, missing, start, date.today())
        except Exception as exc:  # red, BCE caido, CSV raro: se degrada, no se rompe
            logger.warning(
                "fx.ecb_backfill failed currencies=%s since=%s error=%s",
                sorted(missing),
                since.isoformat(),
                type(exc).__name__,
            )
            return None
        logger.info(
            "fx.ecb_backfill currencies=%s since=%s written=%s",
            sorted(missing),
            since.isoformat(),
            (summary or {}).get("written"),
        )
        return summary

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
        external_id: str | None = None,
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
        if trade_date is None or trade_date > local_today():
            raise ValueError("Transaction trade_date cannot be in the future")
        company = self.ensure_company(db, ticker)
        portfolio = self.fx.ensure_portfolio(db)
        if normalized_action in {"buy", "sell"}:
            snapshot_position = db.scalar(select(Position).where(
                Position.company_id == company.id, *tenant_filters(db, Position),
                Position.source == "screenshot_confirmed",
            ))
            if snapshot_position is not None:
                raise ValueError(
                    "Esta posición procede de una captura sin historial. "
                    "Importa primero el fichero del bróker para conciliar antes de añadir compras o ventas"
                )

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
            currency=canonical_currency_code(currency),
            external_id=external_id or f"manual-{uuid4().hex}",
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
            *tenant_filters(db, Transaction),
        )
        ).all():
            # nosemgrep: gerarai-money-none-to-zero -- columna NOT NULL (default 0): el `or 0` no convierte ningun None real
            amount = Decimal(quantity or 0)
            total += amount if str(action).lower() in BUY_ACTIONS else -amount
        return total

    def rebuild_position(
        self,
        db: Session,
        company_id: int,
        *,
        as_of: date | None = None,
        drop_when_empty: bool = False,
    ) -> Position | None:
        """Reproduce las compras/ventas de la compania y reescribe su Position.

        ``drop_when_empty``: el llamante acaba de QUITAR una pata compra/venta
        (borrado o cambio de ticker). Si ya no queda ninguna, la Position que
        habia es un fantasma y se borra. Sin el flag, una compania sin patas
        conserva su Position (p. ej. la foto de posiciones de un extracto IBKR
        a la que solo se le anade un dividendo).
        """
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
        snapshot = db.scalar(select(Position).where(
                Position.company_id == company_id, *tenant_filters(db, Position),
                Position.source == "screenshot_confirmed",
        ))
        if snapshot is not None:
            if transactions:
                # Covers edits/reassignments and every rebuild caller, not only
                # create_transaction: no ledger can replace an opening snapshot
                # until a broker import has explicitly reconciled its source.
                raise ValueError(
                    "Esta posición procede de una captura sin historial. "
                    "Importa el fichero del bróker para conciliar antes de modificar operaciones"
                )
            if not transactions:
                # No opening trades were invented for this snapshot. A rebuild
                # has nothing to replay and must not delete it or fabricate cost.
                snapshot.base_currency = self.fx.base_currency(db)
                self.update_market_price(
                    db, company_id=company_id, position=snapshot,
                    price=snapshot.market_price, as_of=snapshot.as_of,
                )
                snapshot.cost_basis_native = None
                snapshot.cost_basis_base = None
                snapshot.realized_pnl_base = None
                return snapshot
        currencies = {canonical_currency_code(transaction.currency) for transaction in transactions}
        # GBP y GBp son unidades distintas: currency_key no las confunde.
        if len({currency_key(code) for code in currencies}) > 1:
            raise PortfolioMixedCurrencyError(
                "A position cannot mix transaction currencies; split the instrument or normalize the ledger"
            )
        portfolio = self.fx.ensure_portfolio(db)
        base_currency = portfolio.base_currency.upper()
        if transactions:
            self.ensure_historical_fx(
                db,
                currencies=currencies,
                base_currency=base_currency,
                since=min(transaction.trade_date for transaction in transactions),
            )
        quantity = Decimal("0")
        cost = Decimal("0")
        cost_base = Decimal("0")
        base_cost_complete = True
        realized_base_complete = True
        sold = False
        realized = Decimal("0")
        realized_base = Decimal("0")
        last_price = Decimal("0")
        currency = "USD"
        last_transaction_date = max(
            (transaction.trade_date for transaction in transactions), default=None
        )
        valuation_date = as_of or last_transaction_date
        if not transactions and drop_when_empty:
            orphan = db.scalar(select(Position).where(Position.company_id == company_id))
            if orphan is not None:
                db.delete(orphan)
                db.flush()
            return None
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
            sold = True
            if not base_cost_complete:
                realized_base_complete = False
            else:
                # El coste base de las acciones que quedan no depende del FX
                # del dia de la venta: solo el realizado lo necesita.
                average_cost_base = cost_base / quantity
                if historical_rate is None:
                    realized_base_complete = False
                else:
                    proceeds_base = (
                        transaction.price * transaction.quantity - transaction.fees
                    ) * historical_rate
                    realized_base += proceeds_base - average_cost_base * transaction.quantity
                cost_base -= average_cost_base * transaction.quantity
            cost -= average_cost * transaction.quantity
            quantity -= transaction.quantity
            if quantity == 0:
                # Posicion cerrada: el siguiente lote empieza de cero. Un FX
                # ausente en un lote ya cerrado no deja sin coste base al nuevo.
                cost = Decimal("0")
                cost_base = Decimal("0")
                base_cost_complete = True

        position = db.scalar(select(Position).where(Position.company_id == company_id))
        held_as_of = position.as_of if position is not None else None
        if quantity <= 0:
            if position:
                db.delete(position)
                db.flush()
            return None

        if position is None:
            position = Position(company_id=company_id, portfolio_id=portfolio.id)
            db.add(position)
        # nosemgrep: gerarai-money-none-to-zero -- columna NOT NULL (default 0): el `or 0` no convierte ningun None real
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
        position.realized_pnl_base = (
            realized_base if realized_base_complete and (base_cost_complete or sold) else None
        )
        position.fx_rate = current_rate
        position.source = "postgres_ledger"
        position.as_of = valuation_date
        if position.valuation_hold_reason:
            self._blank_valuation(position)
            position.as_of = held_as_of
        db.flush()
        return position

    @staticmethod
    def _blank_valuation(position: Position) -> None:
        """Valoracion NO disponible: 0 es solo el centinela interno de market_price
        (la columna no admite NULL); ningun consumidor debe leerlo como cotizacion."""
        position.market_price = Decimal("0")
        position.market_value = Decimal("0")
        position.unrealized_pnl = Decimal("0")
        position.market_value_native = None
        position.market_value_base = None
        position.unrealized_pnl_base = None

    def hold_valuation(
        self, db: Session, position: Position, *, reason: str, effective_date: date,
        since: date | None = None,
    ) -> None:
        position.valuation_hold_reason = reason[:200]
        position.valuation_hold_effective_date = effective_date
        position.valuation_hold_since = since or date.today()
        self._blank_valuation(position)
        db.flush()

    def release_valuation_hold(
        self, db: Session, *, company_id: int, price: Decimal, as_of: date,
    ) -> Position:
        """Levanta la suspension SOLO con un precio verificado por quien llama:
        finito > 0, fecha entre la fecha efectiva y hoy. Sin hold no hace nada raro:
        falla, para no usarlo como atajo de repricing.

        Frontera de autoridad: NO hay ruta HTTP ni job que lo llame; es solo una
        puerta de servicio. Quien lo invoque debe traer un precio verificado fuera
        de banda (la validacion de aqui solo descarta basura: no acredita
        procedencia). Cablearlo a un endpoint, a la cache market_prices o a un
        importador sin esa verificacion reintroduce una valoracion falsa."""
        position = db.scalar(select(Position).where(Position.company_id == company_id))
        if position is None or not position.valuation_hold_reason:
            raise ValueError("Position has no valuation hold")
        from app.services.corporate_actions_service import _validate_verified_price

        _validate_verified_price(
            price, as_of, position.valuation_hold_effective_date or date.min
        )
        position.valuation_hold_reason = None
        position.valuation_hold_effective_date = None
        position.valuation_hold_since = None
        db.flush()
        return self.update_market_price(db, company_id=company_id, price=price, as_of=as_of, position=position)

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
        if position.valuation_hold_reason:
            # Suspension de valoracion: un precio suelto no la levanta ni reescribe.
            # Error explicito (nunca un no-op silencioso); el llamador decide como
            # informarlo. El unico camino de salida es release_valuation_hold.
            raise ValuationHeldError(
                "Valuation is on hold "
                f"({position.valuation_hold_reason}); a price update does not lift it"
            )
        position.market_price = price
        position.market_value = position.quantity * price
        # Zero/missing cost is unknown, not a free acquisition. Never turn
        # the entire market value into a reported profit after a price refresh.
        # nosemgrep: gerarai-money-none-to-zero -- columna NOT NULL (default 0): el `or 0` no convierte ningun None real
        has_cost = position.average_cost > 0 and (position.cost_basis_base or 0) > 0
        position.unrealized_pnl = (
            position.market_value - position.quantity * position.average_cost
            if position.average_cost > 0 else Decimal("0")
        )
        position.as_of = as_of or local_today()
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
