"""Corporate actions that adjust cost basis and historical quantities.

Splits / reverse splits change share count while preserving the economic
value of a position. To keep the FIFO tax ledger coherent we adjust:

- the open Position (quantity x ratio, average cost / ratio),
- every share-denominated Transaction (buy/sell) strictly before the effective
  date (quantity x ratio, price / ratio) so historical reports and realized
  gains stay correct. Cash movements (dividend, withholding, interest, fee,
  cash_misc) are NEVER rescaled: they store a money amount in ``price``, not a
  per-share price, so dividing them would shrink a EUR 100 dividend to EUR 25
  and the tax report would declare the divided figure.

Ticker changes and mergers update the company identity; merger value
exchange (shares of the acquirer) must be entered as a manual transaction
by the user because it depends on deal terms.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.tenancy import tenant_filters
from app.models import Company, CorporateAction, Position, Transaction
from app.services.company_resolver import resolve_company

SPLIT_TYPES = {"split", "reverse_split"}


def _today() -> date:
    return datetime.now(UTC).date()


def _validate_verified_price(price, as_of, effective_date) -> None:
    """Entradas explicitas del llamador: se comprueban antes de escribir.

    No acreditan procedencia por si solas (no hay fuente autenticada): solo
    descartan basura (float, NaN/Inf, <=0, datetime, fecha anterior al
    efectivo o futura).
    """
    if price is None and as_of is None:
        return
    if type(price) is not Decimal or not price.is_finite() or price <= 0:
        raise ValueError("Split rejected: post_split_price must be a finite Decimal > 0")
    if type(as_of) is not date:
        raise ValueError("Split rejected: post_split_price_as_of must be a date")
    if as_of < effective_date:
        raise ValueError(
            "Split rejected: post_split_price_as_of is before the effective date"
        )
    if as_of > _today():
        raise ValueError("Split rejected: post_split_price_as_of is in the future")


class CorporateActionService:
    @staticmethod
    def first_trade_dates(db: Session, company_ids: set[int]) -> dict[int, object]:
        """Primera compra/venta registrada por empresa (lote, 1 query)."""
        if not company_ids:
            return {}
        rows = db.execute(
            select(Transaction.company_id, func.min(Transaction.trade_date))
            .where(
                Transaction.company_id.in_(company_ids),
                Transaction.action.in_(("buy", "sell")),
                *tenant_filters(db, Transaction),
            )
            .group_by(Transaction.company_id)
        ).all()
        return {company_id: first_date for company_id, first_date in rows if company_id is not None}

    @staticmethod
    def companies_with_holding(db: Session, company_ids: set[int]) -> set[int]:
        """Empresas con posicion abierta o alguna compra/venta registrada (lote).

        Un split de una empresa fuera de cartera no tiene nada que ajustar."""
        if not company_ids:
            return set()
        with_position = set(
            db.scalars(
                select(Position.company_id).where(
                    Position.company_id.in_(company_ids),
                    *tenant_filters(db, Position),
                )
            )
        )
        with_trades = set(
            db.scalars(
                select(Transaction.company_id)
                .where(
                    Transaction.company_id.in_(company_ids),
                    Transaction.action.in_(("buy", "sell")),
                    *tenant_filters(db, Transaction),
                )
                .distinct()
            )
        )
        return {cid for cid in (with_position | with_trades) if cid is not None}

    @staticmethod
    def is_historical(action: CorporateAction, first_trade_date: object) -> bool:
        """Split anterior (o igual) a la primera operacion de la posicion: las
        acciones ya se compraron post-split, asi que ya esta reflejado y
        reescalar la posicion actual la deformaria. Sin transacciones no hay
        referencia: se deja decidir al usuario (no es historico)."""
        return bool(
            action.action_type in SPLIT_TYPES
            and first_trade_date is not None
            and action.effective_date <= first_trade_date  # type: ignore[operator]
        )

    def list_actions(self, db: Session, *, limit: int = 500) -> list[CorporateAction]:
        return list(
            db.scalars(
                select(CorporateAction)
                .join(Company, CorporateAction.company_id == Company.id)
                # Lo mas reciente primero: el tope recorta la historia antigua, no
                # los eventos accionables. Con orden ascendente, los cientos de
                # splits de los anos 70 de la ingesta del universo llenaban el
                # limite y dejaban fuera los de ahora.
                .order_by(CorporateAction.effective_date.desc(), CorporateAction.id.desc())
                .limit(limit)
            )
        )

    def create_action(
        self,
        db: Session,
        *,
        ticker: str,
        action_type: str,
        effective_date,
        ratio: Decimal,
        description: str = "",
        apply_now: bool = True,
        post_split_price: Decimal | None = None,
        post_split_price_as_of=None,
    ) -> CorporateAction:
        """Crea la accion y, con apply_now, la aplica en UNA unidad de trabajo.

        Si aplicar falla se hace rollback de TODA la sesion (tambien de los
        cambios pendientes sin commit del llamador) y se relanza el error.
        """
        company = resolve_company(db, ticker)
        if company is None:
            raise ValueError(f"Company {ticker} does not exist; import transactions or create it first")
        if ratio <= 0:
            raise ValueError("Ratio must be positive")
        action = CorporateAction(
            company_id=company.id,
            action_type=action_type,
            effective_date=effective_date,
            ratio=ratio,
            description=description,
            applied=False,
        )
        db.add(action)
        if not apply_now:
            db.commit()
            db.refresh(action)
            return action
        # Atomico: si aplicar falla (libro ambiguo, oversell...) no queda una
        # accion pendiente residual; se revierte accion y cambios juntos.
        try:
            db.flush()
            self._apply_in_txn(
                db, action,
                post_split_price=post_split_price,
                post_split_price_as_of=post_split_price_as_of,
            )
            db.commit()
        except Exception:
            db.rollback()
            raise
        db.refresh(action)
        return action

    def delete_action(self, db: Session, action_id: int) -> bool:
        action = db.get(CorporateAction, action_id)
        if action is None:
            return False
        if action.applied:
            raise ValueError(
                "Applied corporate actions are immutable; create a compensating "
                "reverse action instead of deleting"
            )
        db.delete(action)
        db.commit()
        return True

    def apply_action(
        self, db: Session, action_id: int, *, post_split_price: Decimal | None = None,
        post_split_price_as_of=None,
    ) -> CorporateAction:
        action = db.get(CorporateAction, action_id)
        if action is None:
            raise ValueError("Corporate action not found")
        if action.applied:
            return action
        try:
            self._apply_in_txn(
                db, action,
                post_split_price=post_split_price,
                post_split_price_as_of=post_split_price_as_of,
            )
            db.commit()
        except Exception:
            db.rollback()
            raise
        db.refresh(action)
        return action

    def _apply_in_txn(
        self, db: Session, action: CorporateAction, *,
        post_split_price: Decimal | None = None, post_split_price_as_of=None,
    ) -> None:
        """Aplica sin commit: el llamador confirma o revierte todo junto."""
        ratio = action.ratio
        if ratio <= 0:
            raise ValueError("Ratio must be positive")
        rebuild_company_id: int | None = None
        hold_old_as_of: date | None = None

        if action.action_type in {"split", "reverse_split"}:
            _validate_verified_price(
                post_split_price, post_split_price_as_of, action.effective_date
            )
            first = self.first_trade_dates(db, {action.company_id}).get(action.company_id)
            position = db.scalar(
                select(Position).where(Position.company_id == action.company_id)
            )
            # Split historico (anterior a la primera operacion): ya reflejado,
            # se marca aplicado sin reescalar la posicion actual.
            if not self.is_historical(action, first):
                # Replay del libro con las patas ANTERIORES a la fecha efectiva
                # ajustadas (cantidad*ratio, precio/ratio, comisiones sin
                # tocar) y las posteriores tal cual (ya estan en terminos
                # post-split). Da cantidad, coste medio y realizado coherentes
                # incluso con ventas posteriores. Todo se calcula ANTES de
                # escribir: si el libro es ambiguo se rechaza sin cambios.
                legs = db.scalars(
                    select(Transaction)
                    .where(
                        Transaction.company_id == action.company_id,
                        Transaction.action.in_(("buy", "sell")),
                    )
                    .order_by(
                        Transaction.trade_date, Transaction.created_at, Transaction.id
                    )
                ).all()
                ledger_net = sum(
                    (
                        # nosemgrep: gerarai-money-none-to-zero -- campos NOT NULL de Transaction (quantity/price/fees default 0); el `or` es defensivo
                        (leg.quantity or Decimal("0"))
                        * (1 if leg.action == "buy" else -1)
                        for leg in legs
                    ),
                    Decimal("0"),
                )
                if len({(leg.currency or "").upper() for leg in legs}) > 1:
                    raise ValueError(
                        "Split rejected: the ledger mixes currencies; "
                        "split the instrument or normalize it first"
                    )
                if position is not None:
                    # Solo posiciones derivadas del libro (source postgres_ledger) y
                    # con libro coherente: manual/Flex/sin patas no demuestran
                    # unidades ni precio correctos, se rechaza antes de escribir.
                    if position.source != "postgres_ledger":
                        raise ValueError(
                            "Split rejected: position source "
                            f"{position.source!r} is not the ledger; review the position"
                        )
                    if not legs:
                        raise ValueError(
                            "Split rejected: no buy/sell legs on the ledger; review the position"
                        )
                    if ledger_net != position.quantity:
                        raise ValueError(
                            "Split rejected: position quantity "
                            f"{position.quantity} does not match the ledger "
                            f"({ledger_net}); review the position before applying"
                        )
                qty = Decimal("0")
                cost = Decimal("0")
                realized = Decimal("0")
                for leg in legs:
                    # nosemgrep: gerarai-money-none-to-zero -- campos NOT NULL de Transaction (quantity/price/fees default 0); el `or` es defensivo
                    leg_qty = leg.quantity or Decimal("0")
                    # nosemgrep: gerarai-money-none-to-zero -- campos NOT NULL de Transaction (quantity/price/fees default 0); el `or` es defensivo
                    leg_price = leg.price or Decimal("0")
                    fees = leg.fees or Decimal("0")
                    if leg.trade_date < action.effective_date:
                        # Mismo redondeo que se persiste mas abajo.
                        leg_qty = (leg_qty * ratio).quantize(Decimal("0.000001"))
                        leg_price = (leg_price / ratio).quantize(Decimal("0.000001"))
                    if leg.action == "buy":
                        qty += leg_qty
                        cost += leg_qty * leg_price + fees
                    else:
                        if leg_qty > qty:
                            raise ValueError(
                                "Split rejected: adjusted ledger would oversell "
                                f"({leg_qty} > {qty}); review the position"
                            )
                        avg = cost / qty
                        realized += (leg_price - avg) * leg_qty - fees
                        cost -= avg * leg_qty
                        qty -= leg_qty
                if position is None:
                    # Posicion ya cerrada: solo se valida el replay ajustado
                    # (sin oversell por redondeo) y se reescalan las patas.
                    if qty > 0:
                        raise ValueError(
                            "Split rejected: the ledger is open but there is "
                            "no position row; review the position"
                        )
                elif qty <= 0:
                    raise ValueError("Split rejected: adjusted ledger is empty")
                # Cantidad, coste, realizado y columnas base/FX/no realizado las
                # recalcula rebuild_position sobre las patas ya ajustadas (una
                # sola fuente de verdad). El precio de mercado post-split y su
                # fecha los aporta quien aplica (verificados); jamas se deduce
                # del precio guardado, que no tiene proveniencia.
                if position is not None:
                    if post_split_price is None:
                        # Sin precio post-split verificado: la contabilidad (cantidad,
                        # coste, realizado) se aplica; la valoracion queda en suspenso
                        # persistente. Nada se deduce del precio guardado ni del ratio.
                        hold_old_as_of = position.as_of
                    else:
                        position.market_price = post_split_price
                        position.as_of = post_split_price_as_of
                    rebuild_company_id = action.company_id

            # Share-denominated legs only. Cash rows keep their amount in
            # `price` (quantity 0 or 1 is legitimate for cash, see
            # PortfolioLedgerService and the IBKR importer which writes
            # quantity=1, price=amount): rescaling them would divide a EUR
            # 100 dividend into EUR 25 and a EUR 9.95 commission into EUR
            # 2.49, and the tax report would declare the divided figure.
            transactions = db.scalars(
                select(Transaction).where(
                    Transaction.company_id == action.company_id,
                    Transaction.trade_date < action.effective_date,
                    Transaction.action.in_(("buy", "sell")),
                )
            ).all()
            for transaction in transactions:
                if transaction.quantity is not None:
                    transaction.quantity = (
                        transaction.quantity * ratio
                    ).quantize(Decimal("0.000001"))
                if transaction.price is not None:
                    transaction.price = (transaction.price / ratio).quantize(
                        Decimal("0.000001")
                    )

        elif action.action_type == "ticker_change":
            company = db.get(Company, action.company_id)
            if company is not None and action.description:
                company.name = action.description.split("|")[0].strip() or company.name

        # mergers / spin-offs: deal terms are user-specific; only flag as applied
        # after the user confirms the compensating transactions exist.
        if rebuild_company_id is not None:
            from app.services.portfolio_ledger_service import PortfolioLedgerService

            db.flush()
            ledger = PortfolioLedgerService()
            rebuilt = ledger.rebuild_position(db, rebuild_company_id)
            if hold_old_as_of is not None and rebuilt is not None:
                ledger.hold_valuation(
                    db, rebuilt,
                    reason=(
                        f"split {action.ratio}:1 de {action.effective_date.isoformat()} aplicado "
                        "sin precio post-split verificado: valoracion no disponible"
                    ),
                    effective_date=action.effective_date,
                )
                rebuilt.as_of = hold_old_as_of
        action.applied = True
        action.applied_at = datetime.now(UTC)