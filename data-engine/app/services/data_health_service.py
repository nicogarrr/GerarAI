"""Inventory of persisted coverage, not a claim that upstream providers are live."""
from __future__ import annotations

import threading
import time
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy import func, select
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


def _coverage_groups(db: Session, *, model, source, table: str, source_col: str,
                     tenant_clause: str, extra_clause: str, params: dict,
                     tenant) -> list[tuple[str, int, object]]:
    """(fuente, empresas distintas, ultima escritura) por capa, sin barrer la tabla.

    El group-by con count(distinct company_id) leia TODA la porcion de la capa
    (medido en frio en prod por el piloto: 17-18 s tras la cache de 003c1644 y
    los indices de 0119; el panel seguia pagando ese coste cada vez que un
    worker entraba en frio). Lo que el panel necesita son los pares
    (fuente, empresa) distintos: miles, no millones. La CTE recursiva hace un
    barrido perezoso (loose index scan): una sonda de indice por par en vez de
    leer cada fila. El max(updated_at) por fuente son sondas puntuales.

    SQL portable (subconsultas escalares, sin LATERAL: sqlite lo ejecuta igual
    y los tests lo cubren; en PG los indices parciales de 0122 hacen cada
    sonda O(log n)). Resultado exactamente igual al group-by: mismos filtros,
    mismos pares, mismo max. Medido en el laboratorio con forma de prod
    (PG 14, 4,9M precios / 3,1M facts / 1M docs / 1M news, caliente):
    1.088 ms -> 107 ms las cuatro capas; detalle en el PR.

    table/source_col son literales fijos del propio modulo (LAYERS), nunca
    entrada del usuario.
    """
    filtros = f"{source_col} NOT IN {_NOT_SOURCES_SQL} AND company_id IS NOT NULL{extra_clause}{tenant_clause}"
    salto = (f"(t2.{source_col}, t2.company_id) > (pairs.src, pairs.cid)")
    sql = sa.text(f"""
        WITH RECURSIVE pairs(src, cid) AS (
          SELECT * FROM (SELECT {source_col}, company_id FROM {table}
           WHERE {filtros} ORDER BY {source_col}, company_id LIMIT 1)
          UNION ALL
          SELECT (SELECT t2.{source_col} FROM {table} t2
                  WHERE {filtros.replace(source_col, 't2.' + source_col).replace('company_id IS NOT NULL', 't2.company_id IS NOT NULL')} AND {salto}
                  ORDER BY t2.{source_col}, t2.company_id LIMIT 1),
                 (SELECT t2.company_id FROM {table} t2
                  WHERE {filtros.replace(source_col, 't2.' + source_col).replace('company_id IS NOT NULL', 't2.company_id IS NOT NULL')} AND {salto}
                  ORDER BY t2.{source_col}, t2.company_id LIMIT 1)
          FROM pairs WHERE pairs.src IS NOT NULL
        )
        SELECT src, count(*) FROM pairs WHERE src IS NOT NULL GROUP BY src
    """)
    grupos = []
    for src_name, covered in db.execute(sql, params).all():
        # Sonda max via ORM: misma consulta (indice (…, source, updated_at) de
        # 0122), con la coercion de tipos del dialecto (text() devolvia str en
        # sqlite y rompia utc()).
        # max() en PG no salta al final del indice: lo agrega entero. La forma
        # ORDER BY ... DESC LIMIT 1 con el filtro IS NOT NULL si lo hace
        # (sonda hacia atras sobre ix_*_health_src_upd / ix_prices_source_upd)
        # y devuelve lo mismo: max ignora NULLs; aqui el mayor no nulo, o None
        # si no hay ninguno. Sin NULLS LAST a proposito: ese modificador no lo
        # satisface el indice (DESC por defecto es NULLS FIRST) y forzaba un
        # sort de toda la fuente; el filtro ya hace irrelevante el orden de
        # los nulos. Medido: 103 ms -> 0,1 ms por fuente.
        stamp_query = (
            select(model.updated_at)
            .where(
                source == src_name,
                source.not_in(["seed", "manual", "test", "dummy", "placeholder"]),
                model.company_id.is_not(None),
                model.updated_at.is_not(None),
            )
            .order_by(model.updated_at.desc())
            .limit(1)
        )
        if model is not MarketPrice:
            stamp_query = stamp_query.where(model.tenant_id == tenant)
        if model is FinancialFact:
            stamp_query = stamp_query.where(model.is_reported)
        if model is MarketPrice:
            stamp_query = stamp_query.where(model.close > 0)
        stamp = db.scalar(stamp_query)
        grupos.append((src_name, covered, stamp))
    return grupos

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
            tenant_clause = "" if model is MarketPrice else " AND tenant_id = :tenant"
            extra = ""
            if model is FinancialFact:
                # Literal bare "is_reported": coincide textualmente con el predicado
                # parcial de los indices de 0122 (con IS TRUE o con parametro el
                # planner NO prueba la implicacion y barre la porcion del tenant:
                # medido 103 ms vs 0,3 ms por sonda).
                extra = " AND is_reported"
            if model is MarketPrice:
                extra = " AND close > 0"
            params = {"tenant": tenant, "is_rep": True}
            groups = _coverage_groups(
                db, model=model, source=source, table=model.__tablename__,
                source_col=source_field, tenant_clause=tenant_clause,
                extra_clause=extra, params=params, tenant=tenant,
            )
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
