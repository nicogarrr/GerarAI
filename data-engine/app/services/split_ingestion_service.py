"""Split ingestion from labeled data providers (Yahoo, fallback FMP).

Yahoo Finance chart API is the primary source (free, no key); FMP stable/
splits is the fallback when Yahoo fails (its key may be dead: errors
surface as unavailable, never guessed). Ingested splits become UNAPPLIED
CorporateAction rows with per-row source provenance; the user applies them
explicitly through the existing corporate-actions flow, which adjusts
position quantities and the FIFO ledger.

``ProviderIngestionService`` hosts the provider-to-record skeleton that the
dividend ingestion shares.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, tzinfo
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import redact_secrets
from app.core.tenancy import tenant_filters
from app.models import Company, CorporateAction, Position
from app.services.company_resolver import resolve_company
from app.services.connectors.fmp import FMPClient
from app.services.connectors.yahoo import YahooFinanceClient
from app.services.date_format import format_date_es
from app.services.provenance import Coverage, SourceKind, provenance

_SAME_EVENT_DAYS = 3


class NoSafeProviderSymbol(RuntimeError):
    """Sin simbolo de proveedor calificable por bolsa: NO se consulta nada.

    Yahoo/FMP resuelven el ticker pelado en la linea US (gemelo o ADR): un
    split del gemelo aplicado al listado real corrompe los recuentos de
    acciones (caso real: split 10:1 de Aena 2025-06-19 nunca ingerido porque
    «AENA» no existe en Yahoo — es «AENA.MC» — y de haber existido un
    homonimo US habriamos importado SUS splits). «Sin dato» antes que el
    dato de otro instrumento, mismo criterio que yahoo_symbol.
    """


class ProviderIngestionService:
    """Skeleton for ingesting declared rows from labeled providers into own records.

    Splits and dividends share everything but the row shape: same Yahoo-then-FMP
    fallback, same dedupe-then-insert, same three statuses. Subclasses supply the
    provider row mapping and the record they write.
    """

    _PROVENANCE_SOURCE = ""
    _PROVENANCE_NOTE = ""

    def __init__(
        self,
        fmp: FMPClient | None = None,
        yahoo: YahooFinanceClient | None = None,
    ) -> None:
        self.fmp = fmp or FMPClient()
        self.yahoo = yahoo or YahooFinanceClient()

    @staticmethod
    def _parse_date(value: Any) -> date | None:
        if not value:
            return None
        try:
            return date.fromisoformat(str(value)[:10])
        except ValueError:
            return None

    @staticmethod
    def _epoch_to_date(value: Any, timezone_name: Any = None) -> date | None:
        """Fecha del evento en la zona de su bolsa (UTC si se desconoce).

        Yahoo da el epoch de la apertura local: BHP.AX el 7-mar-2024 a las
        10:00 de Sydney es el 6-mar a las 23:00 UTC."""
        tz: tzinfo = UTC
        if isinstance(timezone_name, str) and timezone_name.strip():
            try:
                tz = ZoneInfo(timezone_name.strip())
            except (ZoneInfoNotFoundError, ValueError):
                tz = UTC
        try:
            return datetime.fromtimestamp(int(value), tz).date()
        except (TypeError, ValueError, OSError, OverflowError):
            return None

    async def _fetch_rows(
        self, company: Company
    ) -> tuple[list[dict[str, Any]], str]:
        raise NotImplementedError

    @staticmethod
    def _provider_symbol(company: Company) -> str:
        """Simbolo calificado por bolsa (AENA -> AENA.MC) o excepcion honesta."""
        from app.services.propicks_price_service import yahoo_symbol

        symbol = yahoo_symbol(company)
        if symbol is None:
            raise NoSafeProviderSymbol(
                f"sin simbolo Yahoo seguro para {company.ticker} "
                f"(bolsa {getattr(company, 'exchange', None)!r}, divisa "
                f"{getattr(company, 'currency', None)!r}): el ticker pelado "
                "resolveria el gemelo/ADR US y sus eventos no son los del "
                "listado real"
            )
        return symbol

    @staticmethod
    def _row_is_ingestible(row: dict[str, Any]) -> bool:
        raise NotImplementedError

    @staticmethod
    def _skip_reason(row: dict[str, Any]) -> str | None:
        """Motivo observable cuando una fila valida no se ingiere (None = no aplica)."""
        return None

    @staticmethod
    def _existing_record(db: Session, company: Company, row: dict[str, Any]) -> Any:
        raise NotImplementedError

    @staticmethod
    def _new_record(
        company: Company, row: dict[str, Any], source: str, fetched_at: datetime
    ) -> Any:
        raise NotImplementedError

    async def sync_company(self, db: Session, *, ticker: str) -> dict[str, Any]:
        """Ingest this company's declared rows. Returns counts + provenance."""
        company = resolve_company(db, ticker)
        if company is None:
            return {"ticker": ticker.upper(), "status": "unknown_company", "inserted": 0, "existing": 0}
        try:
            rows, source = await self._fetch_rows(company)
        except NoSafeProviderSymbol as exc:
            return {
                "ticker": company.ticker,
                "status": "no_safe_symbol",
                "error": redact_secrets(str(exc))[:300],
                "inserted": 0,
                "existing": 0,
            }
        except Exception as exc:  # provider/auth/entitlement/network failure
            return {
                "ticker": company.ticker,
                "status": "unavailable",
                "error": redact_secrets(f"{type(exc).__name__}: {exc}")[:300],
                "inserted": 0,
                "existing": 0,
            }
        fetched_at = datetime.now(UTC)
        inserted = 0
        existing = 0
        skipped: dict[str, int] = {}
        for row in rows:
            if not self._row_is_ingestible(row):
                reason = self._skip_reason(row)
                if reason:
                    skipped[reason] = skipped.get(reason, 0) + 1
                continue
            duplicate = self._existing_record(db, company, row)
            if duplicate is not None:
                existing += 1
                continue
            db.add(self._new_record(company, row, source, fetched_at))
            inserted += 1
        db.commit()
        return {
            "ticker": company.ticker,
            "status": "ok",
            "source": source,
            "inserted": inserted,
            "existing": existing,
            "skipped": skipped,
            "fetched_at": fetched_at.isoformat(),
        }

    async def sync_each(self, db: Session, tickers: list[str]) -> list[dict[str, Any]]:
        """``sync_company`` por ticker sin que uno que revienta corte al resto.

        Los fallos del proveedor ya vuelven como «unavailable»; un fallo al
        GUARDAR (dato raro, restriccion de la BD) salia del bucle y los
        tickers siguientes se quedaban sin sincronizar ese dia y en cada
        reintento. Ese ticker se deshace y queda «failed»; lo transitorio (BD
        o red caidas) relanza para que Dramatiq reintente todo.
        """
        from app.workers.dramatiq_app import _is_transient

        results: list[dict[str, Any]] = []
        for ticker in tickers:
            try:
                results.append(await self.sync_company(db, ticker=ticker))
            except Exception as exc:
                if _is_transient(exc):
                    raise
                db.rollback()
                results.append({
                    "ticker": ticker.upper(),
                    "status": "failed",
                    "error": redact_secrets(f"{type(exc).__name__}: {exc}")[:300],
                    "inserted": 0,
                    "existing": 0,
                })
        return results

    def _portfolio_tickers(self, db: Session) -> list[str]:
        company_ids = db.scalars(
            select(Position.company_id)
            .where(*tenant_filters(db, Position))
            .distinct()
        ).all()
        return list(
            db.scalars(select(Company.ticker).where(Company.id.in_(company_ids))).all()
        ) if company_ids else []

    async def sync_portfolio(self, db: Session) -> dict[str, Any]:
        """Ingest every currently held company."""
        results = await self.sync_each(db, self._portfolio_tickers(db))
        ok = sum(1 for r in results if r["status"] == "ok")
        failed = sum(1 for r in results if r["status"] == "failed")
        unavailable = sum(1 for r in results if r["status"] == "unavailable") + failed
        summary: dict[str, Any] = {
            "companies": len(results),
            "synced": ok,
            "unavailable": unavailable,
            "results": results,
            "provenance": provenance(
                self._PROVENANCE_SOURCE,
                SourceKind.UNOFFICIAL,
                coverage=(
                    Coverage.OK
                    if unavailable == 0
                    else Coverage.PARTIAL if ok else Coverage.UNAVAILABLE
                ),
                note=self._PROVENANCE_NOTE,
            ),
        }
        if failed:  # solo si hubo fallos: el contrato de siempre no cambia
            summary["failed"] = failed
        return summary


class SplitIngestionService(ProviderIngestionService):
    _PROVENANCE_SOURCE = "Yahoo Finance chart/splits (fallback FMP stable/splits)"
    _PROVENANCE_NOTE = (
        "Splits arrive unapplied; verify against issuer/exchange notices before applying to the ledger."
    )

    @staticmethod
    def _parse_ratio(row: dict) -> Decimal | None:
        """Shares after / shares before from numerator/denominator fields."""
        try:
            numerator = Decimal(str(row.get("numerator")))
            denominator = Decimal(str(row.get("denominator")))
        except (InvalidOperation, ValueError, TypeError):
            return None
        if denominator <= 0 or numerator <= 0:
            return None
        # La columna es Numeric(24, 10): se guarda ya a esa precision. Con el
        # cociente completo (28 digitos, p. ej. 5:3) la comparacion de dedupe
        # contra lo guardado en Postgres nunca coincide y cada sync semanal
        # reinserta el mismo split.
        return (numerator / denominator).quantize(Decimal("1e-10"))

    @staticmethod
    def _description(source: str, ratio: float | Decimal, fetched_at: datetime) -> str:
        ratio = float(ratio)  # en BD llega como Decimal; :g sobre Decimal sale roto
        proveedor = "Yahoo Finance" if source == "yahoo_finance" else source.upper()
        if ratio > 1:
            tipo = f"División de acciones {ratio:g} por 1"
        else:
            tipo = f"Agrupación de acciones 1 por {1 / ratio:g}"
        return (
            f"{tipo}. Dato de {proveedor}, importado el {format_date_es(fetched_at.date())}. "
            "Aplicar ajusta tus acciones y el precio medio; el valor de la posición no cambia."
        )

    async def _fetch_rows(
        self, company: Company
    ) -> tuple[list[dict[str, Any]], str]:
        """Normalized (effective_date, ratio) rows + source label.

        Yahoo first (free, no key); FMP only when Yahoo raises. A successful
        empty Yahoo answer means "no splits", not a failure, so it does not
        trigger the fallback.
        """
        symbol = self._provider_symbol(company)
        try:
            payload = await self.yahoo.splits(symbol)
        except Exception:
            payload = await self.fmp.splits(symbol)
            rows = payload if isinstance(payload, list) else payload.get("historical", [])
            return [
                {
                    "effective_date": self._parse_date(row.get("date")),
                    "ratio": self._parse_ratio(row),
                }
                for row in rows
                if isinstance(row, dict)
            ], "fmp"
        return [
            {
                "effective_date": self._epoch_to_date(
                    row.get("date"), row.get("exchangeTimezoneName")
                ),
                "ratio": self._parse_ratio(row),
            }
            for row in payload
            if isinstance(row, dict)
        ], "yahoo_finance"

    @staticmethod
    def _row_is_ingestible(row: dict[str, Any]) -> bool:
        # Ratio 1 (1:1) no cambia el numero de acciones: Yahoo/FMP lo usan como
        # marcador (spin-off, cambio de nominal). Guardarlo creaba una
        # «Agrupación de acciones 1 por 1» pendiente de aplicar.
        return (
            row["effective_date"] is not None
            and row["ratio"] is not None
            and row["ratio"] != 1
        )

    @staticmethod
    def _skip_reason(row: dict[str, Any]) -> str | None:
        if row["effective_date"] is not None and row["ratio"] == 1:
            return "ratio_1_no_split"
        return None

    @staticmethod
    def _existing_record(db: Session, company: Company, row: dict[str, Any]) -> Any:
        return db.scalar(
            select(CorporateAction).where(
                CorporateAction.company_id == company.id,
                # +-3 dias: Yahoo y FMP (el respaldo) fechan el mismo split con
                # un dia de diferencia; con fecha exacta, un fallo puntual de
                # Yahoo duplicaba el evento con la fecha del otro proveedor.
                CorporateAction.effective_date >= row["effective_date"] - timedelta(days=_SAME_EVENT_DAYS),
                CorporateAction.effective_date <= row["effective_date"] + timedelta(days=_SAME_EVENT_DAYS),
                CorporateAction.ratio == row["ratio"],
                CorporateAction.action_type.in_(["split", "reverse_split"]),
            )
        )

    @staticmethod
    def _new_record(
        company: Company, row: dict[str, Any], source: str, fetched_at: datetime
    ) -> Any:
        ratio = row["ratio"]
        return CorporateAction(
            company_id=company.id,
            action_type="split" if ratio > 1 else "reverse_split",
            effective_date=row["effective_date"],
            ratio=ratio,
            description=SplitIngestionService._description(source, ratio, fetched_at),
            applied=False,
            source=source,
            fetched_at=fetched_at,
        )
