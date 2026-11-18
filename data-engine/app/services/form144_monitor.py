"""Monitor programado de la watchlist/cartera contra SEC Form 144.

Espejo de ``schedule13dg_monitor`` (que a su vez nacio espejo de
``insider_monitor``, PR-3) para avisos de venta PROPUESTA (Rule 144):
escanea SOLO los emisores que el usuario sigue (watch_items + posiciones),
nunca el universo entero. Un Form 144 es un aviso previo a la venta (la
venta suele ejecutarse el mismo dia de la presentacion), asi que la
cadencia es horaria durante el dia; coste 0 (submissions JSON del emisor +
presupuesto de descargas por corrida, muy por debajo del limite de la SEC).

Cada corrida:
- resuelve ticker -> CIK (mismos helpers que el monitor insider);
- pide los Form 144 (+144/A) recientes de cada emisor (los 144 figuran en
  las submissions del EMISOR aunque los presente el vendedor o su agente);
- salta los accessions ya persistidos y solo descarga/parsea los nuevos;
- verifica que el issuer_cik declarado en el documento coincide con el CIK
  del ticker (un 144 mal atribuido no se persiste ni se publica);
- lo no parseable queda status="unparsed" con campos NULL (N/D), nunca
  cifras inventadas;
- deja watermark + metricas en connector_states
  (connector="form144_monitor"). Todo es best-effort por filing: un
  documento roto no detiene la corrida; un fallo global incrementa
  consecutive_errors y deja last_error, nunca lanza al caller del actor.

El watermark y el manejo del fallo fatal viven en ``monitor_common.py``,
compartidos con ``insider_monitor`` y ``schedule13dg_monitor``: espejo por
construccion, no a mano.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import Form144Notice
from app.services import form144_persistence, monitor_common
from app.services.connectors import form144 as form144_connector
from app.services.insider_monitor import resolve_ciks, watchlist_tickers

logger = logging.getLogger(__name__)

CONNECTOR_NAME = "form144_monitor"
DEFAULT_DELAY_SECONDS = 0.15
# Un emisor activo puede tener varios 144 al mes (ventas periodicas de
# insiders); 40 cubre de sobra la cola reciente del submissions JSON sin
# paginar.
DEFAULT_LOOKBACK = 40
# Presupuesto de descargas por corrida: las peticiones al documento primario
# son las que pesan; el listado (submissions JSON) es una por emisor.
DEFAULT_MAX_NEW_FETCHES = 10
# Presupuesto de LISTADOS por corrida (auditoría FAV 2026-11-18): sin el,
# 250 emisores sin novedades eran 250 submissions JSON por corrida. Las
# consultas de listado comparten el techo con las descargas (pacer SEC
# compartido): el efectivo es min(max_listings, max_new_fetches).
DEFAULT_MAX_LISTINGS = 25
# Presupuesto de TIEMPO por corrida: la mitad del lease de 600 s del actor,
# para que una red lenta no lo reviente. Al agotarse (como con cualquier
# presupuesto) la corrida se reanuda donde quedo gracias a next_offset.
DEFAULT_MAX_SECONDS = 300.0


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
    max_listings: int | None = None,
    max_seconds: float = DEFAULT_MAX_SECONDS,
    delay_seconds: float = DEFAULT_DELAY_SECONDS,
    sleeper: Callable[[float], None] = time.sleep,
    client=None,
    fetcher: Callable[[dict], str] | None = None,
) -> dict[str, Any]:
    """Una corrida acotada del monitor. Devuelve stats; nunca lanza.

    Reanudacion: el offset del siguiente emisor pendiente viaja en
    stats["next_offset"] y se persiste en connector_states; la corrida
    siguiente continua ahi en vez de repetir la rotacion desde cero.

    Limite declarado de max_seconds: es un presupuesto ENTRE peticiones
    (listados y descargas), no un timeout duro: una descarga ya iniciada
    puede rebasarlo (la siguiente no arranca). El reloj arranca antes de
    resolver los CIKs: ese tiempo tambien cuenta contra el presupuesto.
    """
    stats: dict[str, Any] = {
        "connector": CONNECTOR_NAME,
        "lookback": lookback,
        "tickers_scanned": 0,
        "tickers_listed": 0,
        "filings_seen": 0,
        "filings_new": 0,
        "filings_unparsed": 0,
        "filings_rejected": 0,
        "next_offset": 0,
        "errors": [],
        "status": "ok",
    }
    try:
        # La escritura inicial del estado va DENTRO del try: fuera, un commit
        # roto (sesion caida, BD caida) lanzaba al caller del actor pese al
        # contrato "nunca lanza"; record_fatal ya hace rollback + relectura.
        state = monitor_common.connector_state(db, tenant_id, CONNECTOR_NAME)
        state.last_started_at = monitor_common.utcnow()
        db.add(state)
        db.commit()
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
        # Orden estable: next_offset solo reanuda bien si la rotacion es
        # determinista entre corridas.
        symbols = sorted(set(symbols))
        # El reloj del presupuesto arranca ANTES de resolver CIKs: las
        # peticiones de resolucion tambien consumen el lease del actor.
        deadline = time.monotonic() + max_seconds
        ciks = resolve_ciks(db, symbols, client=client)
        missing = [t for t in symbols if t not in ciks]
        if missing:
            stats["errors"].append(f"sin CIK SEC: {', '.join(missing)}")
        resolved = [(ticker, ciks[ticker]) for ticker in symbols if ticker in ciks]
        stats["tickers_scanned"] = len(resolved)

        # Reanudacion de la rotacion: la corrida anterior dejo en su stats el
        # offset del primer emisor pendiente.
        last_run = ((state.metadata_ or {}).get("last_run") or {})
        previous_offset = int(last_run.get("next_offset") or 0)
        start_at = previous_offset if 0 <= previous_offset < len(resolved) else 0
        listing_budget = min(
            max_listings if max_listings is not None else DEFAULT_MAX_LISTINGS,
            max_new_fetches,
        )

        # Filtro por el tenant EXPLICITO del argumento, no por
        # db.info["tenant_id"] (mismo motivo que insider_monitor.scan).
        known_accessions = {
            row[0]
            for row in db.execute(
                select(Form144Notice.accession_number).where(
                    Form144Notice.tenant_id == tenant_id
                )
            ).all()
        }
        budget = max_new_fetches
        exhausted = False
        index = start_at
        while index < len(resolved):
            if budget <= 0:
                stats["errors"].append("presupuesto de descargas agotado")
                exhausted = True
                break
            if listing_budget <= 0:
                stats["errors"].append("presupuesto de listados agotado")
                exhausted = True
                break
            if time.monotonic() >= deadline:
                stats["errors"].append("presupuesto de tiempo agotado")
                exhausted = True
                break
            ticker, cik = resolved[index]
            listing_budget -= 1
            stats["tickers_listed"] += 1
            try:
                filings = form144_connector.recent_form144_filings(
                    cik, limit=lookback, client=client
                )
            except Exception:  # noqa: BLE001 - best-effort por emisor
                # Detalle completo solo en el log del servidor: el mensaje de
                # una excepcion no viaja a la API (razon publica constante).
                logger.warning("Form 144: fallo listando filings de %s", ticker, exc_info=True)
                stats["errors"].append(f"{ticker}: form144_list_error")
                index += 1
                continue
            stats["filings_seen"] += len(filings)
            completed_ticker = True
            for filing in filings:
                accession = str(filing.get("accession_number") or "")
                if not accession or accession in known_accessions:
                    continue
                if budget <= 0:
                    # No se adelanta el offset: este emisor se rehace en la
                    # proxima corrida para no perder sus filings pendientes.
                    stats["errors"].append("presupuesto de descargas agotado")
                    completed_ticker = False
                    break
                if time.monotonic() >= deadline:
                    # El reloj corre TAMBIEN entre XML del mismo emisor: un
                    # emisor con muchos filings nuevos no puede pasar el lease.
                    stats["errors"].append("presupuesto de tiempo agotado")
                    completed_ticker = False
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
                        text = form144_connector.fetch_filing_xml(
                            filing["document_url"], client=client
                        )
                    parsed = form144_connector.parse_form144_xml(text)
                    # Veracidad del emisor: si el documento declara un
                    # issuer_cik distinto del CIK del ticker, el aviso no es
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
                    persisted = form144_persistence.persist_filing(
                        db, filing, parsed, raw_text=text, tenant_id=tenant_id
                    )
                    known_accessions.add(accession)
                    stats["filings_new"] += 1 if persisted["filing_created"] else 0
                    stats["filings_unparsed"] += (
                        1 if persisted["filing_created"] and persisted["status"] != "parsed" else 0
                    )
                except Exception:  # noqa: BLE001 - best-effort por filing
                    logger.warning("Form 144: fallo procesando filing %s", accession, exc_info=True)
                    stats["errors"].append(f"{accession}: form144_filing_error")
                if delay_seconds > 0:
                    sleeper(delay_seconds)
            if not completed_ticker:
                exhausted = True
                break
            index += 1

        if exhausted:
            stats["next_offset"] = index

        if stats["errors"]:
            stats["status"] = "partial" if stats["tickers_scanned"] else "error"
        monitor_common.record_success(db, state, stats)
        return stats
    except Exception as exc:  # noqa: BLE001 - el actor jamas recibe una excepcion
        # Este stats SI se sirve en la API (connector_states): solo razon
        # publica constante, nada derivado de la excepcion (el detalle
        # completo queda en el log del servidor).
        logger.exception("Form 144: fallo fatal en scan")
        monitor_common.record_fatal(
            db, tenant_id, CONNECTOR_NAME, stats, exc, public_reason="form144_scan_fatal"
        )
        return stats
