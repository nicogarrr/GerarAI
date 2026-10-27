"""Monitor programado de la watchlist/cartera contra SC 13D/13G (SEC EDGAR).

Espejo de ``insider_monitor`` (PR-3) para titulares >5%: escanea SOLO los
emisores que el usuario sigue (watch_items + posiciones), nunca el universo
entero. Un 13D/13G es un evento raro (BlackRock entra, un activista supera
el 5%), asi que una corrida diaria acotada basta; coste 0 (submissions JSON
+ presupuesto de descargas por corrida, muy por debajo del limite de la SEC).

Cada corrida:
- resuelve ticker -> CIK (mismos helpers que el monitor insider);
- pide los SC 13D/13G (+/A) recientes de cada emisor;
- salta los accessions ya persistidos y solo descarga/parsea los nuevos;
- lo no parseable queda status="unparsed" con campos NULL (N/D), nunca
  cifras inventadas;
- deja watermark + metricas en connector_states
  (connector="schedule13dg_monitor"). Todo es best-effort por filing: un
  documento roto no detiene la corrida; un fallo global incrementa
  consecutive_errors y deja last_error, nunca lanza al caller del actor.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import ConnectorState, Schedule13DGFiling
from app.services import schedule13dg_persistence
from app.services.connectors import form13dg as form13dg_connector
from app.services.insider_monitor import resolve_ciks, watchlist_tickers

CONNECTOR_NAME = "schedule13dg_monitor"
DEFAULT_DELAY_SECONDS = 0.15
# Un emisor rara vez tiene mas de unos pocos 13D/13G al ano; 40 cubre de sobra
# la cola reciente del submissions JSON sin paginar.
DEFAULT_LOOKBACK = 40
# Presupuesto de descargas por corrida: las peticiones al documento primario
# son las que pesan; el listado (submissions JSON) es una por emisor.
DEFAULT_MAX_NEW_FETCHES = 10


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _connector_state(db: Session, tenant_id: int | None) -> ConnectorState:
    state = db.scalar(
        select(ConnectorState).where(
            ConnectorState.connector == CONNECTOR_NAME,
            ConnectorState.tenant_id.is_(tenant_id) if tenant_id is None
            else ConnectorState.tenant_id == tenant_id,
            ConnectorState.company_id.is_(None),
        )
    )
    if state is None:
        state = ConnectorState(tenant_id=tenant_id, connector=CONNECTOR_NAME)
        db.add(state)
        db.flush()
    return state


def _record_success(db: Session, state: ConnectorState, stats: dict[str, Any]) -> None:
    state.last_success_at = _utcnow()
    state.consecutive_errors = 0
    state.last_error = None
    state.cursor = stats.get("status")
    meta = dict(state.metadata_ or {})
    meta["runs"] = int(meta.get("runs", 0)) + 1
    meta["filings_new_total"] = int(meta.get("filings_new_total", 0)) + stats["filings_new"]
    meta["last_run"] = stats
    state.metadata_ = meta
    db.add(state)
    db.commit()


def scan(
    db: Session,
    *,
    tenant_id: int | None = None,
    tickers: list[str] | None = None,
    lookback: int = DEFAULT_LOOKBACK,
    max_new_fetches: int = DEFAULT_MAX_NEW_FETCHES,
    delay_seconds: float = DEFAULT_DELAY_SECONDS,
    sleeper: Callable[[float], None] = time.sleep,
    client=None,
    fetcher: Callable[[dict], str] | None = None,
) -> dict[str, Any]:
    """Una corrida acotada del monitor. Devuelve stats; nunca lanza."""
    state = _connector_state(db, tenant_id)
    state.last_started_at = _utcnow()
    db.add(state)
    db.commit()

    stats: dict[str, Any] = {
        "connector": CONNECTOR_NAME,
        "lookback": lookback,
        "tickers_scanned": 0,
        "filings_seen": 0,
        "filings_new": 0,
        "filings_unparsed": 0,
        "errors": [],
        "status": "ok",
    }
    try:
        symbols = (
            [t.strip().upper() for t in tickers if t and t.strip()]
            if tickers is not None
            else watchlist_tickers(db, tenant_id)
        )
        if not symbols:
            stats["status"] = "skipped"
            stats["reason"] = "watchlist and portfolio are empty"
            _record_success(db, state, stats)
            return stats
        ciks = resolve_ciks(db, symbols, client=client)
        missing = [t for t in symbols if t not in ciks]
        if missing:
            stats["errors"].append(f"sin CIK SEC: {', '.join(missing)}")

        # Filtro por el tenant EXPLICITO del argumento, no por
        # db.info["tenant_id"] (mismo motivo que insider_monitor.scan).
        known_accessions = {
            row[0]
            for row in db.execute(
                select(Schedule13DGFiling.accession_number).where(
                    Schedule13DGFiling.tenant_id == tenant_id
                )
            ).all()
        }
        budget = max_new_fetches
        for ticker, cik in ciks.items():
            if budget <= 0:
                stats["errors"].append("presupuesto de descargas agotado")
                break
            stats["tickers_scanned"] += 1
            try:
                filings = form13dg_connector.recent_form13dg_filings(
                    cik, limit=lookback, client=client
                )
            except Exception as exc:  # noqa: BLE001 - best-effort por emisor
                stats["errors"].append(f"{ticker}: {type(exc).__name__}")
                continue
            stats["filings_seen"] += len(filings)
            for filing in filings:
                accession = str(filing.get("accession_number") or "")
                if not accession or accession in known_accessions:
                    continue
                if budget <= 0:
                    break
                budget -= 1
                filing["issuer_ticker"] = ticker
                try:
                    if fetcher is not None:
                        text = fetcher(filing)
                    else:
                        text = form13dg_connector.fetch_filing_document(
                            filing["document_url"], client=client
                        )
                    parsed = form13dg_connector.parse_schedule13dg(text)
                    persisted = schedule13dg_persistence.persist_filing(
                        db, filing, parsed, raw_text=text, tenant_id=tenant_id
                    )
                    known_accessions.add(accession)
                    stats["filings_new"] += 1 if persisted["filing_created"] else 0
                    stats["filings_unparsed"] += (
                        1 if persisted["filing_created"] and persisted["status"] != "parsed" else 0
                    )
                except Exception as exc:  # noqa: BLE001 - best-effort por filing
                    stats["errors"].append(f"{accession}: {type(exc).__name__}")
                if delay_seconds > 0:
                    sleeper(delay_seconds)

        if stats["errors"]:
            stats["status"] = "partial" if stats["tickers_scanned"] else "error"
        _record_success(db, state, stats)
        return stats
    except Exception as exc:  # noqa: BLE001 - el actor jamas recibe una excepcion
        stats["status"] = "error"
        stats["errors"].append(f"fatal: {type(exc).__name__}: {exc}")
        state.consecutive_errors = (state.consecutive_errors or 0) + 1
        state.last_error = f"{type(exc).__name__}: {exc}"[:1000]
        meta = dict(state.metadata_ or {})
        meta["runs"] = int(meta.get("runs", 0)) + 1
        meta["last_run"] = stats
        state.metadata_ = meta
        db.add(state)
        db.commit()
        return stats
