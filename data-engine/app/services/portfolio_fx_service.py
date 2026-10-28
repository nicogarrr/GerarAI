from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models import FXRate, Portfolio
from app.valuation.currency import normalize_currency

# Divisa de la declaracion (IRPF, Modelo 720): euros al tipo BCE de cada fecha,
# sea cual sea la divisa base de la cartera.
TAX_CURRENCY = "EUR"


def currency_key(raw: str) -> str:
    """Injective monetary-unit key: GBP and GBp must never collide."""
    major, divisor = normalize_currency(raw)
    if major is None:
        # Missing is a distinct key, never a guessed ISO currency. Preserve
        # the pure helper contract for incomplete imported data.
        return ""
    return major if divisor == 1 else f"{major}/{divisor}"


class PortfolioFXService:
    """Tenant-scoped portfolio configuration and point-in-time FX lookup."""

    def portfolio(self, db: Session) -> Portfolio | None:
        return db.scalar(
            select(Portfolio)
            .where(Portfolio.is_default.is_(True))
            .order_by(Portfolio.id)
            .limit(1)
        )

    def base_currency(self, db: Session) -> str:
        portfolio = self.portfolio(db)
        return (portfolio.base_currency if portfolio else "EUR").upper()

    def ensure_portfolio(self, db: Session) -> Portfolio:
        portfolio = self.portfolio(db)
        if portfolio is None:
            portfolio = Portfolio(name="Main", base_currency="EUR", is_default=True)
            db.add(portfolio)
            db.flush()
        return portfolio

    def set_base_currency(self, db: Session, currency: str) -> Portfolio:
        normalized = currency.strip().upper()
        if len(normalized) != 3 or not normalized.isalpha():
            raise ValueError("Base currency must be a three-letter ISO currency")
        portfolio = self.ensure_portfolio(db)
        portfolio.base_currency = normalized
        db.flush()
        return portfolio

    def rate(
        self,
        db: Session,
        *,
        quote_currency: str,
        base_currency: str,
        as_of: date,
    ) -> Decimal | None:
        found = self.rate_with_provenance(
            db,
            quote_currency=quote_currency,
            base_currency=base_currency,
            as_of=as_of,
        )
        return found["rate"] if found else None

    def rate_with_provenance(
        self,
        db: Session,
        *,
        quote_currency: str,
        base_currency: str,
        as_of: date,
    ) -> dict | None:
        """Misma seleccion que ``rate`` (unica implementacion): ultima tasa
        con rate_date <= as_of, directa antes que inversa, desempate por
        rate_date desc y created_at desc. Devuelve la tasa efectiva y su
        procedencia: rate_date y source de la fila usada y direction
        ("same", "direct" o "inverse"; en inversa rate = 1 / fila.rate)."""
        quote, quote_divisor = normalize_currency(quote_currency)
        base, base_divisor = normalize_currency(base_currency)
        factor = Decimal(base_divisor) / Decimal(quote_divisor)
        if quote_divisor != 1 or base_divisor != 1:
            found = self.rate_with_provenance(
                db, quote_currency=quote or "", base_currency=base or "", as_of=as_of
            )
            return {**found, "rate": found["rate"] * factor} if found else None
        if quote == base:
            return {
                "rate": Decimal("1"),
                "rate_date": None,
                "source": None,
                "direction": "same",
            }
        direct = db.scalar(
            select(FXRate)
            .where(
                FXRate.base_currency == base,
                FXRate.quote_currency == quote,
                FXRate.rate_date <= as_of,
            )
            .order_by(desc(FXRate.rate_date), desc(FXRate.created_at))
            .limit(1)
        )
        if direct:
            return {
                "rate": direct.rate,
                "rate_date": direct.rate_date,
                "source": direct.source,
                "direction": "direct",
            }
        inverse = db.scalar(
            select(FXRate)
            .where(
                FXRate.base_currency == quote,
                FXRate.quote_currency == base,
                FXRate.rate_date <= as_of,
            )
            .order_by(desc(FXRate.rate_date), desc(FXRate.created_at))
            .limit(1)
        )
        if inverse and inverse.rate:
            return {
                "rate": Decimal("1") / inverse.rate,
                "rate_date": inverse.rate_date,
                "source": inverse.source,
                "direction": "inverse",
            }
        return None

    def fx_table(
        self,
        db: Session,
        *,
        currencies: set[str] | list[str],
        base_currency: str,
        as_of_max: date,
    ) -> dict[tuple[str, str], list[tuple[date, Decimal]]]:
        """Tabla FX (una query) para resolución point-in-time por fila.

        Devuelve {(base, quote): [(rate_date, rate), ...]} ordenado por
        fecha ascendente; combínese con :meth:`rate_from_table` para
        replicar :meth:`rate` sin N+1 y sin filtrar futuro (lookahead).
        """
        base, _ = normalize_currency(base_currency)
        codes = {normalize_currency(str(code))[0] for code in currencies if code}
        codes.add(base)
        rows = list(
            db.scalars(
                select(FXRate)
                .where(
                    FXRate.base_currency.in_(codes),
                    FXRate.quote_currency.in_(codes),
                    FXRate.rate_date <= as_of_max,
                )
                .order_by(FXRate.rate_date, FXRate.created_at)
            ).all()
        )
        table: dict[tuple[str, str], list[tuple[date, Decimal]]] = {}
        for row in rows:
            if row.rate is None:
                continue
            table.setdefault(
                (row.base_currency.upper(), row.quote_currency.upper()), []
            ).append((row.rate_date, row.rate))
        return table

    @staticmethod
    def rate_from_table(
        table: dict[tuple[str, str], list[tuple[date, Decimal]]],
        *,
        quote_currency: str,
        base_currency: str,
        as_of: date,
    ) -> Decimal | None:
        """Equivalente puro en memoria de :meth:`rate` sobre ``fx_table``."""
        from bisect import bisect_right

        quote, quote_divisor = normalize_currency(quote_currency)
        base, base_divisor = normalize_currency(base_currency)
        factor = Decimal(base_divisor) / Decimal(quote_divisor)
        if quote == base:
            return factor
        series = table.get((base, quote))
        if series:
            idx = bisect_right(series, (as_of, Decimal("Infinity"))) - 1
            if idx >= 0:
                return series[idx][1] * factor
        inverse = table.get((quote, base))
        if inverse:
            idx = bisect_right(inverse, (as_of, Decimal("Infinity"))) - 1
            if idx >= 0 and inverse[idx][1]:
                return factor / inverse[idx][1]
        return None

    def rates_for(
        self,
        db: Session,
        *,
        quote_currencies: set[str] | list[str],
        base_currency: str,
        as_of: date,
    ) -> dict[str, Decimal | None]:
        """Resuelve N tipos de cambio con UNA sola query (anti N+1).

        Carga todas las filas FX relevantes (directas e inversas con
        rate_date <= as_of) y elige en Python la más reciente por par,
        replicando la semántica de :meth:`rate`.
        """
        quotes = {str(code) for code in quote_currencies if code}
        base_major, base_divisor = normalize_currency(base_currency)
        if all(normalize_currency(code)[0] == base_major for code in quotes):
            return {
                currency_key(code): Decimal(base_divisor) / Decimal(normalize_currency(code)[1])
                for code in quotes
            }
        table = self.fx_table(
            db, currencies=quotes, base_currency=base_currency, as_of_max=as_of
        )
        return {
            currency_key(code): self.rate_from_table(
                table, quote_currency=code, base_currency=base_currency, as_of=as_of
            )
            for code in quotes
        }

    def upsert_rate(
        self,
        db: Session,
        *,
        base_currency: str,
        quote_currency: str,
        rate: Decimal,
        rate_date: date,
        source: str,
    ) -> FXRate:
        base = base_currency.strip().upper()
        quote = quote_currency.strip().upper()
        if len(base) != 3 or len(quote) != 3 or not base.isalpha() or not quote.isalpha():
            raise ValueError("FX currencies must use three-letter ISO codes")
        if base == quote and rate != Decimal("1"):
            raise ValueError("Same-currency FX rate must equal 1")
        if rate <= 0:
            raise ValueError("FX rate must be positive")
        row = db.scalar(
            select(FXRate).where(
                FXRate.base_currency == base,
                FXRate.quote_currency == quote,
                FXRate.rate_date == rate_date,
            )
        )
        if row is None:
            row = FXRate(
                base_currency=base,
                quote_currency=quote,
                rate_date=rate_date,
            )
            db.add(row)
        row.rate = rate
        row.source = source.strip()[:80] or "manual"
        db.flush()
        return row
