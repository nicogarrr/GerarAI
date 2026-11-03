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
3. Yahoo Finance (no oficial) para tickers del mapa REVISADO a mano
   (``yahoo_fundamentals_service.REVIEWED_MAP``): complemento, nunca
   sustituto - no toca un par (metrica, ejercicio) con hecho oficial.
4. Emisor sin CIK y sin mapa revisado (UE/UK/resto, nov 2026): ESEF en
   vivo por LEI (filings.xbrl.org, oficial) y, si no hay, los estados
   completos de Yahoo como UNICA fuente, etiquetados «una sola fuente, no
   oficial» (``_non_sec_fallback``).

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
        if not company.cik and not official and _non_sec_fallback_enabled():
            return _non_sec_fallback(db, company, sec_block, chain)
        # Emisor SEC con un fallo puntual (no se rellena con una fuente no
        # oficial) o con oficial ya guardado: como antes.
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


ESEF_LIVE_LABEL = "ESEF (filings.xbrl.org, informe anual oficial)"
YAHOO_FULL_LABEL = "Yahoo Finance (una sola fuente, no oficial)"


def _non_sec_fallback_enabled() -> bool:
    from app.services.esef_live import live_lookup_enabled

    return live_lookup_enabled()


def _non_sec_fallback(
    db: Session,
    company: Company,
    sec_block: dict[str, Any],
    chain: list[dict[str, Any]],
    *,
    esef_refresh: Callable[..., Any] | None = None,
    yahoo_full: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Emisor sin SEC ni mapa Yahoo revisado (BFIT.AS, nov 2026).

    Solo se llama sin hechos oficiales guardados.
    1. ESEF en vivo por LEI (oficial).
    2. Si sigue sin datos: estados completos de Yahoo como UNICA fuente,
       etiquetados «una sola fuente, no oficial».
    Cada eslabon en su SAVEPOINT; nunca lanza.
    """
    official = 0
    from app.services.async_bridge import run_from_any_context
    from app.services.financial_ingestion_service import FinancialIngestionService

    nested = db.begin_nested()
    try:
        if esef_refresh is not None:
            result = esef_refresh(db, company)
        else:
            result = run_from_any_context(
                FinancialIngestionService().refresh_from_esef(db=db, company=company, commit=False)
            )
        nested.commit()
        official = _stored_official_facts(db, company)
        chain.append({
            "source": ESEF_LIVE_LABEL,
            "status": "ok" if official else "sin_datos",
            "facts": result.get("facts_imported", 0),
            "lei": result.get("lei"),
            "period_end": result.get("period_end"),
        })
        if official:
            return {
                "status": "ok",
                "source": ESEF_LIVE_LABEL,
                "official": True,
                "facts_imported": result.get("facts_imported", 0),
                "lei": result.get("lei"),
                "period_end": result.get("period_end"),
                "fallback_chain": chain,
            }
    except Exception as exc:  # noqa: BLE001 - la tesis nunca se rompe por una fuente
        if nested.is_active:
            nested.rollback()
        chain.append({"source": ESEF_LIVE_LABEL, "status": "error", "detail": redact_secrets(str(exc))[:200]})

    from app.services.yahoo_fundamentals_service import SINGLE_SOURCE_NOTE, refresh_full_from_yahoo

    refresh = yahoo_full or refresh_full_from_yahoo
    nested = db.begin_nested()
    try:
        yahoo_result = refresh(db, company, commit=False)
        nested.commit()
    except Exception as exc:  # noqa: BLE001
        if nested.is_active:
            nested.rollback()
        chain.append({"source": YAHOO_FULL_LABEL, "status": "error", "detail": redact_secrets(str(exc))[:200]})
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
    chain.append({
        "source": YAHOO_FULL_LABEL,
        "status": "ok",
        "facts": yahoo_result.get("facts_imported", 0),
        "symbol": yahoo_result.get("symbol"),
    })
    return {
        "status": "ok",
        "source": YAHOO_FULL_LABEL,
        "official": False,
        "single_source": True,
        "note": SINGLE_SOURCE_NOTE,
        "symbol": yahoo_result.get("symbol"),
        "currency": yahoo_result.get("currency"),
        "facts_imported": yahoo_result.get("facts_imported", 0),
        "already_present": yahoo_result.get("facts_skipped_official", 0) + official,
        "metrics": yahoo_result.get("metrics_covered", []),
        "document_id": yahoo_result.get("source_document_id"),
        "source_url": yahoo_result.get("source_url"),
        "retrieved_at": yahoo_result.get("retrieved_at"),
        "fallback_chain": chain,
    }


# Piezas del puente de valoracion que el modo huecos de Yahoo puede aportar.
BRIDGE_GAP_INPUTS = frozenset({"net_debt", "shares_diluted"})


def fill_bridge_gaps(
    db: Session,
    company: Company,
    *,
    refresh: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Trae deuda, caja, deuda neta y acciones de Yahoo (no oficial) en CADA tesis.

    Owner 3-nov-2026 («siempre miramos todas las fuentes, no solo ahora»): se
    trae aunque al snapshot no le falte nada, para que el cruce de fuentes del
    snapshot confirme o marque discrepancias; si falta deuda neta o acciones,
    ademas cierra el hueco (etiquetado). Corre en su propio SAVEPOINT y nunca lanza (la tesis no se rompe por una
    fuente). Devuelve que faltaba, que se intento y si el hueco se cerro.
    """
    from app.valuation.financial_snapshot import FinancialSnapshotBuilder

    if refresh is None:
        from app.core.config import get_settings

        if not get_settings().yahoo_bridge_gaps_enabled:
            return {"status": "desactivado"}
    try:
        before = set(FinancialSnapshotBuilder().build(db, company).missing_inputs)
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "detail": type(exc).__name__}
    wanted = sorted(before & BRIDGE_GAP_INPUTS)
    mode = "huecos" if wanted else "cruce"
    from app.services.yahoo_fundamentals_service import refresh_gaps_from_yahoo

    fn = refresh or refresh_gaps_from_yahoo
    nested = db.begin_nested()
    try:
        result = fn(db, company, commit=False)
        nested.commit()
    except Exception as exc:  # noqa: BLE001 - fuente opcional
        if nested.is_active:
            nested.rollback()
        logger.info("huecos Yahoo no disponibles para %s: %s", company.ticker, type(exc).__name__)
        return {
            "status": "error",
            "source": YAHOO_LABEL,
            "wanted": wanted,
            "detail": redact_secrets(str(exc))[:200],
        }
    try:
        after = set(FinancialSnapshotBuilder().build(db, company).missing_inputs)
    except Exception:  # noqa: BLE001
        after = before
    return {
        "status": "ok",
        "mode": mode,
        "source": YAHOO_LABEL,
        "single_source": True,
        "wanted": wanted,
        "closed": sorted(set(wanted) - after),
        "still_missing": sorted(set(wanted) & after),
        "facts_imported": result.get("facts_imported", 0),
        "symbol": result.get("symbol"),
        "document_id": result.get("source_document_id"),
    }
