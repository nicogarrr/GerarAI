"""Reconstruccion del valor historico diario de la cartera de valores.

El libro solo cubre una ventana reciente (en produccion desde el 8-oct), asi que
la reconstruccion arranca en la primera operacion: la cantidad inicial de cada
valor se deriva como posicion guardada menos el neto del libro (supone que no
hubo otras operaciones fuera del libro). Esa derivacion no es verificable por
si misma; la verificacion independiente es comparar el valor reconstruido del
ultimo dia con el valor guardado de las posiciones (`end_value_check`).

Los snapshots diarios solo valoran un dia si las posiciones se importaron ESE
dia, asi que no forman una serie continua. Esta reconstruccion usa el libro de
operaciones (cantidad en cada fecha) x precio de cierre del dia x FX del dia.

Alcance declarado (se devuelve en `scope` y `method`):
- solo posiciones de valores: sin caja, sin deuda de margen, sin dividendos;
- flujos de compra/venta al cierre del dia (fees incluidas);
- un dia sin precio de cierre exacto o sin FX para alguna posicion en cartera
  queda FUERA de la serie (no se rellena con el dia anterior);
- si la cantidad inicial derivada es negativa, o el valor del ultimo dia
  difiere mas de un 3 % del valor guardado, el estado lo declara y no es usable.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from statistics import median
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Company, MarketPrice, Position, Transaction
from app.services.portfolio_fx_service import PortfolioFXService
from app.services.portfolio_ledger_service import BUY_ACTIONS, SELL_ACTIONS
from app.services.price_units import price_in_currency

METHOD = "ledger_reconstruction"
SCOPE = "positions_only_no_cash_no_dividends"


@dataclass
class Reconstruction:
    status: str
    series: list[dict[str, Any]] = field(default_factory=list)
    returns: dict[date, float] = field(default_factory=dict)
    excluded_days: list[dict[str, Any]] = field(default_factory=list)
    quantity_check: list[dict[str, Any]] = field(default_factory=list)
    price_check: dict[str, Any] = field(default_factory=dict)
    twr: float | None = None

    @property
    def usable(self) -> bool:
        return self.status == "ok" and len(self.returns) >= 2

    def as_dict(self) -> dict[str, Any]:
        return {
            "method": METHOD,
            "scope": SCOPE,
            "status": self.status,
            "days_valued": len(self.series),
            "days_excluded": len(self.excluded_days),
            "excluded_days": self.excluded_days[:30],
            "first_date": self.series[0]["date"] if self.series else None,
            "last_date": self.series[-1]["date"] if self.series else None,
            "twr": self.twr,
            "quantity_check": self.quantity_check,
            "price_check": self.price_check,
        }


class PortfolioReconstructionService:
    def build(
        self,
        db: Session,
        *,
        start: date | None = None,
        rows: list[tuple[Position, Company]] | None = None,
    ) -> Reconstruction:
        fx = PortfolioFXService()
        base = fx.base_currency(db)
        transactions = [
            t
            for t in db.scalars(select(Transaction).order_by(Transaction.trade_date, Transaction.id)).all()
            if t.company_id is not None
            and (t.action or "").lower() in (BUY_ACTIONS | SELL_ACTIONS)
        ]
        if not transactions:
            return Reconstruction(status="no_transactions")
        held_positions = (
            [position for position, _ in rows] if rows is not None else list(db.scalars(select(Position)).all())
        )
        # Posiciones sin operaciones en el libro: cantidad constante en la ventana.
        ids: set[int] = {p.company_id for p in held_positions}
        currency: dict[int, str] = {p.company_id: (p.currency or "USD") for p in held_positions}
        for t in transactions:
            if t.company_id is not None:
                ids.add(t.company_id)
                currency[t.company_id] = (t.currency or "USD")
        company_ids = sorted(ids)
        companies_by_id = {company.id: company for _, company in (rows or [])}
        missing = [cid for cid in company_ids if cid not in companies_by_id]
        if missing:
            companies_by_id.update({
                c.id: c for c in db.scalars(select(Company).where(Company.id.in_(missing))).all()
            })
        tickers = {cid: company.ticker for cid, company in companies_by_id.items()}

        signed: list[tuple[date, int, Decimal, Decimal]] = []  # fecha, company, dqty, flow nativo
        net: dict[int, Decimal] = defaultdict(Decimal)
        for t in transactions:
            action = (t.action or "").lower()
            gross = t.quantity * t.price
            fees = t.fees or Decimal("0")
            if action in BUY_ACTIONS:
                signed.append((t.trade_date, t.company_id, t.quantity, gross + fees))
                net[t.company_id] += t.quantity
            else:
                signed.append((t.trade_date, t.company_id, -t.quantity, -(gross - fees)))
                net[t.company_id] -= t.quantity

        positions = {p.company_id: p for p in held_positions}
        # Cantidad inicial derivada: posicion guardada menos neto del libro.
        opening: dict[int, Decimal] = {}
        quantity_check = []
        for company_id in company_ids:
            stored = positions.get(company_id)
            stored_qty = stored.quantity if stored is not None else Decimal("0")
            opening[company_id] = stored_qty - net[company_id]
            quantity_check.append(
                {
                    "ticker": tickers.get(company_id),
                    "opening_derived": float(opening[company_id]),
                    "ledger_net": float(net[company_id]),
                    "position": float(stored_qty),
                }
            )
        if any(q < Decimal("-0.0001") for q in opening.values()):
            return Reconstruction(status="negative_opening_quantity", quantity_check=quantity_check)

        first_trade = signed[0][0]
        lower = max(start, first_trade) if start else first_trade
        warmup = first_trade - timedelta(days=7)
        prices: dict[tuple[int, date], Decimal] = {}
        # Columnas, no entidades: son años de cierres por valor (decenas de
        # miles de filas) y construir un MarketPrice ORM por fila era el mayor
        # coste de la reconstruccion. MarketPrice no es de tenant.
        for price_company_id, price_date, close, quote_currency in db.execute(
            select(
                MarketPrice.company_id,
                MarketPrice.date,
                MarketPrice.close,
                MarketPrice.quote_currency,
            ).where(
                MarketPrice.company_id.in_(company_ids), MarketPrice.date >= warmup
            )
        ):
            if close and close > 0:
                company = companies_by_id.get(price_company_id)
                if company is None:
                    continue
                converted = price_in_currency(
                    close, quote_currency=quote_currency,
                    target_currency=currency[price_company_id], company=company,
                )
                if converted is not None:
                    prices[(price_company_id, price_date)] = converted
        days = sorted({d for (_, d) in prices if d >= warmup})
        fx_table = fx.fx_table(
            db,
            currencies=set(currency.values()) | {base},
            base_currency=base,
            as_of_max=days[-1] if days else date.today(),
        )

        price_diffs = []
        for t in transactions:
            close = prices.get((t.company_id, t.trade_date))
            if close and t.price and t.price > 0:
                price_diffs.append(abs(float(t.price / close - 1)))
        price_check = {
            "compared_trades": len(price_diffs),
            "median_abs_diff_vs_close": round(median(price_diffs), 4) if price_diffs else None,
            "max_abs_diff_vs_close": round(max(price_diffs), 4) if price_diffs else None,
        }

        qty: dict[int, Decimal] = defaultdict(Decimal, opening)
        index = 0
        series: list[dict[str, Any]] = []
        excluded: list[dict[str, Any]] = []
        returns: dict[date, float] = {}
        pending_flow = Decimal("0")
        previous_value: Decimal | None = None
        previous_day: date | None = None
        base_row: dict[str, Any] | None = None
        for day in days:
            while index < len(signed) and signed[index][0] <= day:
                _, company_id, dqty, flow = signed[index]
                qty[company_id] += dqty
                rate_flow = PortfolioFXService.rate_from_table(
                    fx_table, quote_currency=currency[company_id], base_currency=base, as_of=signed[index][0]
                )
                if rate_flow is None:
                    return Reconstruction(
                        status="missing_fx_for_flow",
                        quantity_check=quantity_check,
                        price_check=price_check,
                    )
                pending_flow += flow * rate_flow
                index += 1
            held = [cid for cid, q in qty.items() if q > 0]
            value = Decimal("0")
            reason = None
            # Un tipo por divisa y dia (no uno por posicion y dia).
            day_rates: dict[str, Decimal | None] = {}
            for cid in held:
                close = prices.get((cid, day))
                cid_currency = currency[cid]
                if cid_currency not in day_rates:
                    day_rates[cid_currency] = PortfolioFXService.rate_from_table(
                        fx_table, quote_currency=cid_currency, base_currency=base, as_of=day
                    )
                rate = day_rates[cid_currency]
                if close is None:
                    reason = f"sin precio de cierre: {tickers.get(cid)}"
                    break
                if rate is None:
                    reason = f"sin FX {currency[cid]}/{base}: {tickers.get(cid)}"
                    break
                value += qty[cid] * close * rate
            if reason:
                excluded.append({"date": day.isoformat(), "reason": reason})
                continue
            if day < lower:
                previous_value, previous_day, pending_flow = (value if value > 0 else None), day, Decimal("0")
                base_row = {"date": day.isoformat(), "value_base": float(round(value, 2))}
                continue
            if base_row is not None:
                series.append(base_row)
                base_row = None
            series.append({"date": day.isoformat(), "value_base": float(round(value, 2))})
            if previous_value and previous_value > 0 and previous_day is not None:
                returns[day] = float((value - pending_flow) / previous_value - 1)
            previous_value = value if value > 0 else None
            previous_day = day
            pending_flow = Decimal("0")

        twr = None
        if returns:
            compound = 1.0
            for r in returns.values():
                compound *= 1 + r
            twr = compound - 1
        stored_value = sum(
            (p.market_value_base for p in positions.values() if p.market_value_base is not None),
            Decimal("0"),
        )
        end_check: dict[str, Any] = {"reconstructed": None, "stored": float(stored_value), "diff_pct": None}
        status = "ok"
        if series and stored_value > 0:
            last_value = Decimal(str(series[-1]["value_base"]))
            diff = float(last_value / stored_value - 1)
            end_check.update(
                reconstructed=float(last_value),
                diff_pct=round(100 * diff, 2),
                last_date=series[-1]["date"],
            )
            if abs(diff) > 0.03:
                status = "end_value_mismatch"
        elif series:
            status = "end_value_unverifiable"
        price_check["end_value_check"] = end_check
        return Reconstruction(
            status=status,
            series=series,
            returns=returns,
            excluded_days=excluded,
            quantity_check=quantity_check,
            price_check=price_check,
            twr=twr,
        )
