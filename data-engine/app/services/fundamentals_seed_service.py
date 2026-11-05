"""Siembra automatica de fundamentales para cartera+watchlist (por tenant).

Hallazgo del tester (19 oct 2026): los FinancialFact son filas POR TENANT
(TenantOwnedMixin, filtro automatico en las SELECT); un tenant nuevo veia
«Todavia no hay hechos financieros persistidos» en UNH/KO hasta pulsar
«Refrescar SEC». Con este carril, anadir a cartera o watchlist encola la
ingesta en el contexto del propio tenant: mismos proveedores y contratos
de veracidad que el boton manual (SEC companyfacts / snapshot ESEF local),
sin que el usuario tenga que pulsar nada.

La via se elige con la misma señal estable que la ficha: mercado declarado
o sufijo de ticker (espejo de ESEF_EXCHANGE_PATTERNS/ESEF_MARKET_SUFFIXES
del frontend); sin esa señal manda el CIK (SEC) y, como ultimo recurso, la
existencia de snapshot ESEF local. Un fallo del proveedor queda contado en
el resultado del actor: nunca se inventa un hecho.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import redact_secrets
from app.core.tenancy import tenant_filters
from app.models.entities import Company, FinancialFact
from app.services.connectors import esef as esef_connector

logger = logging.getLogger(__name__)

# Espejo backend de ESEF_MARKET_SUFFIXES / ESEF_EXCHANGE_PATTERNS de
# app/(root)/research/[ticker]/page.tsx (mantener alineados).
ESEF_TICKER_SUFFIXES = {
    "MC", "PA", "AS", "BR", "LS", "DE", "F", "MI", "VI", "HE", "ST", "CO", "OL",
}
ESEF_EXCHANGE_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"BME|BOLSA DE MADRID",
        r"EURONEXT",  # cubre la nomenclatura historica «NYSE EURONEXT - ...»
        r"XETRA|FRANKFURT|DEUTSCHE B.O.RSE",
        r"BORSA ITALIANA|MILAN",
        r"WIENER|VIENNA",
        r"HELSINKI",
        r"STOCKHOLM",
        r"COPENHAGEN|COPENHAGUE",
        r"OSLO",
        r"LISBON|LISBOA",
        r"ATHENS|ATENAS",
        r"DUBLIN",
        r"WARSAW|VARSOVIA",
        r"PRAGUE|PRAGA",
        r"BUDAPEST",
        r"BRATISLAVA",
        r"LJUBLJANA",
        r"LUXEMBOURG",
    )
)


def fundamentals_lane(company: Company) -> str:
    """Via de fundamentales: 'esef' o 'sec', decidida con datos declarados."""
    ticker = (company.ticker or "").upper()
    exchange = (company.exchange or "").strip()
    suffix = ticker.rsplit(".", 1)[-1] if "." in ticker else ""
    if suffix in ESEF_TICKER_SUFFIXES or any(p.search(exchange) for p in ESEF_EXCHANGE_PATTERNS):
        return "esef"
    if company.cik:
        return "sec"
    # Sin señal de mercado ni CIK (p.ej. OTC de un emisor europeo): si hay
    # snapshot ESEF local revisado para el ticker, esa es la fuente primaria.
    if esef_connector.read_esef_snapshot(ticker) is not None:
        return "esef"
    return "sec"


def tenant_has_facts(db: Session, company: Company) -> bool:
    """La sesion ya filtra por tenant: cuenta solo los hechos de ESTE tenant."""
    return bool(
        db.scalar(
            select(func.count(FinancialFact.id)).where(
                FinancialFact.company_id == company.id,
                *tenant_filters(db, FinancialFact),
            )
        )
    )


def seed_company_fundamentals(db: Session, company: Company) -> dict[str, Any]:
    """Ingiere fundamentales del proveedor primario si el tenant no tiene.

    Idempotente: con hechos presentes no hace nada. Devuelve un dict con el
    resultado; las excepciones del proveedor las gestiona el actor caller.
    """
    from app.services.async_bridge import run_from_any_context
    from app.services.financial_ingestion_service import FinancialIngestionService
    from app.services.fundamentals_fallback import fill_bridge_gaps

    if tenant_has_facts(db, company):
        gaps = fill_bridge_gaps(db, company)
        db.commit()
        return {"status": "ya_tiene_hechos", "ticker": company.ticker, "bridge_gaps": gaps}
    lane = fundamentals_lane(company)
    service = FinancialIngestionService()
    # Cascada (nov 2026, BFIT.AS con 0 hechos): la via primaria segun el
    # mercado y, si no deja hechos, la otra primaria; al final los estados
    # completos de Yahoo como UNICA fuente no oficial (etiquetados). Cada
    # intento queda en ``intentos`` con su motivo; nunca se inventa un hecho.
    order = ["esef", "sec"] if lane == "esef" else ["sec", "esef"]
    attempts: list[dict[str, Any]] = []
    result: dict[str, Any] = {}
    via_ok: str | None = None
    for via in order:
        if via == "sec" and not company.cik:
            attempts.append({"via": "sec", "status": "no_aplica", "detail": "sin CIK"})
            continue
        try:
            coro = (
                service.refresh_from_esef(db=db, company=company)
                if via == "esef"
                else service.refresh_from_sec(db=db, company=company)
            )
            result = run_from_any_context(coro)
            db.commit()
        except Exception as exc:  # noqa: BLE001 - se prueba la siguiente fuente
            db.rollback()
            attempts.append({"via": via, "status": "error", "detail": redact_secrets(str(exc))[:200]})
            continue
        attempts.append({"via": via, "status": "ok", "facts_imported": result.get("facts_imported")})
        if (result.get("facts_imported") or 0) > 0 or tenant_has_facts(db, company):
            via_ok = via
            break
    from app.services.fundamentals_fallback import _non_sec_fallback_enabled

    if via_ok is None and _non_sec_fallback_enabled():
        from app.services.yahoo_fundamentals_service import refresh_full_from_yahoo

        try:
            result = refresh_full_from_yahoo(db, company, commit=True)
            via_ok = "yahoo_no_oficial"
            attempts.append({
                "via": via_ok,
                "status": "ok",
                "facts_imported": result.get("facts_imported"),
                "note": result.get("note"),
            })
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            attempts.append({"via": "yahoo_no_oficial", "status": "error", "detail": redact_secrets(str(exc))[:200]})
            logger.info("sin fundamentales para %s: %s", company.ticker, attempts)
    gaps = fill_bridge_gaps(db, company)
    db.commit()
    return {
        "status": "sembrado" if via_ok else "sin_fuente",
        "ticker": company.ticker,
        "via": via_ok or lane,
        "facts_imported": result.get("facts_imported") if via_ok else 0,
        "intentos": attempts,
        "bridge_gaps": gaps,
    }


def enqueue_fundamentals_seed(db: Session, ticker: str) -> bool:
    """Encola la siembra para el tenant de la sesion. Nunca rompe al caller:
    sin contexto de tenant o sin broker devuelve False y el alta continua."""
    tenant_id = db.info.get("tenant_id")
    user_id = db.info.get("user_id")
    if tenant_id is None or not user_id:
        return False
    try:
        from app.workers.dramatiq_app import seed_company_fundamentals

        seed_company_fundamentals.send(tenant_id, user_id, ticker.strip().upper())
        return True
    except Exception:  # noqa: BLE001 - el alta de cartera/watchlist manda
        logger.exception("No se pudo encolar la siembra de fundamentales de %s", ticker)
        return False
