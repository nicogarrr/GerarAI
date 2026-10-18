"""Backfill presupuestado de perfiles Finnhub (/quote + /stock/profile2).

PR-D resto: el perfil de compania (nombre real, exchange, divisa, pais de
domicilio) y el market cap de proveedor solo llegaban por caminos on-demand
(cobertura ~0,1%). Este barrido diario rellena el universo respetando el
rate limit del plan gratuito de Finnhub (60 llamadas/min): como mucho
`max_companies` companias por ejecucion y una pausa tras CADA llamada.

Veracidad:
- Solo se escribe lo que la API devuelve; una respuesta vacia se registra
  y no se reintenta hasta pasados `recheck_days` dias (Document
  ``finnhub_profile`` por compania = marcador de reanudacion y
  procedencia declarada).
- market_cap se fecha con la sesion de la quote, nunca con el dia de la
  ingesta; sin fecha honesta no se escribe (mismo contrato que
  thesis_evidence_service: millones USD x1e6, source_type "Finnhub",
  is_reported=True, confianza 0,75).
- Los campos de Company solo se rellenan cuando estan vacios o son
  placeholders; un dato bueno nunca se pisa.
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx
from sqlalchemy import func, select

from app.core.config import get_settings
from app.models.entities import Company, Document, FinancialFact
from app.services.company_enrichment_service import (
    _PLACEHOLDER_EXCHANGES,
    sector_for_industry,
)

logger = logging.getLogger(__name__)

QUOTE_URL = "https://finnhub.io/api/v1/quote"
PROFILE_URL = "https://finnhub.io/api/v1/stock/profile2"
PROFILE_DOC_SOURCE = "finnhub_profile"
_MARKET_CAP_CONFIDENCE = Decimal("0.75")


def _decimal(raw: Any) -> Decimal | None:
    try:
        return Decimal(str(raw))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _quote_session_date(payload: dict[str, Any], today: date) -> date | None:
    """Fecha de sesion de la quote (campo t, epoch); nunca en el futuro."""
    price = _decimal(payload.get("c"))
    ts = payload.get("t")
    if price is None or price <= 0 or not isinstance(ts, (int, float)):
        return None
    session_date = datetime.fromtimestamp(ts, tz=UTC).date()
    return session_date if session_date <= today else None


class FinnhubProfileBackfill:
    def __init__(self, settings=None, client: httpx.Client | None = None) -> None:
        self.settings = settings or get_settings()
        self._client = client or httpx.Client(timeout=15)

    def close(self) -> None:
        self._client.close()

    def _get(self, url: str, ticker: str) -> dict[str, Any] | None:
        key = getattr(self.settings, "finnhub_api_key", None)
        if not key:
            return None
        try:
            resp = self._client.get(url, params={"symbol": ticker, "token": key})
            if resp.status_code == 200:
                return resp.json()
        except httpx.HTTPError as exc:
            logger.warning("Finnhub %s fallo para %s: %s", url, ticker, exc)
        return None

    def _recently_checked(self, db, company_ids: list[int], since: datetime) -> set[int]:
        rows = db.scalars(
            select(Document.company_id)
            .where(
                Document.company_id.in_(company_ids),
                Document.source_type == PROFILE_DOC_SOURCE,
                Document.created_at >= since,
            )
            .group_by(Document.company_id)
        ).all()
        return {row for row in rows if row is not None}

    def backfill(
        self,
        db,
        *,
        max_companies: int = 300,
        sleep_between_calls: float = 1.05,
        recheck_days: int = 30,
        today: date | None = None,
    ) -> dict[str, Any]:
        """Rellena perfiles Finnhub con presupuesto de llamadas. Idempotente."""
        today = today or datetime.now(UTC).date()
        if not getattr(self.settings, "finnhub_api_key", None):
            return {"status": "sin_clave", "detail": "FINNHUB_API_KEY no configurada"}

        since = datetime.now(UTC) - timedelta(days=recheck_days)
        companies = list(db.scalars(select(Company).order_by(Company.ticker)).all())
        checked = self._recently_checked(db, [c.id for c in companies], since)
        pending = [c for c in companies if c.id not in checked][:max_companies]

        stats = {"ok": 0, "sin_datos": 0, "error": 0, "market_cap": 0}
        for company in pending:
            quote = self._get(QUOTE_URL, company.ticker)
            time.sleep(sleep_between_calls)
            profile = self._get(PROFILE_URL, company.ticker)
            time.sleep(sleep_between_calls)
            if profile is None and quote is None:
                stats["error"] += 1
                continue  # error de transporte: sin Document, reintento manana
            profile = profile or {}
            fields: list[str] = []
            if profile.get("name"):
                fields.extend(k for k in ("exchange", "currency", "country", "finnhubIndustry") if profile.get(k))

            changed = False
            name = (profile.get("name") or "").strip()
            if name and (
                not (company.name or "").strip()
                or company.name.strip().upper() == (company.ticker or "").upper()
                or "_" in (company.name or "")
            ):
                company.name = name
                changed = True
            exchange = (profile.get("exchange") or "").strip()
            if exchange and company.exchange in _PLACEHOLDER_EXCHANGES:
                company.exchange = exchange
                changed = True
            currency = (profile.get("currency") or "").strip()
            if currency and not (company.currency or "").strip():
                company.currency = currency
                changed = True
            industry = (profile.get("finnhubIndustry") or "").strip()
            if industry and industry.upper() not in {"N/A", "UNKNOWN"} and not (company.industry or "").strip():
                company.industry = industry
                changed = True
                sector = sector_for_industry(industry)
                if sector and not (company.sector or "").strip():
                    company.sector = sector
            country = (profile.get("country") or "").strip().upper()
            if country and not (company.domicile_country or "").strip():
                company.domicile_country = country
                changed = True

            quote_date = _quote_session_date(quote or {}, today)
            cap = _decimal(profile.get("marketCapitalization"))
            cap_written = False
            if cap is not None and cap > 0 and quote_date is not None:
                period = quote_date.isoformat()
                already = db.scalar(
                    select(func.count(FinancialFact.id)).where(
                        FinancialFact.company_id == company.id,
                        FinancialFact.metric == "market_cap",
                        FinancialFact.period == period,
                        FinancialFact.source_type == "Finnhub",
                    )
                )
                if not already:
                    db.add(
                        FinancialFact(
                            company_id=company.id,
                            metric="market_cap",
                            value=cap * Decimal("1000000"),
                            unit="USD",
                            period=period,
                            source_id=None,
                            source_type="Finnhub",
                            is_reported=True,
                            confidence=_MARKET_CAP_CONFIDENCE,
                        )
                    )
                    cap_written = True
                    stats["market_cap"] += 1

            db.add(
                Document(
                    company_id=company.id,
                    title=f"Finnhub profile backfill {today.isoformat()}",
                    source_type=PROFILE_DOC_SOURCE,
                    source_url=f"{PROFILE_URL}?symbol={company.ticker}",
                    metadata_={
                        "date": today.isoformat(),
                        "ticker": company.ticker,
                        "quote_date": quote_date.isoformat() if quote_date else None,
                        "fields": sorted(fields),
                        "company_updated": changed,
                        "market_cap_written": cap_written,
                        "empty": not profile,
                    },
                )
            )
            if changed:
                db.add(company)
            stats["ok" if profile else "sin_datos"] += 1

        db.commit()
        return {
            "status": "ok",
            "date": today.isoformat(),
            "procesadas": len(pending),
            "pendientes_tras_run": len(companies) - len(checked) - len(pending),
            "presupuesto": max_companies,
            **stats,
        }


def backfill_finnhub_profiles(db, **kwargs) -> dict[str, Any]:
    service = FinnhubProfileBackfill()
    try:
        return service.backfill(db, **kwargs)
    finally:
        service.close()
