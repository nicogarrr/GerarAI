"""Orden de fuentes de fundamentales cuando SEC no aporta nada (tesis).

La tesis hace su propia ingesta rapida de SEC companyfacts. Para un emisor
sin CIK (KRKNF, TSXV) o sin hechos us-gaap (BN, 40-F en NIIF) devolvia
"pending" y la tesis salia sin un solo dato, aunque el repo ya tenia una
fuente alternativa revisada (Yahoo, no oficial) para esos tickers.

Orden, de mas a menos fiable, y cada eslabon queda en ``fallback_chain``:

1. SEC companyfacts (oficial) - lo resuelve la ingesta rapida.
2. Hechos oficiales ya guardados (ESEF/CNMV, de refresh/esef): no se
   re-ingieren aqui (esa ingesta hace commit y la tesis corre en un
   SAVEPOINT), solo se cuentan y mandan sobre cualquier otra fuente.
3. Yahoo Finance (no oficial) solo para tickers del mapa REVISADO a mano
   (``yahoo_fundamentals_service.REVIEWED_MAP``): complemento, nunca
   sustituto - no toca un par (metrica, ejercicio) con hecho oficial.

Nunca lanza: un fallo de red o de identidad deja el bloque en "pending" con
el motivo de cada eslabon, y lo escrito se revierte con un savepoint propio.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import redact_secrets
from app.core.tenancy import tenant_filters
from app.models import Company, FinancialFact

logger = logging.getLogger(__name__)

OFFICIAL_STORED_SOURCES = ("ESEF", "CNMV")
YAHOO_LABEL = "Yahoo Finance (fuente no oficial)"


def _stored_official_facts(db: Session, company: Company) -> int:
    return int(
        db.scalar(
            select(func.count())
            .select_from(FinancialFact)
            .where(
                FinancialFact.company_id == company.id,
                FinancialFact.source_type.in_(OFFICIAL_STORED_SOURCES),
                *tenant_filters(db, FinancialFact),
            )
        )
        or 0
    )


def ingest_with_fallback(
    db: Session,
    company: Company,
    sec_block: dict[str, Any],
    *,
    yahoo_refresh: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Bloque de fundamentales de la tesis con el orden de fuentes aplicado."""
    if sec_block.get("status") == "ok":
        return sec_block

    from app.services.yahoo_fundamentals_service import REVIEWED_MAP, refresh_from_yahoo

    chain: list[dict[str, Any]] = [
        {
            "source": sec_block.get("source") or "SEC EDGAR companyfacts",
            "status": sec_block.get("status") or "pending",
            "detail": sec_block.get("detail"),
        }
    ]
    official = _stored_official_facts(db, company)
    chain.append(
        {
            "source": "ESEF/CNMV guardado",
            "status": "ok" if official else "sin_datos",
            "facts": official,
        }
    )

    ticker = company.ticker.upper()
    entry = REVIEWED_MAP.get(ticker)
    yahoo_result: dict[str, Any] | None = None
    if entry is None:
        chain.append({"source": YAHOO_LABEL, "status": "no_aplica", "detail": "ticker sin mapa revisado"})
    else:
        refresh = yahoo_refresh or refresh_from_yahoo
        nested = db.begin_nested()
        try:
            yahoo_result = refresh(db, company, commit=False)
            nested.commit()
            chain.append(
                {
                    "source": YAHOO_LABEL,
                    "status": "ok",
                    "facts": yahoo_result.get("facts_imported", 0),
                    "symbol": yahoo_result.get("symbol"),
                }
            )
        except Exception as exc:  # noqa: BLE001 - la tesis nunca se rompe por una fuente
            if nested.is_active:
                nested.rollback()
            yahoo_result = None
            logger.info("fuente Yahoo no disponible para %s: %s", ticker, type(exc).__name__)
            chain.append({"source": YAHOO_LABEL, "status": "error", "detail": redact_secrets(str(exc))[:200]})

    if yahoo_result is not None:
        return {
            "status": "ok",
            "source": YAHOO_LABEL,
            "official": False,
            "symbol": yahoo_result.get("symbol"),
            "currency": yahoo_result.get("currency"),
            "facts_imported": yahoo_result.get("facts_imported", 0),
            "already_present": yahoo_result.get("facts_skipped_official", 0),
            "metrics": yahoo_result.get("metrics_covered", []),
            "document_id": yahoo_result.get("source_document_id"),
            "source_url": yahoo_result.get("source_url"),
            "retrieved_at": yahoo_result.get("retrieved_at"),
            "verified_against": yahoo_result.get("verified_against", []),
            "fallback_chain": chain,
        }
    if official:
        return {
            "status": "ok",
            "source": "ESEF/CNMV guardado",
            "official": True,
            "facts_imported": 0,
            "already_present": official,
            "fallback_chain": chain,
        }
    return {**sec_block, "fallback_chain": chain}
