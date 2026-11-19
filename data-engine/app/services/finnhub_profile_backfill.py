"""Backfill presupuestado de perfiles Finnhub (/quote + /stock/profile2).

PR-D resto: el perfil de compania (nombre real, exchange, divisa, pais de
domicilio) y el market cap de proveedor solo llegaban por caminos on-demand
(cobertura ~0,1%). Este barrido diario rellena el universo respetando el
rate limit del plan gratuito de Finnhub (60 llamadas/min): como mucho
`max_companies` companias por ejecucion y CADA llamada reservando su hueco
en el pacer global compartido (~50/min entre TODOS los carriles; antes un
sleep propio de 1,05 s marcaba ~57/min solo este barrido e invisible para
los demas carriles, y un 429 no cortaba nada: hasta 600 llamadas contra la
ventana cerrada). Un 429 propaga el cooldown compartido y corta la corrida;
lo no procesado queda sin Document y lo retoma el cron de manana.

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
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx
from sqlalchemy import select

from app.core.config import get_settings
from app.core.tenancy import tenant_filters
from app.models.entities import Company, Document, FinancialFact
from app.services.company_enrichment_service import (
    _PLACEHOLDER_EXCHANGES,
    profile_ir_url,
    sector_for_industry,
)
from app.services.connectors.base import UpstreamRateLimited, retry_after_seconds
from app.services.connectors.finnhub import finnhub_pacer

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
    def __init__(self, settings=None, client: httpx.Client | None = None, pacer=None) -> None:
        self.settings = settings or get_settings()
        self._client = client or httpx.Client(timeout=15)
        # Pacer GLOBAL compartido (precios, valoracion, IR y este backfill
        # reservan el mismo hueco ~50/min). Inyectable en tests; el real
        # es el singleton del conector.
        self._pacer = pacer if pacer is not None else finnhub_pacer()

    def close(self) -> None:
        self._client.close()

    def _get(self, url: str, ticker: str) -> dict[str, Any] | None:
        key = getattr(self.settings, "finnhub_api_key", None)
        if not key:
            return None
        # Hueco global ANTES de cada llamada: con su propio sleep(1.05) el
        # backfill solo marcaba ~57/min y, sumado a los demas carriles, el
        # agregado superaba la cuota FREE de 60/min y todos comian 429.
        self._pacer.wait_sync()
        try:
            resp = self._client.get(url, params={"symbol": ticker, "token": key})
            if resp.status_code == 429:
                # La ventana es del proveedor y la respetan TODOS los
                # procesos: quien la ve primero la propaga (cool_down en el
                # llamante) y la corrida se corta aqui. Seguir llamando con
                # la ventana cerrada solo mantiene la cuota agotada.
                raise UpstreamRateLimited(
                    f"Finnhub 429 en backfill de perfiles ({url})",
                    # La ventana del proveedor NUNCA se acorta: no es un
                    # reintento inline (ahi cabe el cap), es el cooldown
                    # compartido que respetan todos los procesos. Un
                    # Retry-After de 2 dias se propaga como 2 dias
                    # (objecion del auditor 1, contraejemplo medido).
                    retry_after=retry_after_seconds(resp, cap=float("inf")) or None,
                )
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
                *tenant_filters(db, Document),
            )
            .group_by(Document.company_id)
        ).all()
        return {row for row in rows if row is not None}

    def backfill(
        self,
        db,
        *,
        max_companies: int = 300,
        recheck_days: int = 30,
        today: date | None = None,
    ) -> dict[str, Any]:
        """Rellena perfiles Finnhub con presupuesto de llamadas. Idempotente."""
        today = today or datetime.now(UTC).date()
        if not getattr(self.settings, "finnhub_api_key", None):
            return {"status": "sin_clave", "detail": "FINNHUB_API_KEY no configurada"}

        blocked = float(self._pacer.blocked_for() or 0.0)
        if blocked > 0:
            # Cooldown 429 vigente (lo marco cualquier carril): cero llamadas.
            # El Document de reanudacion de cada empresa pendiente sigue sin
            # escribirse, asi que el cron de manana retoma exactamente aqui.
            return {
                "status": "skipped",
                "reason": "finnhub_cooldown_429",
                "blocked_for_seconds": int(blocked),
                "procesadas": 0,
            }

        since = datetime.now(UTC) - timedelta(days=recheck_days)
        companies = list(db.scalars(select(Company).order_by(Company.ticker)).all())
        checked = self._recently_checked(db, [c.id for c in companies], since)
        pending = [c for c in companies if c.id not in checked][:max_companies]

        stats = {"ok": 0, "sin_datos": 0, "error": 0, "market_cap": 0}
        attended = 0
        rate_limited: UpstreamRateLimited | None = None
        # Dedup de market_cap en UNA consulta por corrida (carga perezosa en
        # el primer cap escribible): antes era un SELECT por compania con
        # cap fresca (hasta max_companies idas a Postgres por ejecucion;
        # medido con harness de conteo: 50 chequeos -> 1 para 50 empresas).
        # Mismos filtros que el count original; cada compania se procesa
        # una vez por corrida, asi que no hace falta actualizar el set.
        cap_facts: set[tuple[int, str]] | None = None
        for company in pending:
            try:
                quote = self._get(QUOTE_URL, company.ticker)
                profile = self._get(PROFILE_URL, company.ticker)
            except UpstreamRateLimited as exc:
                rate_limited = exc
                # La proteccion compartida se publica AL DETECTAR el 429,
                # antes del commit: si el commit falla, el cooldown ya
                # frena a todos los procesos (objecion del auditor 1,
                # contraejemplo medido con commit roto).
                self._pacer.cool_down(exc.retry_after or 60.0)
                break
            attended += 1
            if profile is None and quote is None:
                stats["error"] += 1
                continue  # error de transporte: sin Document, reintento manana
            profile = profile or {}
            fields: list[str] = []
            if profile.get("name"):
                fields.extend(k for k in ("exchange", "currency", "country", "finnhubIndustry") if profile.get(k))

            # Objecion de revision: con exchange placeholder, Finnhub
            # resuelve el ticker pelado al ADR americano (SAN -> NYSE/USD/US)
            # y promover exchange/currency/country/market_cap escribiria la
            # identidad de OTRO instrumento. En ese caso solo se promueve el
            # nombre; el resto queda como candidato declarado en metadata.
            unknown_exchange = company.exchange in _PLACEHOLDER_EXCHANGES
            adr_candidates: dict[str, str] = {}
            changed = False
            # Web oficial del emisor (weburl) -> ir_url: abre la vía de
            # informes oficiales (issuer_reports/IR) a emisores sin SEC
            # (Fairfax FFH.TO, Sagicor SFC.TO). Mismo criterio de identidad
            # que el resto: con bolsa placeholder no se promueve nada de un
            # perfil que puede ser del ADR o de un homónimo; queda declarado
            # en adr_candidates para revisión.
            weburl = (profile.get("weburl") or "").strip() if profile else ""
            ir_url_written = False
            if weburl and not (company.ir_url or "").strip():
                if unknown_exchange:
                    adr_candidates["weburl"] = weburl
                else:
                    promoted = profile_ir_url(profile, company.ticker)
                    if promoted:
                        company.ir_url = promoted
                        ir_url_written = True
                        changed = True
            name = (profile.get("name") or "").strip()
            if name and (
                not (company.name or "").strip()
                or company.name.strip().upper() == (company.ticker or "").upper()
                or "_" in (company.name or "")
            ):
                company.name = name
                changed = True
            exchange = (profile.get("exchange") or "").strip()
            currency = (profile.get("currency") or "").strip()
            country = (profile.get("country") or "").strip().upper()
            industry = (profile.get("finnhubIndustry") or "").strip()
            if unknown_exchange:
                for key, value in (("exchange", exchange), ("currency", currency), ("country", country)):
                    if value:
                        adr_candidates[key] = value
            else:
                # exchange conocido y no placeholder: se respeta tal cual.
                if currency and not (company.currency or "").strip():
                    company.currency = currency
                    changed = True
                if industry and industry.upper() not in {"N/A", "UNKNOWN"} and not (company.industry or "").strip():
                    company.industry = industry
                    changed = True
                    sector = sector_for_industry(industry)
                    if sector and not (company.sector or "").strip():
                        company.sector = sector
                if country and not (company.domicile_country or "").strip():
                    company.domicile_country = country
                    changed = True

            quote_date = _quote_session_date(quote or {}, today)
            cap = _decimal(profile.get("marketCapitalization"))
            cap_written = False
            if unknown_exchange and cap is not None and cap > 0:
                adr_candidates["market_cap_usd_millions"] = str(cap)
            if not unknown_exchange and cap is not None and cap > 0 and quote_date is not None:
                period = quote_date.isoformat()
                if cap_facts is None:
                    cap_facts = set(
                        db.execute(
                            select(FinancialFact.company_id, FinancialFact.period).where(
                                FinancialFact.company_id.in_([c.id for c in pending]),
                                FinancialFact.metric == "market_cap",
                                FinancialFact.source_type == "Finnhub",
                                *tenant_filters(db, FinancialFact),
                            )
                        ).all()
                    )
                if (company.id, period) not in cap_facts:
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
                        "fields": sorted([*fields, *(("ir_url",) if ir_url_written else ())]),
                        "company_updated": changed,
                        "market_cap_written": cap_written,
                        "empty": not profile,
                        # Candidatos NO promovidos por identidad dudosa (ADR):
                        # visibles para revision, nunca aplicados a Company.
                        "adr_candidates": adr_candidates,
                    },
                )
            )
            if changed:
                db.add(company)
            stats["ok" if profile else "sin_datos"] += 1

        db.commit()
        result = {
            "status": "ok",
            "date": today.isoformat(),
            # Empresas atendidas de verdad (con Document o error de
            # transporte contado); con corte por 429 NO incluye las que
            # quedaron sin tocar: esas siguen pendientes para manana.
            "procesadas": attended,
            "pendientes_tras_run": len(companies) - len(checked) - attended,
            "presupuesto": max_companies,
            **stats,
        }
        if rate_limited is not None:
            # El cooldown ya se publico al detectar el 429 (antes del
            # commit); aqui solo se reporta. Ventana del proveedor sin
            # acortar; suelo 60 s si no mando Retry-After util.
            window = rate_limited.retry_after or 60.0
            result.update({
                "status": "partial",
                "reason": "finnhub_429",
                "retry_after_seconds": rate_limited.retry_after,
                "cooldown_seconds": window,
            })
        return result


def backfill_finnhub_profiles(db, **kwargs) -> dict[str, Any]:
    service = FinnhubProfileBackfill()
    try:
        return service.backfill(db, **kwargs)
    finally:
        service.close()
