"""Inventory of persisted coverage, not a claim that upstream providers are live."""
from __future__ import annotations

import threading
import time
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session

from app.models import (
    Company,
    ConnectorState,
    Document,
    FinancialFact,
    MarketPrice,
    NewsEvent,
    ProPickCandidate,
    ProPickRun,
)


def _eligible_total(db: Session, label: str, source_name: str | None) -> int | None:
    """Denominador de elegibilidad para fuentes estructuralmente acotadas.

    ESEF solo cubre emisores revisados contra el registro CNMV (tabla
    REVIEWED, hoy ~110): medirlo contra las 2.132 empresas del universo
    reportaba un 4,6 % que parecia fuente rota cuando la cobertura real
    sobre elegibles era ~89 %. Resto de fuentes: sin cota declarada, el
    denominador sigue siendo el universo."""
    if label == "Fundamentales" and source_name == "ESEF":
        from app.services.cnmv_mapping import REVIEWED_ISSUERS
        from app.services.esef_issuer_mapping import (
            REVIEWED_ISSUERS_IE,
            REVIEWED_ISSUERS_NL,
        )

        tickers = {issuer.ticker.upper() for issuer in REVIEWED_ISSUERS}
        tickers |= {f"{t}.MC" for t in tickers}
        # Emisores ESEF reviewed fuera de ES (NL/IE): tambien son elegibles
        # de esta fuente; sin ellos el ratio sobre elegibles podia pasar de 100.
        tickers |= {i.ticker.upper() for i in REVIEWED_ISSUERS_NL + REVIEWED_ISSUERS_IE}
        return db.scalar(
            select(func.count(Company.id)).where(func.upper(Company.ticker).in_(tickers))
        ) or 0
    return None


_CACHE: dict[int, tuple[float, dict]] = {}
_LOCK = threading.Lock()
# El inventario agrupa por fuente sobre tablas grandes (precios, hechos,
# noticias): la lectura en frio tarda >10 s en prod (medido 16,4 s). Con TTL
# 60 s ese coste se repetia cada minuto por worker; 10 min de frescura es
# suficiente para un panel de salud de fuentes.
_CACHE_TTL_SECONDS = 600.0
LAYERS = (
    ("Fundamentales", FinancialFact, "source_type", 90),
    ("Documentos", Document, "source_type", 30),
    ("Precios diarios", MarketPrice, "source", 4),
    ("Noticias", NewsEvent, "source", 7),
)


# Nombre del connector con el que sec_fundamentals_backfill persiste sus
# marcas de intento (una por compania). Literal a proposito: ese servicio
# importa utc() de este modulo, y una importacion cruzada seria circular.
SEC_BACKFILL_CONNECTOR = "sec-fundamentals-backfill"
# refresh_rss_feeds guarda una ConnectorState por feed (cursor de #3029): se
# agregan en una linea, igual que el backfill SEC.
RSS_FEED_CONNECTOR = "rss"



# Fuentes excluidas del panel (no son ingesta real). Lista fija de codigo:
# se interpola en el SQL como literal seguro, nunca viene del usuario.
_NOT_SOURCES_SQL = "('seed', 'manual', 'test', 'dummy', 'placeholder')"


def _coverage_groups(db: Session, *, table: str, source_col: str,
                     tenant: int, reported: bool = False,
                     prices: bool = False) -> list:
    """Count source/company pairs with bounded probes on existing indexes.

    PG17 can discard a redundant IS NOT NULL on a NOT NULL integer column
    before matching a partial index. An equivalent full INTEGER domain bound
    keeps the predicate provable without excluding negative or zero IDs.
    Table and column identifiers come only from the fixed LAYERS tuple.
    """
    filters = (
        f"{source_col} NOT IN {_NOT_SOURCES_SQL} AND company_id IS NOT NULL"
        " AND company_id >= -2147483648"
    )
    if not prices:
        filters += " AND tenant_id = :tenant"
    if reported:
        filters += " AND is_reported"
    if prices:
        filters += " AND close > 0"
    # nosemgrep: gerarai-tenant-raw-sql -- every tenant-owned probe includes tenant_id=:tenant; global prices are intentionally shared, as before.
    statement = sa.text(f"""
      WITH RECURSIVE sources(src) AS (
        SELECT * FROM (SELECT {source_col} FROM {table} WHERE {filters}
          ORDER BY {source_col} LIMIT 1)
        UNION ALL
        SELECT (SELECT {source_col} FROM {table} WHERE {filters}
          AND {source_col} > sources.src ORDER BY {source_col} LIMIT 1)
        FROM sources WHERE src IS NOT NULL
      ), pairs(src, cid) AS (
        SELECT src, (SELECT company_id FROM {table} WHERE {filters}
          AND {source_col} = sources.src ORDER BY company_id LIMIT 1)
        FROM sources WHERE src IS NOT NULL
        UNION ALL
        SELECT src, (SELECT company_id FROM {table} WHERE {filters}
          AND {source_col} = pairs.src AND company_id > pairs.cid
          ORDER BY company_id LIMIT 1)
        FROM pairs WHERE cid IS NOT NULL
      ), counts AS (
        SELECT src, count(*) AS covered FROM pairs WHERE cid IS NOT NULL GROUP BY src
      )
      SELECT src, covered, (SELECT updated_at FROM {table} WHERE {filters}
        AND {source_col} = counts.src AND updated_at IS NOT NULL
        ORDER BY updated_at DESC LIMIT 1) AS stamp FROM counts ORDER BY src
    """).columns(src=sa.String(), covered=sa.Integer(), stamp=sa.DateTime(timezone=True))
    return list(db.execute(statement, {"tenant": tenant}).all())

def utc(value: datetime | None) -> datetime | None:
    return value.replace(tzinfo=UTC) if value and value.tzinfo is None else value


def inventory(db: Session, *, now: datetime | None = None) -> dict:
    tenant = db.info.get("tenant_id")
    if tenant is None:
        raise ValueError("Tenant context required")
    now = now or datetime.now(UTC)
    total = db.scalar(select(func.count(Company.id))) or 0
    rows = []
    for label, model, source_field, max_age in LAYERS:
        source = getattr(model, source_field)
        try:
            if db.get_bind().dialect.name == "postgresql":
                groups = _coverage_groups(
                    db, table=model.__tablename__, source_col=source_field,
                    tenant=tenant, reported=model is FinancialFact,
                    prices=model is MarketPrice,
                )
            else:
                statement = select(source, func.count(distinct(model.company_id)),
                                   func.max(model.updated_at)).where(
                    source.not_in(["seed", "manual", "test", "dummy", "placeholder"]),
                    model.company_id.is_not(None),
                ).group_by(source)
                if model is not MarketPrice:
                    statement = statement.where(model.tenant_id == tenant)
                if model is FinancialFact:
                    statement = statement.where(model.is_reported.is_(True))
                if model is MarketPrice:
                    statement = statement.where(model.close > 0)
                groups = db.execute(statement).all()
            for name, covered, stamp in groups:
                stamp = utc(stamp)
                status = "stale" if stamp and now - stamp > timedelta(days=max_age) else "available"
                eligible = _eligible_total(db, label, name)
                rows.append({"layer": label, "source": name, "covered": covered,
                             "total": total, "coverage_pct": round(100 * covered / total, 2) if total else None,
                             "eligible": eligible,
                             "coverage_pct_eligible": (
                                 round(100 * covered / eligible, 2) if eligible else None
                             ),
                             "last_update": stamp.isoformat() if stamp else None,
                             "status": status, "max_age_days": max_age,
                             "reason": "Actualización almacenada fuera del límite de frescura del panel." if status == "stale" else None})
            if not groups:
                rows.append({"layer": label, "source": None, "covered": 0, "total": total,
                             "coverage_pct": 0.0 if total else None, "last_update": None,
                             "status": "empty", "max_age_days": max_age,
                             "reason": "No hay registros de fuentes externas para esta capa."})
        except Exception:  # noqa: BLE001 - no false zeros on failed reads
            db.rollback()
            rows.append({"layer": label, "source": None, "covered": None, "total": total,
                         "coverage_pct": None, "last_update": None, "status": "error",
                         "max_age_days": max_age, "reason": "No se pudo leer esta capa de la base de datos."})
    try:
        states = db.scalars(select(ConnectorState).where(ConnectorState.tenant_id == tenant)).all()
        connectors = [{"source": state.connector,
                       "last_success": utc(state.last_success_at).isoformat() if state.last_success_at else None,
                       "last_attempt": utc(state.last_started_at).isoformat() if state.last_started_at else None,
                       "status": "degraded" if state.consecutive_errors else "observed" if state.last_success_at else "empty",
                       "errors": state.consecutive_errors} for state in states
                      if state.connector not in (SEC_BACKFILL_CONNECTOR, RSS_FEED_CONNECTOR)]
        rss = [state for state in states if state.connector == RSS_FEED_CONNECTOR]
        if rss:
            ok = sum(1 for s in rss if s.last_success_at and not s.consecutive_errors)
            failing = sum(1 for s in rss if s.consecutive_errors)
            attempts = [stamp for s in rss if (stamp := utc(s.last_started_at)) is not None]
            successes = [stamp for s in rss if (stamp := utc(s.last_success_at)) is not None]
            last_attempt = max(attempts, default=None)
            last_success = max(successes, default=None)
            connectors.append({
                "source": f"{RSS_FEED_CONNECTOR} · {len(rss)} feeds (ok {ok} · error {failing})",
                "last_success": last_success.isoformat() if last_success else None,
                "last_attempt": last_attempt.isoformat() if last_attempt else None,
                "status": "degraded" if failing else "observed" if ok else "empty",
                "errors": failing})
        backfill = [state for state in states if state.connector == SEC_BACKFILL_CONNECTOR]
        if backfill:
            # El backfill SEC guarda una marca por compania intentada
            # (potencialmente todo el universo US): una linea por fila
            # llenaria el panel de "empty/degraded" repetidas. Se agrega en
            # una sola linea con contadores por resultado (objecion del
            # auditor). El estado por compania se lee de la metadata que
            # escribe sec_fundamentals_backfill; los fallbacks cubren
            # marcas escritas sin metadata.
            def _outcome(state: ConnectorState) -> str:
                meta = (state.metadata_ or {}).get("status")
                if meta in ("ok", "skipped", "error"):
                    return meta
                if state.consecutive_errors:
                    return "error"
                return "ok" if state.last_success_at else "skipped"

            counts = {"ok": 0, "skipped": 0, "error": 0}
            for state in backfill:
                counts[_outcome(state)] += 1
            attempts = [stamp for s in backfill if (stamp := utc(s.last_started_at)) is not None]
            successes = [stamp for s in backfill if (stamp := utc(s.last_success_at)) is not None]
            last_attempt = max(attempts, default=None)
            last_success = max(successes, default=None)
            status = ("degraded" if counts["error"] else
                      "observed" if counts["ok"] else "empty")
            connectors.append({
                "source": (f"{SEC_BACKFILL_CONNECTOR} · {len(backfill)} empresas "
                           f"(ok {counts['ok']} · omitidas {counts['skipped']} · error {counts['error']})"),
                "last_success": last_success.isoformat() if last_success else None,
                "last_attempt": last_attempt.isoformat() if last_attempt else None,
                "status": status,
                "errors": counts["error"]})
    except Exception:  # noqa: BLE001
        db.rollback()
        connectors = []
        rows.append({"layer": "Conectores", "source": None, "covered": None, "total": total,
                     "coverage_pct": None, "last_update": None, "status": "error",
                     "max_age_days": None, "reason": "No se pudo leer el registro de conectores."})
    try:
        run = db.scalar(select(ProPickRun).where(ProPickRun.tenant_id == tenant).order_by(ProPickRun.as_of.desc()).limit(1))
        if run:
            count = db.scalar(select(func.count(ProPickCandidate.id)).where(ProPickCandidate.tenant_id == tenant, ProPickCandidate.run_id == run.id)) or 0
            stamp = utc(run.as_of)
            status = "degraded" if run.status not in {"completed", "ok", "success"} or (run.universe_size > 0 and count == 0) else "stale" if now - stamp > timedelta(days=7) else "observed"
            connectors.append({"source": "ProPicks · último run", "last_success": stamp.isoformat() if status == "observed" else None,
                               "last_attempt": stamp.isoformat(), "status": status, "errors": None})
    except Exception:  # noqa: BLE001
        db.rollback()
        connectors.append({"source": "ProPicks · último run", "last_success": None, "last_attempt": None, "status": "error", "errors": None})
    return {"as_of": now.isoformat(), "total_companies": total, "sources": rows, "connectors": connectors,
            "coverage_basis": "DERIVADO: empresas con al menos un registro / todas las empresas registradas. No mide completitud. Fuentes con alcance estructuralmente acotado (ESEF: emisores reviewed CNMV) llevan ademas eligible y coverage_pct_eligible con el denominador de elegibilidad real.",
            "freshness_basis": "Última escritura en la BD, no fecha del dato ni prueba de disponibilidad del proveedor."}


def read_inventory(db: Session) -> dict:
    tenant = db.info.get("tenant_id")
    if tenant is None:
        raise ValueError("Tenant context required")
    with _LOCK:
        cached = _CACHE.get(tenant)
        if cached and time.monotonic() - cached[0] < _CACHE_TTL_SECONDS:
            return cached[1]
    result = inventory(db)
    with _LOCK:
        if len(_CACHE) > 128:
            _CACHE.clear()
        _CACHE[tenant] = (time.monotonic(), result)
    return result
