"""Lo que produce el equipo de expertos, como entrada citada de la tesis v2 (que no se pierda nada).

El pipeline de la tesis (``thesis_service._run_thesis_experts``) corre el Recopilador, la mezcla de analistas
y el escéptico antes de valorar. Hasta el 8-nov-2026 la tesis v2 no leía nada de eso: el inventario de
impulsores, los supuestos por firma y los juicios del escéptico se perdían. Aquí se leen de donde quedan:

- el Recopilador guarda el inventario de impulsores (``value_drivers``) con su cita y su fuente;
- la mezcla de analistas guarda los supuestos por firma (``declared_input_values`` con ``analyst_firm``);
- el escéptico no escribe en la base: ``store_pipeline`` guarda su salida (y el estado de cada etapa) en una
  fila ``declared_input_values`` con ``input_key = "thesis_experts"`` (tabla existente, sin migración).

Las cifras de los supuestos de analistas llegan a la tesis como marcadores formateados por el código
(``expertos.analista.N.valor``); el modelo solo cita, clasifica y redacta.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

EXPERTS_KEY = "thesis_experts"
MAX_DRIVERS = 20
MAX_ANALYST_INPUTS = 20
MAX_BELIEFS = 20


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(k): _jsonable(v) for k, v in value.items() if not str(k).startswith("_")}
    if isinstance(value, list | tuple | set | frozenset):
        return [_jsonable(v) for v in value]
    if isinstance(value, date | datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if value is None or isinstance(value, str | int | float | bool):
        return value
    return str(value)


def store_pipeline(db: Session, company_id: int, pipeline: Mapping[str, Any] | None, *, today: date | None = None) -> bool:
    """Guarda la salida del pipeline de expertos de esta tesis (sustituye a la anterior). No commitea."""
    from app.models.declared_input_value import DeclaredInputValue

    if not isinstance(pipeline, Mapping) or not pipeline.get("stages"):
        return False
    stages = _jsonable(pipeline.get("stages") or [])
    blob = json.dumps(stages, sort_keys=True, ensure_ascii=False, default=str)
    fp = hashlib.sha256(blob.encode()).hexdigest()
    prev = _latest(db, company_id)
    if prev is not None and prev.fingerprint == fp:
        return False
    if prev is not None:
        prev.superseded_at = datetime.now(UTC)
    db.add(DeclaredInputValue(
        company_id=company_id, input_key=EXPERTS_KEY, segment_key="", base=Decimal("0"), unit="ratio",
        status="derivado", method="derive", as_of=today or date.today(), model_family="expert_team",
        fingerprint=fp, source_quote="Salida del equipo de expertos (Recopilador, mezcla de analistas, escéptico)",
        metadata_={"stages": stages, "consensus": _jsonable(pipeline.get("consensus")),
                   "consensus_source": pipeline.get("consensus_source")},
    ))
    db.flush()
    return True


def _latest(db: Session, company_id: int):
    from app.models.declared_input_value import DeclaredInputValue

    return db.scalars(select(DeclaredInputValue).where(
        DeclaredInputValue.company_id == company_id, DeclaredInputValue.input_key == EXPERTS_KEY,
        DeclaredInputValue.superseded_at.is_(None)).order_by(desc(DeclaredInputValue.id))).first()


def _drivers(db: Session, company_id: int, tenant_id: int | None) -> list[dict[str, Any]]:
    if type(tenant_id) is not int or tenant_id <= 0:
        return []
    from app.services.value_driver_service import ValueDriverService

    try:
        rows = ValueDriverService().current(db, company_id=company_id, tenant_id=tenant_id)
    except Exception:  # noqa: BLE001 - sin inventario la tesis sigue
        return []
    out = []
    for row in list(rows.values())[:MAX_DRIVERS]:
        out.append({"clave": row.driver_key, "nombre": row.name, "categoria": row.category, "estado": row.status,
                    "tratamiento": row.treatment, "plazo": row.timing, "fuente": row.source_url,
                    "cita": (row.source_quote or "")[:600], "por_que_no_se_valora": row.reason_if_not_valued})
    return out


def _analyst_inputs(db: Session, company_id: int) -> list[dict[str, Any]]:
    from app.models.declared_input_value import DeclaredInputValue

    rows = db.scalars(select(DeclaredInputValue).where(
        DeclaredInputValue.company_id == company_id, DeclaredInputValue.analyst_firm.is_not(None),
        DeclaredInputValue.superseded_at.is_(None)).order_by(desc(DeclaredInputValue.as_of), DeclaredInputValue.id)
        .limit(MAX_ANALYST_INPUTS)).all()
    return [{"input": r.input_key + (f"@{r.segment_key}" if r.segment_key else ""), "firma": r.analyst_firm,
             "base": float(r.base) if r.base is not None else None,
             "bajo": float(r.low) if r.low is not None else None, "alto": float(r.high) if r.high is not None else None,
             "unidad": r.unit, "fuente": r.source_url, "cita": (r.source_quote or "")[:600],
             "fecha": r.as_of.isoformat() if r.as_of else None} for r in rows]


def _stage(meta: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    for st in meta.get("stages") or []:
        if isinstance(st, Mapping) and st.get("name") == name:
            return st
    return {}


def expert_block(db: Session, company: Any, tenant_id: int | None) -> dict[str, Any] | None:
    """Lo que dejó el equipo para esta empresa, con sus fuentes; None si no dejó nada."""
    row = _latest(db, company.id)
    meta = (row.metadata_ or {}) if row is not None else {}
    skeptic = _stage(meta, "esceptico")
    beliefs = [b for b in (skeptic.get("beliefs") or []) if isinstance(b, Mapping)][:MAX_BELIEFS]
    block = {
        "impulsores": _drivers(db, company.id, tenant_id),
        "supuestos_de_analistas": _analyst_inputs(db, company.id),
        "esceptico": [dict(b) for b in beliefs],
        "etapas": {str(st.get("name")): st.get("status") for st in meta.get("stages") or [] if isinstance(st, Mapping)},
        "fecha": row.as_of.isoformat() if row is not None and row.as_of else None,
    }
    if not (block["impulsores"] or block["supuestos_de_analistas"] or block["esceptico"]):
        return None
    return block


def _fmt(value: float | None, unit: str | None) -> str:
    from app.services.expert_team.thesis_v2 import _es

    if value is None:
        return "N/D"
    u = (unit or "").lower()
    if u in ("ratio", "pct", "percent", "%"):
        return (_es(value * 100, 1) + " %").replace("-", "−")
    if u in ("x", "multiple", "múltiplo"):
        return _es(value, 1) + "x"
    return (_es(value, 2) + (f" {unit}" if unit else "")).replace("-", "−")


def expert_markers(block: Mapping[str, Any] | None) -> dict[str, str]:
    """Cifras de los supuestos de analistas como marcadores (formato del código)."""
    m: dict[str, str] = {}
    for i, a in enumerate((block or {}).get("supuestos_de_analistas") or [], start=1):
        m[f"expertos.analista.{i}.valor"] = _fmt(a.get("base"), a.get("unidad"))
        if a.get("bajo") is not None and a.get("alto") is not None:
            m[f"expertos.analista.{i}.rango"] = f"{_fmt(a['bajo'], a.get('unidad'))}–{_fmt(a['alto'], a.get('unidad'))}"
    return m


def expert_payload(block: Mapping[str, Any] | None) -> dict[str, Any] | str:
    """Lo que ve el modelo: el trabajo del equipo, sin cifras sueltas (las de analistas van por marcador)."""
    if not block:
        return "el equipo de expertos no dejó inventario, supuestos ni juicios para esta empresa: no lo menciones"
    analysts = []
    for i, a in enumerate(block.get("supuestos_de_analistas") or [], start=1):
        item = {"input": a["input"], "firma": a["firma"], "valor": "{{" + f"expertos.analista.{i}.valor" + "}}",
                "fuente": a["fuente"], "cita": a["cita"], "fecha": a["fecha"]}
        if a.get("bajo") is not None and a.get("alto") is not None:
            item["rango"] = "{{" + f"expertos.analista.{i}.rango" + "}}"
        analysts.append(item)
    return {
        "impulsores_del_recopilador": block.get("impulsores") or [],
        "supuestos_de_analistas": analysts,
        "juicios_del_escéptico": block.get("esceptico") or [],
        "nota": ("Trabajo del equipo de expertos, con su fuente. Úsalo TODO donde toque: los impulsores en "
                 "negocio, ventaja y riesgos; los supuestos de analistas en guía y consenso (cada uno con su "
                 "firma y su marcador); los juicios del escéptico («qué hace falta creer», «aceptamos / rechazamos "
                 "/ abierta» y el dato que lo cierra) en valoración, riesgos y qué vigilar. Si citas, copia la "
                 "cita literal que trae cada elemento."),
    }


def experts_table(block: Mapping[str, Any] | None) -> dict[str, Any]:
    """Tabla que pinta el código bajo «Riesgos»: cada juicio del escéptico e impulsor, con su fuente."""
    rows: list[list[str]] = []
    links: list[str | None] = []
    beliefs = {str(b.get("driver_key")): b for b in (block or {}).get("esceptico") or []}
    for d in (block or {}).get("impulsores") or []:
        b = beliefs.pop(str(d.get("clave")), None) or {}
        rows.append([str(d.get("nombre") or d.get("clave")), str(d.get("estado") or ""),
                     str(b.get("hace_falta_creer") or ""), str(b.get("postura") or "sin juicio"),
                     str(b.get("motivo") or b.get("dato_que_lo_cierra") or "")])
        links.append(b.get("fuente") or d.get("fuente"))
    for key, b in beliefs.items():
        rows.append([key, "", str(b.get("hace_falta_creer") or ""), str(b.get("postura") or ""),
                     str(b.get("motivo") or b.get("dato_que_lo_cierra") or "")])
        links.append(b.get("fuente"))
    return {"title": "Equipo de expertos: impulsores y juicio del escéptico (cada fila con su fuente)",
            "head": ["Impulsor", "Estado", "Qué hace falta creer", "Postura", "Motivo o dato que lo cierra"],
            "rows": rows, "links": links}


def block_fingerprint(block: Mapping[str, Any] | None) -> str:
    return hashlib.sha256(json.dumps(_jsonable(block or {}), sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


__all__ = ["EXPERTS_KEY", "block_fingerprint", "expert_block", "expert_markers", "expert_payload",
           "experts_table", "store_pipeline"]
