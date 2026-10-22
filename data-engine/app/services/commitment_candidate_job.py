"""Candidatos de compromisos desde transcripciones oficiales REGISTRADAS (cartera + watchlist).

Solo crea CANDIDATOS sin revisar (status="candidate"). No aprueba criterios ni emite veredictos.
- Cada (tenant, empresa, URL) tiene un registro de intento (UNIQUE = cerrojo): dos procesos no extraen
  el mismo activo a la vez; hash/fecha/resultado se persisten; el 'cero candidatos' NO se repite a diario.
- Fallo por activo aislado: cualquier excepcion se registra y el lote sigue (nada se pierde por commit previo).
- Orden justo: lo nunca intentado primero, luego lo mas antiguo; reintentos con espera creciente.
- Identidad: una empresa en cartera se identifica por Position.company_id; ambiguedad => se informa.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.entities import CommitmentExtractionAttempt as Attempt
from app.models.entities import Company, Position
from app.services.commitment_coverage import dynamic_universe
from app.services.company_resolver import resolve_company
from app.services.management_credibility_service import ManagementCredibilityService
from app.services.transcript_source_registry import OFFICIAL_TRANSCRIPT_PDF, get_entry

log = logging.getLogger(__name__)
MAX_NEW_ASSETS_PER_RUN = 12
STALE_RUNNING = timedelta(minutes=30)
REFRESH_OK_DAYS = 7
REFRESH_UNSUPPORTED_DAYS = 30
OK_OUTCOMES = {"candidatos_creados", "sin_candidatos_detectados", "sin_cambios_hash"}


def _now() -> datetime:
    return datetime.now(UTC)


def is_due(row: Attempt | None, today: date, now: datetime | None = None) -> bool:
    if row is None:
        return True
    now = now or _now()
    if row.status == "running":
        started = row.started_at
        if started is not None and started.tzinfo is None:
            started = started.replace(tzinfo=UTC)
        return started is None or now - started > STALE_RUNNING
    return row.next_attempt_on is None or today >= row.next_attempt_on


def claim(db: Session, company_id: int, url: str, call_date: date | None, now: datetime | None = None) -> Attempt | None:
    """Toma el activo (None si otro proceso lo tiene en curso). UNIQUE + UPDATE condicional."""
    now = now or _now()
    row = db.scalar(select(Attempt).where(Attempt.company_id == company_id, Attempt.source_url == url))
    if row is None:
        row = Attempt(company_id=company_id, source_url=url, call_date=call_date, status="running", started_at=now)
        db.add(row)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            return None
        return row
    res = db.execute(
        update(Attempt)
        .where(Attempt.id == row.id, or_(Attempt.status != "running", Attempt.started_at < now - STALE_RUNNING))
        .values(status="running", started_at=now)
        .execution_options(synchronize_session=False)
    )
    db.commit()
    if res.rowcount != 1:
        return None
    db.refresh(row)
    return row


def _finish(db: Session, row: Attempt, *, outcome: str, today: date, ok: bool, days: int | None = None, **fields) -> None:
    row.attempts = (row.attempts or 0) + 1
    row.last_attempt_on = today
    row.outcome = outcome
    row.detail = (fields.pop("detail", None) or None)
    for k, v in fields.items():
        setattr(row, k, v)
    if ok:
        row.status, row.consecutive_failures = "done", 0
        row.next_attempt_on = today + timedelta(days=days if days is not None else REFRESH_OK_DAYS)
    else:
        row.status = "failed"
        row.consecutive_failures = (row.consecutive_failures or 0) + 1
        row.next_attempt_on = today + timedelta(days=min(2 ** row.consecutive_failures, 7))
    db.commit()


def process_asset(db: Session, company: Company, ticker: str, asset, *, today: date, fetch: Callable) -> dict:
    """Un activo, aislado: nunca propaga excepcion; deja registro persistido del resultado."""
    from app.services.commitment_extraction_service import extract_with_diagnostics

    item: dict = {"url": asset.url, "created": 0}
    row = claim(db, company.id, asset.url, date.fromisoformat(asset.call_date) if asset.call_date else None)
    if row is None:
        item["outcome"] = "en_curso_otro_proceso"
        return item
    try:
        doc, _meta = fetch(ticker, asset.url, today=today)
        hashes = {"bytes_sha256": getattr(doc, "bytes_sha256", None), "text_sha256": getattr(doc, "text_sha256", None)}
        if row.outcome in OK_OUTCOMES and row.text_sha256 and row.text_sha256 == hashes["text_sha256"]:
            _finish(db, row, outcome="sin_cambios_hash", today=today, ok=True, **hashes)
            item["outcome"] = "sin_cambios_hash"
            return item
        _cands, diag = extract_with_diagnostics(doc.text, call_date=doc.asset.published_on)
        if diag["management_turns"] == 0:
            _finish(db, row, outcome="formato_sin_hablantes_reconocidos", today=today, ok=True,
                    days=REFRESH_UNSUPPORTED_DAYS, management_turns=0, candidates_created=0, **hashes)
            item["outcome"] = "formato_sin_hablantes_reconocidos"
            return item
        new = ManagementCredibilityService().register_extracted_candidates(
            db, company, transcript_text=doc.text, call_date=doc.asset.published_on, source_url=doc.url,
            source_check="registro_oficial_exacto", date_basis="call_date",
        )
        outcome = "candidatos_creados" if new else "sin_candidatos_detectados"
        _finish(db, row, outcome=outcome, today=today, ok=True, management_turns=diag["management_turns"],
                candidates_created=len(new), **hashes)
        item.update(outcome=outcome, created=len(new))
    except Exception as exc:  # noqa: BLE001 - aislamiento por activo; el tipo queda persistido, no se traga
        db.rollback()
        known = isinstance(exc, ValueError)
        outcome = "fallo_fuente_o_limite" if known else f"error_inesperado:{type(exc).__name__}"
        detail = str(exc)[:160] if known else None
        item.update(outcome=outcome, detail=detail)
        if not known:
            log.exception("extraccion de candidatos: error inesperado en %s", ticker)
        try:
            row = db.get(Attempt, row.id)
            _finish(db, row, outcome=outcome, today=today, ok=False, detail=detail)
        except Exception:  # noqa: BLE001
            db.rollback()
            log.exception("no se pudo registrar el intento de %s", ticker)
            item["outcome"] = "error_registro_intento"
    return item


def _held_ids(db: Session) -> dict[str, list[int]]:
    net = (select(Position.company_id).group_by(Position.company_id)
           .having(func.sum(Position.quantity) != 0).subquery())
    out: dict[str, list[int]] = {}
    for cid, t in db.execute(select(Company.id, Company.ticker).join(net, net.c.company_id == Company.id)):
        out.setdefault((t or "").strip().upper(), []).append(cid)
    return out


def _company_for(db: Session, ticker: str, held: dict[str, list[int]]) -> tuple[Company | None, str | None]:
    ids = held.get(ticker)
    if ids:
        if len(ids) > 1:
            return None, "company_identity_ambiguous"
        return db.get(Company, ids[0]), None
    c = resolve_company(db, ticker)
    return (c, None) if c else (None, "empresa_no_resuelta")


def extract_registry_candidates(
    db: Session, *, today: date, fetch: Callable | None = None, max_new_assets: int = MAX_NEW_ASSETS_PER_RUN
) -> dict:
    """{ticker: [{url, outcome, created}]}: resultado explicito por empresa/activo."""
    if fetch is None:
        from app.services.commitment_primary_pipeline import fetch_registered_document_isolated as fetch
    universe, _flags = dynamic_universe(db)
    held = _held_ids(db)
    results: dict[str, list[dict]] = {}
    pending: list[tuple[date, int, str, Company, object]] = []
    for ticker in universe:
        entry = get_entry(ticker)
        if entry is None or entry.status != OFFICIAL_TRANSCRIPT_PDF:
            results[ticker] = [{"outcome": "sin_transcripcion_registrada", "created": 0}]
            continue
        company, problem = _company_for(db, ticker, held)
        if company is None:
            results[ticker] = [{"outcome": problem, "created": 0}]
            continue
        results[ticker] = []
        for asset in entry.assets:
            if asset.kind != "transcript" or not asset.call_date:
                results[ticker].append({"url": asset.url, "outcome": "activo_no_apto", "created": 0})
                continue
            row = db.scalar(select(Attempt).where(Attempt.company_id == company.id, Attempt.source_url == asset.url))
            if not is_due(row, today):
                results[ticker].append({"url": asset.url, "outcome": "no_toca_aun", "created": 0,
                                        "last_outcome": row.outcome if row else None,
                                        "next_attempt_on": row.next_attempt_on.isoformat() if row and row.next_attempt_on else None})
                continue
            pending.append(((row.last_attempt_on if row and row.last_attempt_on else date.min),
                            row.id if row else 0, ticker, company, asset))
    pending.sort(key=lambda x: (x[0], x[1], x[2]))
    for i, (_d, _id, ticker, company, asset) in enumerate(pending):
        if i >= max_new_assets:
            results[ticker].append({"url": asset.url, "outcome": "pendiente_por_limite_de_ejecucion", "created": 0})
            continue
        results[ticker].append(process_asset(db, company, ticker, asset, today=today, fetch=fetch))
    return results
