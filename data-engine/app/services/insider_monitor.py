"""PR-3: monitor programado de la watchlist/cartera contra SEC Form 4.

Escanea SOLO los emisores que el usuario sigue (watch_items + posiciones),
nunca el universo entero. Cada corrida:

- resuelve ticker -> CIK (Company.cik primero; company_tickers.json si falta);
- pide los Form 4 recientes de cada emisor (submissions API, gratis);
- salta los accessions ya persistidos (#82) y solo descarga/parsea los nuevos,
  con un presupuesto acotado de descargas por corrida y una pausa entre
  peticiones (muy por debajo del limite de 10 rps de la SEC);
- deja watermark + metricas en connector_states (connector="insider_monitor"):
  runs, filings nuevos, errores consecutivos, ultimo error.

Los schedulers (intervalo 15 min, catch-up diario, reconciliacion semanal)
solo varian `lookback` y `max_new_fetches`. Todo es best-effort por filing:
un XML roto no detiene la corrida; un fallo global incrementa
consecutive_errors y deja last_error, nunca lanza al caller del actor.

El watermark en connector_states y el manejo del fallo fatal viven en
``monitor_common.py``, compartidos con ``schedule13dg_monitor`` (que nacio
espejo de este modulo: ahora el espejo es por construccion). El handler
fatal hereda el endurecimiento del 13D/G: rollback antes de regrabar el
estado, por si el fallo vino de la propia sesion.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import (
    Company,
    InsiderFiling,
    InsiderTransaction,
    Position,
    WatchItem,
)
from app.services import insider_persistence, monitor_common
from app.services.connectors import form4 as form4_connector
from app.services.insider_persistence import PARSER_VERSION as INSIDER_PARSER_VERSION
from app.services.insider_service import _cik_for_ticker

CONNECTOR_NAME = "insider_monitor"
DEFAULT_DELAY_SECONDS = 0.15


def watchlist_tickers(db: Session, tenant_id: int | None = None) -> list[str]:
    """Simbolos seguidos: watchlist + companias con posicion en cartera."""
    symbols = {
        row.symbol.upper()
        for row in db.scalars(
            select(WatchItem).where(
                WatchItem.tenant_id.is_(tenant_id) if tenant_id is None
                else WatchItem.tenant_id == tenant_id
            )
        )
        if row.symbol
    }
    company_ids = db.scalars(
        select(Position.company_id).where(
            Position.tenant_id.is_(tenant_id) if tenant_id is None
            else Position.tenant_id == tenant_id
        )
    ).all()
    if company_ids:
        symbols |= {
            c.ticker.upper()
            for c in db.scalars(select(Company).where(Company.id.in_(company_ids)))
            if c.ticker
        }
    return sorted(symbols)


def resolve_ciks(
    db: Session,
    tickers: list[str],
    *,
    client=None,
) -> dict[str, str]:
    """ticker -> CIK, usando Company.cik y rellenando desde la SEC."""
    resolved: dict[str, str] = {}
    for ticker in tickers:
        company = db.scalar(select(Company).where(Company.ticker == ticker))
        cik = (company.cik or "").strip() if company else ""
        if not cik:
            cik = _cik_for_ticker(ticker, client) or ""
            if cik and company is not None:
                company.cik = cik
                db.add(company)
                db.commit()
        if cik:
            resolved[ticker] = cik
    return resolved


def scan(
    db: Session,
    *,
    tenant_id: int | None = None,
    lookback: int = 20,
    max_new_fetches: int = 25,
    delay_seconds: float = DEFAULT_DELAY_SECONDS,
    sleeper: Callable[[float], None] = time.sleep,
    client=None,
    fetcher: Callable[[dict], str] | None = None,
    backfill: bool = False,
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
        "transactions_created": 0,
        "errors": [],
        "status": "ok",
    }
    try:
        tickers = watchlist_tickers(db, tenant_id)
        if not tickers:
            stats["status"] = "skipped"
            stats["reason"] = "watchlist and portfolio are empty"
            monitor_common.record_success(
                db, state, stats, extra_totals={"transactions_created": "transactions_total"}
            )
            return stats
        ciks = resolve_ciks(db, tickers, client=client)
        missing = [t for t in tickers if t not in ciks]
        if missing:
            stats["errors"].append(f"sin CIK SEC: {', '.join(missing)}")

        # Filtro por el tenant EXPLICITO del argumento, no por
        # db.info["tenant_id"]: en workers la sesion nace sin scope (None -> el
        # criteria no se activa, el set salia vacio y se reprocesaban filings
        # ya persistidos) o arrastra el tenant de una corrida anterior (-> se
        # saltaban los de ESTE tenant). Medido en SQLAlchemy 2.1.6: un select()
        # de una sola columna SI dispara el with_loader_criteria de
        # database.py; el filtro tiene que estar aqui y tiene que ser el
        # argumento porque la sesion de worker no garantiza el contexto.
        known_accessions = {
            row[0]
            for row in db.execute(
                select(InsiderFiling.accession_number).where(
                    InsiderFiling.tenant_id == tenant_id
                )
            ).all()
        }
        budget = max_new_fetches
        for ticker, cik in ciks.items():
            if budget <= 0:
                stats["errors"].append("presupuesto de descargas agotado")
                break
            stats["tickers_scanned"] += 1
            filings = form4_connector.recent_form4_filings(cik, limit=lookback, client=client)
            stats["filings_seen"] += len(filings)
            for filing in filings:
                accession = str(filing.get("accession_number") or "")
                if not accession or accession in known_accessions:
                    continue
                if budget <= 0:
                    break
                budget -= 1
                try:
                    if fetcher is not None:
                        xml_text = fetcher(filing)
                    else:
                        xml_text = form4_connector.fetch_filing_xml(
                            filing["document_url"], client=client
                        )
                    parsed = form4_connector.parse_form4_xml(xml_text)
                    persisted = insider_persistence.persist_filing(
                        db, filing, parsed, xml_text=xml_text, tenant_id=tenant_id
                    )
                    known_accessions.add(accession)
                    stats["filings_new"] += 1 if persisted["filing_created"] else 0
                    stats["transactions_created"] += persisted["transactions_created"]
                except Exception as exc:  # noqa: BLE001 - best-effort por filing
                    stats["errors"].append(f"{accession}: {type(exc).__name__}")
                if delay_seconds > 0:
                    sleeper(delay_seconds)

        if backfill and budget > 0:
            stats["backfill"] = backfill_empty_filings(
                db,
                tenant_id=tenant_id,
                max_fetches=budget,
                delay_seconds=delay_seconds,
                sleeper=sleeper,
                client=client,
                fetcher=fetcher,
            )
            budget = max(0, budget - stats["backfill"].get("examined", 0))
        if backfill and budget > 0:
            # Planes 10b5-1: re-lectura acotada de XML ya persistidos para
            # marcar rule_10b5_1 (columna anadida despues del dato).
            stats["backfill_10b5_1"] = backfill_rule_10b5_1(
                db,
                tenant_id=tenant_id,
                max_fetches=budget,
                delay_seconds=delay_seconds,
                sleeper=sleeper,
                client=client,
                fetcher=fetcher,
            )
        if stats["errors"]:
            stats["status"] = "partial" if stats["tickers_scanned"] else "error"
        monitor_common.record_success(
            db, state, stats, extra_totals={"transactions_created": "transactions_total"}
        )
        return stats
    except Exception as exc:  # noqa: BLE001 - el actor jamas recibe una excepcion
        # Sin public_reason: este stats NO se sirve en ninguna ruta, asi que
        # conserva el detalle redactado (ver monitor_common.record_fatal y
        # tests/test_monitor_last_error_redaction.py).
        monitor_common.record_fatal(db, tenant_id, CONNECTOR_NAME, stats, exc)
        return stats


def backfill_empty_filings(
    db: Session,
    *,
    tenant_id: int | None = None,
    max_fetches: int = 25,
    delay_seconds: float = DEFAULT_DELAY_SECONDS,
    sleeper: Callable[[float], None] = time.sleep,
    client=None,
    fetcher: Callable[[dict], str] | None = None,
) -> dict[str, Any]:
    """Rellena filings persistidos que no tienen ninguna transaccion.

    Un filing sin filas es un filing sin insider/cargo/importe. Se vuelve a
    leer su XML y se persisten las transacciones (idempotente por fingerprint).
    Si el XML se lee bien y de verdad no trae operaciones, el filing queda
    ``status="empty"`` y no se reintenta; un fallo de red no lo marca.
    """
    stats: dict[str, Any] = {"examined": 0, "filled": 0, "empty": 0, "failed": 0}
    has_tx = select(InsiderTransaction.filing_id).where(
        InsiderTransaction.filing_id == InsiderFiling.id,
        InsiderTransaction.tenant_id.is_(tenant_id)
        if tenant_id is None
        else InsiderTransaction.tenant_id == tenant_id,
    )
    stmt = (
        select(InsiderFiling)
        .where(
            InsiderFiling.tenant_id.is_(tenant_id) if tenant_id is None
            else InsiderFiling.tenant_id == tenant_id,
            InsiderFiling.status != "empty",
            ~has_tx.exists(),
        )
        .order_by(InsiderFiling.filing_date.desc(), InsiderFiling.id.desc())
        .limit(max_fetches)
    )
    for record in list(db.scalars(stmt)):
        stats["examined"] += 1
        filing = {
            "accession_number": record.accession_number,
            "form": record.form,
            "filing_date": record.filing_date,
            "report_date": record.report_date,
            "document_url": record.source_url,
            "index_url": record.index_url,
        }
        try:
            if fetcher is not None:
                xml_text = fetcher(filing)
            else:
                xml_text = form4_connector.fetch_filing_xml(
                    str(record.source_url), client=client
                )
            parsed = form4_connector.parse_form4_xml(xml_text)
            result = insider_persistence.persist_filing(
                db, filing, parsed, xml_text=xml_text, tenant_id=tenant_id
            )
            if result["transactions_created"]:
                stats["filled"] += 1
            elif not parsed.get("transactions"):
                record.status = "empty"
                db.add(record)
                db.commit()
                stats["empty"] += 1
        except Exception:  # noqa: BLE001 - best-effort por filing
            db.rollback()
            stats["failed"] += 1
        if delay_seconds > 0:
            sleeper(delay_seconds)
    return stats


def backfill_rule_10b5_1(
    db: Session,
    *,
    tenant_id: int | None = None,
    max_fetches: int = 25,
    delay_seconds: float = DEFAULT_DELAY_SECONDS,
    sleeper: Callable[[float], None] = time.sleep,
    client=None,
    fetcher: Callable[[dict], str] | None = None,
) -> dict[str, Any]:
    """Marca rule_10b5_1 en transacciones ya persistidas re-leyendo su XML.

    La columna llego despues del dato: hace falta re-descargar cada Form 4
    (el XML crudo no se guarda, solo su sha). Misma disciplina que el resto
    del monitor: presupuesto de descargas por corrida, pausa entre
    peticiones (por debajo del limite de la SEC) y best-effort por filing —
    un fallo de red deja el filing para la siguiente corrida, nunca lo
    marca. No machaca: solo actualiza el flag de filas cuyo fingerprint
    coincide con la re-lectura y sube el parser_version del filing, que es
    lo que lo saca de la cola.
    """
    stats: dict[str, Any] = {"examined": 0, "updated": 0, "flagged": 0, "failed": 0}
    has_tx = select(InsiderTransaction.id).where(
        InsiderTransaction.filing_id == InsiderFiling.id,
        InsiderTransaction.tenant_id.is_(tenant_id)
        if tenant_id is None
        else InsiderTransaction.tenant_id == tenant_id,
    )
    stmt = (
        select(InsiderFiling)
        .where(
            InsiderFiling.tenant_id.is_(tenant_id) if tenant_id is None
            else InsiderFiling.tenant_id == tenant_id,
            InsiderFiling.parser_version != INSIDER_PARSER_VERSION,
            has_tx.exists(),
        )
        .order_by(InsiderFiling.filing_date.desc(), InsiderFiling.id.desc())
        .limit(max_fetches)
    )
    for record in list(db.scalars(stmt)):
        stats["examined"] += 1
        filing = {
            "accession_number": record.accession_number,
            "form": record.form,
            "filing_date": record.filing_date,
            "report_date": record.report_date,
            "document_url": record.source_url,
            "index_url": record.index_url,
        }
        try:
            if fetcher is not None:
                xml_text = fetcher(filing)
            else:
                xml_text = form4_connector.fetch_filing_xml(
                    str(record.source_url), client=client
                )
            parsed = form4_connector.parse_form4_xml(xml_text)
            by_fingerprint = {
                insider_persistence.transaction_fingerprint(
                    record.accession_number, row_index, tx
                ): tx
                for row_index, tx in enumerate(parsed.get("transactions", []))
            }
            rows = list(
                db.scalars(
                    select(InsiderTransaction).where(
                        InsiderTransaction.filing_id == record.id
                    )
                )
            )
            changed = False
            for row in rows:
                tx = by_fingerprint.get(row.fingerprint)
                if tx is None:
                    continue
                flag = bool(tx.get("rule_10b5_1"))
                if row.rule_10b5_1 != flag:
                    row.rule_10b5_1 = flag
                    db.add(row)
                    changed = True
                    if flag:
                        stats["flagged"] += 1
            record.parser_version = INSIDER_PARSER_VERSION
            db.add(record)
            db.commit()
            if changed:
                stats["updated"] += 1
        except Exception:  # noqa: BLE001 - best-effort por filing
            db.rollback()
            stats["failed"] += 1
        if delay_seconds > 0:
            sleeper(delay_seconds)
    return stats

