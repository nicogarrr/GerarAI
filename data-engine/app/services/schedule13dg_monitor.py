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

El watermark y el manejo del fallo fatal viven en ``monitor_common.py``,
compartidos con ``insider_monitor``: este monitor nacio espejo suyo y el
esqueleto ya se habia desalineado a mano; ahora es por construccion.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import Schedule13DGFiling
from app.services import monitor_common, schedule13dg_persistence
from app.services.connectors import form13dg as form13dg_connector
from app.services.insider_monitor import resolve_ciks, watchlist_tickers

logger = logging.getLogger(__name__)

CONNECTOR_NAME = "schedule13dg_monitor"
DEFAULT_DELAY_SECONDS = 0.15
# Un emisor rara vez tiene mas de unos pocos 13D/13G al ano; 40 cubre de sobra
# la cola reciente del submissions JSON sin paginar.
DEFAULT_LOOKBACK = 40
# Presupuesto de descargas por corrida: las peticiones al documento primario
# son las que pesan; el listado (submissions JSON) es una por emisor.
DEFAULT_MAX_NEW_FETCHES = 10


def _normalize_cik(cik: str | int) -> str:
    """CIK sin ceros a la izquierda para comparar (EDGAR lo sirve de ambas)."""
    try:
        return str(int(str(cik).strip()))
    except ValueError:
        return str(cik).strip()


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
    state = monitor_common.connector_state(db, tenant_id, CONNECTOR_NAME)
    state.last_started_at = monitor_common.utcnow()
    db.add(state)
    db.commit()

    stats: dict[str, Any] = {
        "connector": CONNECTOR_NAME,
        "lookback": lookback,
        "tickers_scanned": 0,
        "filings_seen": 0,
        "filings_new": 0,
        "filings_unparsed": 0,
        "filings_rejected": 0,
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
            monitor_common.record_success(db, state, stats)
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
            except Exception:  # noqa: BLE001 - best-effort por emisor
                # Detalle completo solo en el log del servidor: el mensaje de
                # una excepcion no viaja a la API (razon publica constante).
                logger.warning("13D/G: fallo listando filings de %s", ticker, exc_info=True)
                stats["errors"].append(f"{ticker}: form13dg_list_error")
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
                # CIK del emisor SEGUN NUESTRO listado (submissions JSON del
                # ticker): referencia para verificar el filing y respaldo de
                # la columna issuer_cik cuando el documento no lo declara.
                filing["issuer_cik"] = cik
                try:
                    if fetcher is not None:
                        text = fetcher(filing)
                    else:
                        text = form13dg_connector.fetch_filing_document(
                            filing["document_url"], client=client
                        )
                    parsed = form13dg_connector.parse_schedule13dg(text)
                    # Veracidad del emisor: si el documento declara un
                    # issuer_cik distinto del CIK del ticker, el filing no es
                    # de este emisor: no se persiste ni se publica; se
                    # registra y se sigue con el siguiente.
                    parsed_issuer = str(parsed.get("issuer_cik") or "").strip()
                    if parsed_issuer and _normalize_cik(parsed_issuer) != _normalize_cik(cik):
                        stats["filings_rejected"] += 1
                        stats["errors"].append(
                            f"{accession}: issuer_cik {parsed_issuer} no coincide con "
                            f"{ticker} (CIK {cik}); filing descartado"
                        )
                        if delay_seconds > 0:
                            sleeper(delay_seconds)
                        continue
                    persisted = schedule13dg_persistence.persist_filing(
                        db, filing, parsed, raw_text=text, tenant_id=tenant_id
                    )
                    known_accessions.add(accession)
                    stats["filings_new"] += 1 if persisted["filing_created"] else 0
                    stats["filings_unparsed"] += (
                        1 if persisted["filing_created"] and persisted["status"] != "parsed" else 0
                    )
                except Exception:  # noqa: BLE001 - best-effort por filing
                    logger.warning("13D/G: fallo procesando filing %s", accession, exc_info=True)
                    stats["errors"].append(f"{accession}: form13dg_filing_error")
                if delay_seconds > 0:
                    sleeper(delay_seconds)

        if stats["errors"]:
            stats["status"] = "partial" if stats["tickers_scanned"] else "error"
        monitor_common.record_success(db, state, stats)
        return stats
    except Exception as exc:  # noqa: BLE001 - el actor jamas recibe una excepcion
        # Este stats SI se sirve en la API (ownership.scan): solo razon
        # publica constante, nada derivado de la excepcion (el detalle
        # completo queda en el log del servidor).
        logger.exception("13D/G: fallo fatal en scan")
        monitor_common.record_fatal(
            db, tenant_id, CONNECTOR_NAME, stats, exc, public_reason="schedule13dg_scan_fatal"
        )
        return stats
