"""Dividend record ingestion from labeled data providers (Yahoo, fallback FMP).

Yahoo Finance chart API is the primary source (free, no key); FMP is the
fallback when Yahoo fails (its key may be dead: errors surface as
unavailable, never fabricated). Declared dividends are ingested as deduped
DividendRecord rows with per-row source and fetched_at provenance.
Dividend cash application to the ledger stays manual.

The provider-to-record skeleton is inherited from ``ProviderIngestionService``.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Company, DividendRecord, Position, WatchItem
from app.services.provenance import Coverage, SourceKind, provenance
from app.services.split_ingestion_service import ProviderIngestionService


class DividendIngestionService(ProviderIngestionService):
    _PROVENANCE_SOURCE = "Yahoo Finance chart/dividends (fallback FMP stable/dividends)"
    _PROVENANCE_NOTE = (
        "Declared dividends from data providers; reconcile against issuer/regulator "
        "notices for material decisions."
    )

    @staticmethod
    def _parse_amount(payload: dict) -> Decimal | None:
        for key in ("adjDividend", "dividend", "amount"):
            raw = payload.get(key)
            if raw is None:
                continue
            try:
                amount = Decimal(str(raw))
            except (InvalidOperation, ValueError):
                continue
            if amount > 0:
                return amount
        return None

    async def _fetch_rows(
        self, company: Company
    ) -> tuple[list[dict[str, Any]], str]:
        """Normalized (ex_date, amount, pay_date, currency) rows + source label.

        Yahoo first (free, no key); FMP only when Yahoo raises. A successful
        empty Yahoo answer means "no dividends declared", not a failure, so
        it does not trigger the fallback.
        """
        symbol = self._provider_symbol(company)
        try:
            payload = await self.yahoo.dividends(symbol)
        except Exception:
            payload = await self.fmp.dividends(symbol)
            rows = payload if isinstance(payload, list) else payload.get("historical", [])
            return [
                {
                    "ex_date": self._parse_date(row.get("date") or row.get("recordDate")),
                    "pay_date": self._parse_date(row.get("paymentDate") or row.get("payDate")),
                    "amount": self._parse_amount(row),
                    "currency": str(row.get("currency") or "USD").upper()[:10],
                }
                for row in rows
                if isinstance(row, dict)
            ], "fmp"
        return [
            {
                "ex_date": self._epoch_to_date(row.get("date")),
                "pay_date": None,  # chart API no expone fecha de pago
                "amount": self._parse_amount(row),
                "currency": (company.currency or "USD").upper()[:10],
            }
            for row in payload
            if isinstance(row, dict)
        ], "yahoo_finance"

    @staticmethod
    def _row_is_ingestible(row: dict[str, Any]) -> bool:
        return row["ex_date"] is not None and row["amount"] is not None

    @staticmethod
    def _existing_record(db: Session, company: Company, row: dict[str, Any]) -> Any:
        return db.scalar(
            select(DividendRecord).where(
                DividendRecord.company_id == company.id,
                DividendRecord.ex_date == row["ex_date"],
                DividendRecord.amount == row["amount"],
            )
        )

    @staticmethod
    def _new_record(
        company: Company, row: dict[str, Any], source: str, fetched_at: datetime
    ) -> Any:
        return DividendRecord(
            company_id=company.id,
            ex_date=row["ex_date"],
            pay_date=row["pay_date"],
            amount=row["amount"],
            currency=row["currency"],
            source=source,
            fetched_at=fetched_at,
        )

    async def sync_portfolio(self, db: Session) -> dict[str, Any]:
        """Posiciones abiertas y watchlist: el Cerebro responde dividendos de ambas.

        El rendimiento de cartera (portfolio_yields) sigue contando solo posiciones.
        """
        held = set(db.scalars(select(Position.company_id).distinct()).all())
        symbols = {x.upper() for x in db.scalars(select(WatchItem.symbol)).all() if x}
        watched = set(db.scalars(select(Company.id).where(Company.ticker.in_(symbols))).all()) if symbols else set()
        ids = held | watched
        tickers = sorted(db.scalars(select(Company.ticker).where(Company.id.in_(ids))).all()) if ids else []
        results = [await self.sync_company(db, ticker=t) for t in tickers]
        ok = sum(1 for r in results if r["status"] == "ok")
        unavailable = sum(1 for r in results if r["status"] == "unavailable")
        return {
            "companies": len(results), "synced": ok, "unavailable": unavailable, "results": results,
            "provenance": provenance(
                self._PROVENANCE_SOURCE, SourceKind.UNOFFICIAL,
                coverage=(Coverage.OK if unavailable == 0 else Coverage.PARTIAL if ok else Coverage.UNAVAILABLE),
                note=self._PROVENANCE_NOTE,
            ),
        }

    def portfolio_yields(self, db: Session) -> dict[str, Any]:
        """Trailing-12-month dividend yield per held position + portfolio aggregate.

        Yield = TTM declared dividends per share / current market price, both in
        the position's native currency. Positions whose dividend currency does
        not match the price currency are excluded from yield math and counted
        honestly in coverage instead of being silently converted: with every
        record skipped there is no dividend in the position's currency, so the
        yield is None (unknown), never 0.0% - a fabricated zero reads as "this
        position pays nothing" and drags the portfolio yield down.

        The portfolio aggregate weights by ``market_value_base`` only. A
        position without a base-currency value has no honest weight (its native
        value is in another currency and summing the two would mix EUR and USD
        into a meaningless total), so it is excluded and reported in coverage.
        """
        cutoff = date.today().replace(year=date.today().year - 1)
        rows = list(
            db.execute(
                select(Position, Company).join(Company, Position.company_id == Company.id)
            ).all()
        )
        positions = []
        with_data = 0
        weighted_yield = 0.0
        weighted_positions = 0
        total_value = 0.0
        missing_base_value: list[str] = []
        for position, company in rows:
            records = list(
                db.scalars(
                    select(DividendRecord).where(
                        DividendRecord.company_id == company.id,
                        DividendRecord.ex_date >= cutoff,
                    )
                ).all()
            )
            price = float(position.market_price or 0)
            # Peso solo en divisa base: `market_value` esta en la divisa nativa
            # y sumarlo mezclaria monedas distintas en el mismo total.
            if position.market_value_base is None:
                missing_base_value.append(company.ticker)
                value = None
            else:
                value = float(position.market_value_base)
                total_value += value
            matching_currency = [r for r in records if r.currency == position.currency]
            ttm = sum(float(r.amount) for r in matching_currency)
            skipped_currency = len(records) - len(matching_currency)
            # Gate on the records actually USED, not on every record: with all
            # of them skipped for currency mismatch ttm is 0 and the old guard
            # published a 0.0% yield that looks like a verified fact.
            dividend_yield = (ttm / price) if price > 0 and matching_currency else None
            if matching_currency:
                with_data += 1
                if dividend_yield is not None and value is not None and value > 0:
                    weighted_yield += dividend_yield * value
                    weighted_positions += 1
            positions.append(
                {
                    "ticker": company.ticker,
                    "ttm_dividend_per_share": ttm if matching_currency else None,
                    "currency": position.currency,
                    "price": price or None,
                    "dividend_yield": dividend_yield,
                    "records_12m": len(records),
                    "matching_currency_records_12m": len(matching_currency),
                    "skipped_currency_mismatch": skipped_currency,
                    "last_fetched_at": (
                        max(r.fetched_at for r in records).isoformat()
                        if records and all(r.fetched_at for r in records)
                        else None
                    ),
                }
            )
        coverage_ratio = (with_data / len(rows)) if rows else 1.0
        return {
            "as_of": date.today().isoformat(),
            "positions": positions,
            # The aggregate is published only when at least one position with a
            # real yield and a real base-currency weight contributed: 0.0%
            # computed from an empty numerator is the same fabrication as the
            # per-position one, one level up.
            "portfolio_yield": (
                (weighted_yield / total_value)
                if weighted_positions and total_value > 0
                else None
            ),
            "coverage": {
                "positions": len(rows),
                "positions_with_dividend_data": with_data,
                "percent": round(100 * coverage_ratio, 1),
                "positions_missing_base_value": sorted(missing_base_value),
            },
            "provenance": provenance(
                "Yahoo Finance/FMP dividends via la base de datos de GerarAI",
                SourceKind.UNOFFICIAL,
                coverage=(
                    Coverage.OK
                    if coverage_ratio >= 1.0
                    else Coverage.PARTIAL if with_data else Coverage.UNAVAILABLE
                ),
                note=(
                    "Trailing-12-month declared dividends per share over current price; "
                    "run POST /portfolio/dividends/sync to refresh. Positions without a "
                    "base-currency value are excluded from the portfolio yield instead of "
                    "being weighted with a native-currency amount."
                ),
            ),
        }
