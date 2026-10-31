"""Eventos de resultados e índice de filings por compañía (ficha Quartr-like, Fase 1).

Fuentes gratuitas, todo con fuente y fecha; la ausencia es un estado honesto,
nunca un dato inventado:

- Finnhub ``/calendar/earnings`` (tier gratis): próxima fecha de resultados,
  hora (bmo/amc) y estimaciones de EPS/ingresos.
- Finnhub ``/stock/earnings`` (tier gratis): historial de 4 trimestres con
  EPS real vs estimado y sorpresa.
- SEC EDGAR submissions (data.sec.gov, sin key): índice de filings
  10-K/10-Q/8-K/DEF 14A... con fecha y enlace directo a sec.gov (lo abre el
  navegador del usuario; la VM no descarga el documento).

Nunca lanza por red: cada fuente degrada a ``status="unavailable"`` con el
motivo. La red es inyectable (tests herméticos sin salir a internet).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import redact_secrets
from app.core.tenancy import tenant_filters
from app.models import Company, Document
from app.models.entities import (
    DividendRecord,
    EarningsDate,
    InsiderTransaction,
    NewsEvent,
    Position,
    Transaction,
)
from app.services.connectors.finnhub import FinnhubClient
from app.services.connectors.sec import SECClient
from app.services.document_visibility import without_archive_duplicates

logger = logging.getLogger(__name__)

FILING_FORMS = (
    "10-K",
    "10-K/A",
    "10-Q",
    "10-Q/A",
    "8-K",
    "8-K/A",
    "DEF 14A",
    "20-F",
    "6-K",
)

CALENDAR_CHUNK_DAYS = 90
# Tope total (cik + submissions + reintentos + EFTS) de la SEC dentro del GET
# /api/companies/{ticker}/filings.
FILINGS_SEC_BUDGET_SECONDS = 4.0
CALENDAR_PAST_DAYS = 400
CALENDAR_FUTURE_DAYS = 120

# Tipo de los fetchers inyectables: mismas firmas que los métodos reales.
CalendarFetcher = Callable[[str, str], Awaitable[dict[str, Any] | None]]
EpsHistoryFetcher = Callable[[str], Awaitable[list[dict[str, Any]] | None]]
SubmissionsFetcher = Callable[[str], Awaitable[dict[str, Any] | None]]
CikFetcher = Callable[[str], Awaitable[str | None]]


def _utcnow() -> datetime:
    return datetime.now(UTC)


class CompanyEventsService:
    def __init__(
        self,
        db: Session,
        *,
        calendar_fetcher: CalendarFetcher | None = None,
        eps_history_fetcher: EpsHistoryFetcher | None = None,
        submissions_fetcher: SubmissionsFetcher | None = None,
        cik_fetcher: CikFetcher | None = None,
    ) -> None:
        self.db = db
        self._finnhub = FinnhubClient()
        self._sec = SECClient()
        self._calendar_fetcher = calendar_fetcher or self._fetch_calendar_chunk
        self._eps_fetcher = eps_history_fetcher or self._fetch_eps_history
        self._submissions_fetcher = submissions_fetcher or self._fetch_submissions
        self._cik_fetcher = cik_fetcher or self._fetch_cik

    # ------------------------------------------------------------------
    # Fetchers reales (envoltura fina sobre los connectors)
    # ------------------------------------------------------------------
    async def _fetch_calendar_chunk(
        self, from_date: str, to_date: str
    ) -> dict[str, Any] | None:
        if not self._finnhub.configured():
            return None
        try:
            payload = await self._finnhub._get(
                "/calendar/earnings", {"from": from_date, "to": to_date}
            )
        except Exception as exc:  # red, 4xx/5xx, timeout: degradación honesta
            logger.warning("finnhub calendar/earnings %s→%s falló: %s", from_date, to_date, redact_secrets(str(exc)))
            return None
        return payload if isinstance(payload, dict) else None

    async def _fetch_eps_history(self, symbol: str) -> list[dict[str, Any]] | None:
        if not self._finnhub.configured():
            return None
        try:
            payload = await self._finnhub._get("/stock/earnings", {"symbol": symbol})
        except Exception as exc:
            logger.warning("finnhub stock/earnings %s falló: %s", symbol, redact_secrets(str(exc)))
            return None
        return payload if isinstance(payload, list) else None

    async def _fetch_submissions(self, cik: str) -> dict[str, Any] | None:
        try:
            payload = await self._sec.submissions(cik)
        except Exception as exc:
            logger.warning("EDGAR submissions CIK%s falló: %s", cik, redact_secrets(str(exc)))
            return None
        return payload if isinstance(payload, dict) else None

    async def _fetch_cik(self, ticker: str) -> str | None:
        try:
            return await self._sec.cik_for_ticker(ticker)
        except Exception as exc:
            logger.warning("EDGAR cik_for_ticker %s falló: %s", ticker, redact_secrets(str(exc)))
            return None

    # ------------------------------------------------------------------
    # Eventos de resultados
    # ------------------------------------------------------------------
    async def get_events(self, company: Company) -> dict[str, Any]:
        today = _utcnow().date()
        chunks: list[tuple[date, date]] = []
        start = today - timedelta(days=CALENDAR_PAST_DAYS)
        while start < today + timedelta(days=CALENDAR_FUTURE_DAYS):
            end = min(start + timedelta(days=CALENDAR_CHUNK_DAYS - 1),
                      today + timedelta(days=CALENDAR_FUTURE_DAYS))
            chunks.append((start, end))
            start = end + timedelta(days=1)

        calendar_rows: list[dict[str, Any]] = []
        calendar_ok = False
        for chunk_start, chunk_end in chunks:
            payload = await self._calendar_fetcher(
                chunk_start.isoformat(), chunk_end.isoformat()
            )
            if payload is None:
                continue
            calendar_ok = True
            for row in payload.get("earningsCalendar") or []:
                if str(row.get("symbol", "")).upper() == company.ticker.upper():
                    calendar_rows.append(row)

        eps_rows = await self._eps_fetcher(company.ticker)

        next_event = self._next_event(calendar_rows, today)
        history = self._history(calendar_rows, eps_rows, today)

        return {
            "ticker": company.ticker,
            "company_name": company.name,
            "as_of": _utcnow().isoformat(),
            "calendar_status": "ok" if calendar_ok else "unavailable",
            "eps_history_status": "ok" if eps_rows is not None else "unavailable",
            "next_event": next_event,
            "history": history,
            "source": "Finnhub (calendar/earnings + stock/earnings, tier gratuito)",
            "note": None
            if (calendar_ok or eps_rows is not None)
            else "Sin datos de calendario de resultados: Finnhub no disponible o sin cobertura para este ticker.",
        }

    @staticmethod
    def _parse_day(value: Any) -> date | None:
        if not value:
            return None
        try:
            return date.fromisoformat(str(value)[:10])
        except ValueError:
            return None

    def _next_event(
        self, rows: list[dict[str, Any]], today: date
    ) -> dict[str, Any] | None:
        future = [
            row for row in rows
            if (day := self._parse_day(row.get("date"))) is not None and day >= today
        ]
        if not future:
            return None
        row = min(future, key=lambda r: self._parse_day(r.get("date")) or today)
        return {
            "date": row.get("date"),
            "hour": row.get("hour") or None,
            "quarter": row.get("quarter"),
            "year": row.get("year"),
            "eps_estimate": row.get("epsEstimate"),
            "revenue_estimate": row.get("revenueEstimate"),
            "source": "Finnhub /calendar/earnings",
        }

    def _history(
        self,
        calendar_rows: list[dict[str, Any]],
        eps_rows: list[dict[str, Any]] | None,
        today: date,
    ) -> list[dict[str, Any]]:
        by_period: dict[str, dict[str, Any]] = {}
        for row in calendar_rows:
            day = self._parse_day(row.get("date"))
            if day is None or day >= today:
                continue
            period = day.isoformat()
            by_period[period] = {
                "period": period,
                "quarter": row.get("quarter"),
                "year": row.get("year"),
                "eps_estimate": row.get("epsEstimate"),
                "eps_actual": row.get("epsActual"),
                "revenue_estimate": row.get("revenueEstimate"),
                "revenue_actual": row.get("revenueActual"),
                "eps_surprise_percent": None,
                "source": "Finnhub /calendar/earnings",
            }
        for row in eps_rows or []:
            period = str(row.get("period") or "")
            if not period:
                continue
            entry = by_period.setdefault(
                period,
                {
                    "period": period,
                    "quarter": row.get("quarter"),
                    "year": row.get("year"),
                    "eps_estimate": None,
                    "eps_actual": None,
                    "revenue_estimate": None,
                    "revenue_actual": None,
                    "eps_surprise_percent": None,
                    "source": "Finnhub /stock/earnings",
                },
            )
            if entry["eps_estimate"] is None:
                entry["eps_estimate"] = row.get("estimate")
            if entry["eps_actual"] is None:
                entry["eps_actual"] = row.get("actual")
            entry["eps_surprise_percent"] = row.get("surprisePercent")
        return sorted(
            by_period.values(), key=lambda item: item["period"], reverse=True
        )[:8]

    # ------------------------------------------------------------------
    # Índice de filings
    # ------------------------------------------------------------------
    async def get_filings(self, company: Company, *, limit: int = 40) -> dict[str, Any]:
        # Presupuesto TOTAL de red para la SEC dentro del GET: con EDGAR caido,
        # los reintentos con backoff + el fallback EFTS tardaban ~15 s y el
        # usuario esperaba con la pestana colgada. Pasado el presupuesto se
        # sirve lo que ya hay en la base (documentos importados) con estado
        # honesto ``unavailable``.
        loop = asyncio.get_running_loop()
        deadline = loop.time() + FILINGS_SEC_BUDGET_SECONDS
        timed_out = False
        cik: str | None = company.cik
        if not cik:
            try:
                cik = await asyncio.wait_for(
                    self._cik_fetcher(company.ticker), max(0.0, deadline - loop.time())
                )
            except TimeoutError:
                timed_out = True
                cik = None
        filings: list[dict[str, Any]] = []
        sec_status = "unavailable"
        note: str | None = None
        partial_source: str | None = None

        if cik:
            try:
                payload = await asyncio.wait_for(
                    self._submissions_fetcher(str(cik).zfill(10)),
                    max(0.0, deadline - loop.time()),
                )
            except TimeoutError:
                timed_out = True
                payload = None
                logger.warning(
                    "EDGAR submissions CIK%s sin respuesta en %.1fs; se sirve la base",
                    cik,
                    FILINGS_SEC_BUDGET_SECONDS,
                )
            if payload is not None:
                fallback = payload.get("_fallback")
                # Origen y estado honestos: una respuesta reconstruida desde
                # EDGAR full-text search es PARCIAL, no "ok" de data.sec.gov.
                sec_status = "partial" if fallback else "ok"
                filings = self._map_submissions(str(cik), payload, company.ticker, limit)
                if fallback:
                    partial_source = "SEC EDGAR full-text search (efts.sec.gov), cobertura parcial"
                    for entry in filings:
                        entry["source"] = "SEC EDGAR (efts.sec.gov)"
                    note = payload.get("_fallback_note") or partial_source
            elif timed_out:
                note = "SEC EDGAR no respondió a tiempo; se listan los documentos ya importados."
            else:
                note = "SEC EDGAR no accesible desde el servidor en este momento."
        elif timed_out:
            note = "SEC EDGAR no respondió a tiempo; se listan los documentos ya importados."
        if not filings:
            db_docs = self._db_documents(company, limit)
            if db_docs:
                note = note or "Sin índice SEC; se listan documentos ya importados."
        return {
            "ticker": company.ticker,
            "company_name": company.name,
            "as_of": _utcnow().isoformat(),
            "sec_status": sec_status,
            "filings": filings,
            "documents": self._db_documents(company, limit),
            "source": (partial_source or "SEC EDGAR (data.sec.gov)") if filings else None,
            "note": note
            or (None if filings else "Sin filings SEC para este ticker (¿compañía no estadounidense?). Documentos ESEF/CNMV llegan en Fase 2."),
        }

    @staticmethod
    def _column(recent: dict[str, Any], name: str, index: int) -> Any:
        values = recent.get(name) or []
        return values[index] if index < len(values) else None

    def _map_submissions(
        self, cik: str, payload: dict[str, Any], ticker: str, limit: int
    ) -> list[dict[str, Any]]:
        recent = (payload.get("filings") or {}).get("recent") or {}
        accessions = recent.get("accessionNumber") or []
        allowed = {form.upper() for form in FILING_FORMS}
        items: list[dict[str, Any]] = []
        for index, accession in enumerate(accessions):
            form = self._column(recent, "form", index)
            if not form or str(form).upper() not in allowed:
                continue
            primary_document = self._column(recent, "primaryDocument", index)
            try:
                url = (
                    SECClient.filing_document_url(cik, str(accession), str(primary_document))
                    if primary_document
                    else SECClient.filing_index_url(cik, str(accession))
                )
            except ValueError:
                continue
            items.append(
                {
                    "form": str(form),
                    "filed_at": self._column(recent, "filingDate", index),
                    "period": self._column(recent, "reportDate", index),
                    "accession": str(accession),
                    "url": url,
                    "source": "SEC EDGAR",
                }
            )
            if len(items) >= limit:
                break
        return items

    def _db_documents(self, company: Company, limit: int) -> list[dict[str, Any]]:
        # F252: hay filas duplicadas del mismo filing de la SEC (re-ingestas
        # historicas con bytes ligeramente distintos). El dedupe se hace en
        # SQL antes del LIMIT para que el limite se aplique sobre las filas
        # ya visibles; sin URL no se deduplica por titulo: dos notas
        # homonimas con contenido distinto son documentos distintos y se
        # muestran ambos, igual que en la vista global.
        rows = self.db.execute(
            without_archive_duplicates(
                select(Document).where(Document.company_id == company.id)
            )
            .order_by(Document.created_at.desc())
            .limit(limit)
        ).scalars().all()
        return [
            {
                "title": row.title,
                "source_type": row.source_type,
                "url": row.source_url,
                "published_at": row.published_at.isoformat() if row.published_at else None,
                "imported_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ]



# ---------------------------------------------------------------------------
# Eventos guardados para el gráfico de precio de la ficha («Precio y eventos»).
# Solo tablas propias: resultados (earnings_dates), dividendos (dividend_records),
# filings y noticias (news_events), insiders (insider_transactions) y la posición
# (positions/transactions). Ninguna llamada a proveedores en la petición.
# ---------------------------------------------------------------------------
TIMELINE_INSIDER_MIN_VALUE = 100_000.0
TIMELINE_NEWS_MIN_MATERIALITY = 5
TIMELINE_FILING_TYPES = frozenset({"new_filing", "ownership_disclosure", "sec_filing"})


def _timeline_float(value: Any) -> float | None:
    try:
        out = float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
    return out if out is not None and out == out and out not in (float("inf"), float("-inf")) else None


def _timeline_day(value: Any) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def stored_holding(db: Session, company: Company) -> dict[str, Any] | None:
    """Precio medio ponderado y primera compra de la posición del tenant (None si no la tiene)."""
    positions = db.scalars(select(Position).where(Position.company_id == company.id, *tenant_filters(db, Position))).all()
    qty = sum((_timeline_float(p.quantity) or 0.0) for p in positions)
    if qty <= 0:
        return None
    cost = sum((_timeline_float(p.quantity) or 0.0) * (_timeline_float(p.average_cost) or 0.0) for p in positions)
    first_buy = db.scalar(
        select(func.min(Transaction.trade_date)).where(
            Transaction.company_id == company.id,
            func.lower(Transaction.action) == "buy",
            *tenant_filters(db, Transaction),
        )
    )
    return {
        "average_cost": round(cost / qty, 4) if cost > 0 else None,
        "first_buy_date": first_buy.isoformat() if first_buy else None,
    }


def stored_timeline_events(db: Session, company: Company, desde: date, hasta: date) -> list[dict[str, Any]]:
    """Eventos fechados y con fuente entre ``desde`` y ``hasta`` (ambos incluidos), más recientes primero."""
    events: list[dict[str, Any]] = []
    ticker = (company.ticker or "").upper()
    for row in db.scalars(
        select(EarningsDate).where(
            func.upper(EarningsDate.ticker) == ticker,
            EarningsDate.event_date >= desde,
            EarningsDate.event_date <= hasta,
        )
    ).all():
        source = row.source_label or row.source
        if not source:
            continue
        events.append({
            "id": f"earnings-{row.id}",
            "date": row.event_date.isoformat(),
            "kind": "results",
            "title": f"Resultados {row.fiscal_label}" if row.fiscal_label else "Resultados",
            "detail": "Fecha confirmada por la fuente" if row.confirmed else None,
            "source": source,
            "source_url": row.source_url,
        })
    for row in db.scalars(
        select(DividendRecord).where(
            DividendRecord.company_id == company.id,
            DividendRecord.ex_date >= desde,
            DividendRecord.ex_date <= hasta,
            *tenant_filters(db, DividendRecord),
        )
    ).all():
        if not row.source:
            continue
        amount = _timeline_float(row.amount)
        events.append({
            "id": f"dividend-{row.id}",
            "date": row.ex_date.isoformat(),
            "kind": "ex_dividend",
            "title": "Ex-dividendo",
            "detail": f"{amount:g} {row.currency} por acción" if amount else None,
            "source": row.source,
            "source_url": None,
        })
    start_dt = datetime.combine(desde, datetime.min.time(), tzinfo=UTC)
    end_dt = datetime.combine(hasta + timedelta(days=1), datetime.min.time(), tzinfo=UTC)
    for row in db.scalars(
        select(NewsEvent).where(
            NewsEvent.company_id == company.id,
            NewsEvent.date >= start_dt,
            NewsEvent.date < end_dt,
            *tenant_filters(db, NewsEvent),
        )
    ).all():
        is_filing = bool(row.sec_filing_identity) or row.event_type in TIMELINE_FILING_TYPES
        if not is_filing and (row.materiality_score or 0) < TIMELINE_NEWS_MIN_MATERIALITY:
            continue
        if not row.source or not row.date or not row.title:
            continue
        events.append({
            "id": f"news-{row.id}",
            "date": row.date.date().isoformat(),
            "kind": "filing" if is_filing else "news",
            "title": row.title,
            "detail": row.summary or None,
            "source": row.source,
            "source_url": row.url,
        })
    for row in db.scalars(
        select(InsiderTransaction).where(
            func.upper(InsiderTransaction.issuer_ticker) == ticker, *tenant_filters(db, InsiderTransaction)
        )
    ).all():
        value = _timeline_float(row.value)
        day = _timeline_day(row.tx_date)
        if day is None or not (desde <= day <= hasta) or value is None or value < TIMELINE_INSIDER_MIN_VALUE:
            continue
        if row.code not in ("P", "S") or row.is_derivative:
            continue
        events.append({
            "id": f"insider-{row.id}",
            "date": day.isoformat(),
            "kind": "insider",
            "title": f"{row.insider or 'Un directivo'} {'compra' if row.code == 'P' else 'vende'} acciones",
            "detail": f"Operación de {value:,.0f} $ (formulario {row.form})".replace(",", "."),
            "source": "SEC",
            "source_url": row.source_url,
        })
    events.sort(key=lambda e: (e["date"], e["id"]), reverse=True)
    return events
