"""Dividend record ingestion from labeled data providers (Yahoo, fallback FMP).

Yahoo Finance chart API is the primary source (free, no key); FMP is the
fallback when Yahoo fails (its key may be dead: errors surface as
unavailable, never fabricated). Declared dividends are ingested as deduped
DividendRecord rows with per-row source and fetched_at provenance.
Dividend cash application to the ledger stays manual.

The provider-to-record skeleton is inherited from ``ProviderIngestionService``.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.tenancy import tenant_filters
from app.models import Company, CorporateAction, DividendRecord, Position, WatchItem
from app.services.company_resolver import resolve_company
from app.services.dividend_records import records_in_position_currency, resolve_yahoo_events
from app.services.provenance import Coverage, SourceKind, provenance
from app.services.split_ingestion_service import ProviderIngestionService


class DividendIngestionService(ProviderIngestionService):
    _PROVENANCE_SOURCE = "Yahoo Finance chart/dividends (fallback FMP stable/dividends)"
    _PROVENANCE_NOTE = (
        "Dividends from data providers (Yahoo amounts are split-adjusted, not the original "
        "declared per-share figure); reconcile against issuer/regulator "
        "notices for material decisions."
    )

    def __init__(self, fmp: Any = None, yahoo: Any = None) -> None:
        super().__init__(fmp=fmp, yahoo=yahoo)
        self._last_provider_rows: tuple[int, list[dict[str, Any]]] | None = None

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

    @staticmethod
    def _known_currency(*candidates: Any) -> str | None:
        """Primera divisa presente, o None. La divisa sale del dividendo/listado
        (Yahoo meta.currency, fila FMP), NUNCA de company.currency (divisa de
        reporte: Novartis SIX reporta en USD y paga en CHF) ni de USD por
        omision: sin divisa el dividendo no se ingiere."""
        for value in candidates:
            raw = str(value or "").strip()
            if raw == "GBp":  # peniques: no son libras
                return "GBX"
            text = raw.upper()[:10]
            if text:
                return text
        return None

    async def _fetch_rows(
        self, company: Company
    ) -> tuple[list[dict[str, Any]], str]:
        """Cachea la ultima descarga Yahoo del run: la usa la curacion de splits."""
        rows, source = await self._fetch_provider_rows(company)
        if source == "yahoo_finance":
            self._last_provider_rows = (company.id, rows)
        else:
            self._last_provider_rows = None
        return rows, source

    async def _fetch_provider_rows(
        self, company: Company
    ) -> tuple[list[dict[str, Any]], str]:
        """Normalized (ex_date, amount, pay_date, currency) rows + source label.

        Yahoo first (free, no key); FMP only when Yahoo raises. A successful
        empty Yahoo answer means "no dividends declared", not a failure, so
        it does not trigger the fallback.
        """
        symbol = self._provider_symbol(company)
        try:
            events = await self.yahoo.dividend_events(symbol)
            payload = events["rows"]
            listing_currency = self._known_currency(events.get("currency"))
        except Exception:
            payload = await self.fmp.dividends(symbol)
            rows = payload if isinstance(payload, list) else payload.get("historical", [])
            return [
                {
                    "ex_date": self._parse_date(row.get("date") or row.get("recordDate")),
                    "pay_date": self._parse_date(row.get("paymentDate") or row.get("payDate")),
                    "amount": self._parse_amount(row),
                    "currency": self._known_currency(row.get("currency")),
                }
                for row in rows
                if isinstance(row, dict)
            ], "fmp"
        return [
            {
                "ex_date": self._epoch_to_date(
                    row.get("date"), row.get("exchangeTimezoneName")
                ),
                # Fecha que guardaban las versiones que leian el epoch en UTC
                # (un dia antes en ASX/NZX): permite corregir la fila ya guardada.
                "legacy_utc_ex_date": self._epoch_to_date(row.get("date")),
                "pay_date": None,  # chart API no expone fecha de pago
                "amount": self._parse_amount(row),
                "currency": listing_currency,
            }
            for row in payload
            if isinstance(row, dict)
        ], "yahoo_finance"

    @staticmethod
    def _row_is_ingestible(row: dict[str, Any]) -> bool:
        return (
            row["ex_date"] is not None
            and row["amount"] is not None
            and bool(row.get("currency"))
        )

    @staticmethod
    def _skip_reason(row: dict[str, Any]) -> str | None:
        if row["ex_date"] is not None and row["amount"] is not None and not row.get("currency"):
            return "unknown_currency"
        return None

    async def sync_company(self, db: Session, *, ticker: str) -> dict[str, Any]:
        """Como la base, pero «sin divisa, no ingerido» es DESCONOCIDO: no un
        exito fresco con 0 filas."""
        result = await super().sync_company(db, ticker=ticker)
        if result.get("status") == "ok":
            company = resolve_company(db, ticker)
            if company is not None:
                healed = self._heal_split_readjustments(db, company)
                if healed:
                    db.commit()
                    result["split_readjustments_healed"] = healed
        unknown = (result.get("skipped") or {}).get("unknown_currency", 0)
        if result.get("status") == "ok" and unknown:
            result["currency_unknown_rows"] = unknown
            if not (result["inserted"] or result["existing"]):
                result["status"] = "currency_unknown"
                result["reason"] = (
                    "el proveedor no informo la divisa del dividendo; "
                    "no se ingirio nada y el estado no esta actualizado"
                )
        return result

    _SPLIT_HEAL_TOLERANCE = Decimal("0.005")

    @staticmethod
    def _split_factor_since(db: Session, company_id: int, ex_date: date, until: date) -> Decimal:
        """Producto de los ratios de split ingeridos entre ex_date (excluido) y until."""
        stmt = select(CorporateAction.ratio).where(
            CorporateAction.company_id == company_id,
            CorporateAction.action_type.in_(["split", "reverse_split"]),
            CorporateAction.effective_date > ex_date,
            CorporateAction.effective_date <= until,
        )
        factor = Decimal("1")
        for ratio in db.scalars(stmt):
            factor *= Decimal(ratio)
        return factor

    def _heal_split_readjustments(self, db: Session, company: Company) -> int:
        """Borra filas Yahoo viejas sin reajustar cuando un split ingerido las explica.

        Doble evidencia exigida (nunca ratio a solas): el proveedor sirve HOY el
        importe reajustado para ese ex_date Y un split ingerido entre el ex_date y
        hoy explica la relacion vieja/nueva dentro de la tolerancia. Solo se tocan
        grupos donde TODA fila que no coincide con el proveedor encaja con el
        factor; si hay cualquier otra discrepancia el grupo queda intacto y
        `resolve_yahoo_events` lo sigue marcando incierto.
        """
        cached = self._last_provider_rows
        if not cached or cached[0] != company.id:
            return 0
        provider_amounts: dict[tuple[date, str | None], set[Decimal]] = defaultdict(set)
        for row in cached[1]:
            if row["ex_date"] is not None and row["amount"] is not None:
                provider_amounts[(row["ex_date"], row["currency"])].add(Decimal(row["amount"]))
        records = db.scalars(
            select(DividendRecord).where(
                DividendRecord.company_id == company.id,
                DividendRecord.source == "yahoo_finance",
            )
        ).all()
        groups: dict[tuple[date, str], list[Any]] = defaultdict(list)
        for rec in records:
            groups[(rec.ex_date, rec.currency)].append(rec)
        healed = 0
        today = date.today()
        for (ex_date, currency), recs in groups.items():
            amounts = {Decimal(rec.amount) for rec in recs}
            if len(amounts) < 2:
                continue
            currents = provider_amounts.get((ex_date, currency))
            if not currents:
                continue
            factor = self._split_factor_since(db, company.id, ex_date, today)
            if factor <= 1:
                continue
            stale = [
                rec
                for rec in recs
                if Decimal(rec.amount) not in currents
                and any(
                    current > 0
                    and abs(Decimal(rec.amount) / current - factor) <= factor * self._SPLIT_HEAL_TOLERANCE
                    for current in currents
                )
            ]
            unexplained = [
                rec
                for rec in recs
                if Decimal(rec.amount) not in currents and rec not in stale
            ]
            if stale and not unexplained:
                for rec in stale:
                    db.delete(rec)
                healed += len(stale)
        return healed

    @staticmethod
    def _existing_record(db: Session, company: Company, row: dict[str, Any]) -> Any:
        record = db.scalar(
            select(DividendRecord).where(
                DividendRecord.company_id == company.id,
                DividendRecord.ex_date == row["ex_date"],
                DividendRecord.amount == row["amount"],
            )
        )
        legacy = row.get("legacy_utc_ex_date")
        if record is not None or legacy is None or legacy == row["ex_date"]:
            return record
        # Fila guardada con la fecha UTC (un dia antes en ASX/NZX): se corrige
        # en sitio en vez de duplicar el cobro.
        record = db.scalar(
            select(DividendRecord).where(
                DividendRecord.company_id == company.id,
                DividendRecord.ex_date == legacy,
                DividendRecord.amount == row["amount"],
                DividendRecord.source == "yahoo_finance",
            )
        )
        if record is not None:
            record.ex_date = row["ex_date"]
        return record

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
        held = set(
            db.scalars(
                select(Position.company_id)
                .where(*tenant_filters(db, Position))
                .distinct()
            ).all()
        )
        symbols = {
            x.upper()
            for x in db.scalars(
                select(WatchItem.symbol).where(*tenant_filters(db, WatchItem))
            ).all()
            if x
        }
        watched = set(db.scalars(select(Company.id).where(Company.ticker.in_(symbols))).all()) if symbols else set()
        ids = held | watched
        tickers = sorted(db.scalars(select(Company.ticker).where(Company.id.in_(ids))).all()) if ids else []
        results = [await self.sync_company(db, ticker=t) for t in tickers]
        ok = sum(1 for r in results if r["status"] == "ok")
        unavailable = sum(1 for r in results if r["status"] == "unavailable")
        unknown = sum(1 for r in results if r["status"] == "currency_unknown" or r.get("currency_unknown_rows"))
        unavailable += unknown  # desconocido/no actualizado: cobertura parcial, nunca OK
        return {
            "companies": len(results), "synced": ok, "unavailable": unavailable,
            "currency_unknown": unknown, "results": results,
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
        # Ventana TTM = (hoy - 1 año, hoy]: un dividendo ya declarado con
        # ex_date futuro todavia no forma parte de los ultimos 12 meses (antes
        # se sumaba y un pagador trimestral salia con 5 pagos: yield +25 %), y
        # el ex_date de hace exactamente un año tampoco (es el pago que el de
        # hoy sustituye). Mismo criterio que DividendProjectionService.
        today = date.today()
        try:
            cutoff = today.replace(year=today.year - 1)
        except ValueError:  # 29 de febrero -> 28 en el año anterior
            cutoff = today.replace(year=today.year - 1, day=28)
        rows = list(
            db.execute(
                select(Position, Company).join(Company, Position.company_id == Company.id)
            ).all()
        )
        # Una sola consulta para los dividendos TTM de todas las empresas en
        # cartera (antes, una por posicion: N+1). Se agrupan por empresa en
        # memoria; resolve_yahoo_events recibe exactamente las mismas filas.
        company_ids = sorted({company.id for _position, company in rows})
        records_by_company: dict[int, list[DividendRecord]] = {}
        if company_ids:
            for record in db.scalars(
                select(DividendRecord)
                .where(
                    DividendRecord.company_id.in_(company_ids),
                    DividendRecord.ex_date > cutoff,
                    DividendRecord.ex_date <= today,
                )
                .order_by(DividendRecord.company_id, DividendRecord.ex_date, DividendRecord.id)
            ).all():
                records_by_company.setdefault(record.company_id, []).append(record)
        positions = []
        with_data = 0
        weighted_yield = 0.0
        weighted_positions = 0
        total_value = 0.0
        missing_base_value: list[str] = []
        for position, company in rows:
            records, uncertain = resolve_yahoo_events(records_by_company.get(company.id, []))
            # nosemgrep: gerarai-money-none-to-zero -- columna NOT NULL (default 0): el `or 0` no convierte ningun None real
            price = float(position.market_price or 0)
            # Peso solo en divisa base: `market_value` esta en la divisa nativa
            # y sumarlo mezclaria monedas distintas en el mismo total.
            if position.market_value_base is None:
                missing_base_value.append(company.ticker)
                value = None
            else:
                value = float(position.market_value_base)
                total_value += value
            # GBX (dividendo Yahoo en peniques) frente a GBp/GBP de la posicion:
            # misma moneda, se convierte sin FX; otra moneda no se mezcla.
            matching_currency = records_in_position_currency(records, position.currency)
            ttm = sum(float(r.amount) for r in matching_currency)
            skipped_currency = len(records) - len(matching_currency)
            # Gate on the records actually USED, not on every record: with all
            # of them skipped for currency mismatch ttm is 0 and the old guard
            # published a 0.0% yield that looks like a verified fact.
            # Evento Yahoo con importes distintos sin evidencia de split: el
            # total seria incierto -> sin yield (no se elige uno por defecto).
            dividend_yield = (ttm / price) if price > 0 and matching_currency and not uncertain else None
            if matching_currency:
                with_data += 1
                if dividend_yield is not None and value is not None and value > 0:
                    weighted_yield += dividend_yield * value
                    weighted_positions += 1
            positions.append(
                {
                    "ticker": company.ticker,
                    "ttm_dividend_per_share": ttm if matching_currency and not uncertain else None,
                    "uncertain_dividend_events": [
                        {"ex_date": u.ex_date.isoformat(), "amounts": [str(a) for a in u.amounts]}
                        for u in uncertain
                    ],
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
