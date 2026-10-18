"""Inventory of persisted coverage, not a claim that upstream providers are live."""
from __future__ import annotations

import threading
import time
from datetime import UTC, datetime, timedelta

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

        tickers = {issuer.ticker.upper() for issuer in REVIEWED_ISSUERS}
        tickers |= {f"{t}.MC" for t in tickers}
        return db.scalar(
            select(func.count(Company.id)).where(func.upper(Company.ticker).in_(tickers))
        ) or 0
    return None


_CACHE: dict[int, tuple[float, dict]] = {}
_LOCK = threading.Lock()
LAYERS = (
    ("Fundamentales", FinancialFact, "source_type", 90),
    ("Documentos", Document, "source_type", 30),
    ("Precios diarios", MarketPrice, "source", 4),
    ("Noticias", NewsEvent, "source", 7),
)


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
                       "errors": state.consecutive_errors} for state in states]
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
        if cached and time.monotonic() - cached[0] < 60:
            return cached[1]
    result = inventory(db)
    with _LOCK:
        if len(_CACHE) > 128:
            _CACHE.clear()
        _CACHE[tenant] = (time.monotonic(), result)
    return result
