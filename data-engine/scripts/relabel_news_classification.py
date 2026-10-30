"""Reetiquetado historico de NewsEvent: event_type e impact_direction.

Contexto: la clasificacion visible de una noticia (insignia
positiva/negativa/neutra y motivo) sale de NewsEvent.impact_direction y
NewsEvent.event_type, escritos SOLO en la ingesta (news_service llama a
MaterialityService.assess_news; es el unico punto de creacion de NewsEvent).
Las reglas mejoran con el tiempo (p.ej. selloff contestado, terminos con
borde de palabra) pero las filas ya persistidas conservan la etiqueta de su
version: un titular sano queda marcado como deterioro de tesis. La ingesta
es insert-only, asi que ningun deploy reetiqueta el historico.

Este script recalcula event_type e impact_direction con las reglas
VIGENTES (importa MATERIAL_KEYWORDS, _has_term y MaterialityService del
servicio, no una copia: si las reglas cambian, el reetiquetado cambia con
ellas) y actualiza solo las filas cuya etiqueta difiere.

Campos que muta: SOLO event_type e impact_direction.
NO toca materiality_score ni requires_update: dependen del peso de cartera
en el momento de la ingesta, del triage Jev y del impacto semantico sobre
la tesis; recomputarlos hoy inventaria una historia distinta de la vivida.
Tampoco toca title, summary ni metadata.

Base del calculo: el titulo y resumen PERSISTIDOS (lo que ve el usuario).
La ingesta clasifico titulo+cuerpo del item; el resumen persistido es ese
cuerpo (posiblemente saneado), asi que la base es fiel a lo mostrado.

Alcance conservador:
- Se excluyen las filas source == "manual": son datos escritos por el
  usuario, nunca se reescriben.
- Una fila cuya recomputacion coincide con lo almacenado no se toca: la
  segunda ejecucion planifica 0 cambios (idempotente).

Seguridad (mismo patron que scripts/retitle_sec_news_es.py):
- DRY-RUN por defecto en apply y en rollback: nada escribe sin --apply.
- Backup exclusivo y durable ANTES de tocar la BD: modo 'x' (nunca
  sobrescribe), fsync y renombrado atomico. Guarda los valores previos:
  el rollback restaura el estado exacto, no una aproximacion.
- --apply requiere --plan ruta.json: el dry-run escribe el plan revisado y
  --apply compara CADA fila contra ese plan (event_type, impact_direction,
  title y summary actuales == valores esperados); una fila que cambio
  desde el dry-run se salta y se reporta, no se pisa. Una unica
  transaccion; error = rollback de la transaccion.
- --rollback restaura con precondicion (la fila debe seguir con los
  valores que escribio este plan y el mismo texto base); filas editadas
  despues se saltan y se reportan.

Ejecutarlo sobre la BD de produccion es una decision aparte que requiere
aprobacion explicita del propietario con alcance y preview del dry-run.

Uso:
    python -m scripts.relabel_news_classification --plan /tmp/relabel-plan.json              # dry-run
    python -m scripts.relabel_news_classification --apply --plan /tmp/relabel-plan.json --backup /tmp/relabel-backup.json
    python -m scripts.relabel_news_classification --rollback /tmp/relabel-backup.json        # preview
    python -m scripts.relabel_news_classification --rollback /tmp/relabel-backup.json --apply
"""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models import NewsEvent
from app.services.materiality_service import (
    MATERIAL_KEYWORDS,
    MaterialityService,
    _has_term,
)

# Origen excluido: notas escritas por el usuario, nunca se reescriben.
_MANUAL_SOURCE = "manual"

_BASE_FIELDS = ("title", "summary")
_LABEL_FIELDS = ("event_type", "impact_direction")


def _recompute(title: str | None, summary: str | None) -> dict:
    """Etiqueta vigente para el texto persistido: (event_type, direction).

    Usa las funciones del servicio de materialidad, no una copia local:
    el reetiquetado sigue la regla actual aunque esta cambie despues.
    """
    lower_text = f"{title or ''} {summary or ''}".lower()
    matched = [
        event_type
        for event_type, keywords in MATERIAL_KEYWORDS.items()
        if any(_has_term(lower_text, keyword) for keyword in keywords)
    ]
    return {
        "event_type": matched[0] if matched else "general_news",
        "impact_direction": MaterialityService()._impact_direction(lower_text),
    }


def _plan_row(row) -> dict | None:
    """Plan de reetiquetado de una fila, o None si ya tiene la etiqueta vigente."""
    new = _recompute(row.title, row.summary)
    if all(getattr(row, field) == new[field] for field in _LABEL_FIELDS):
        return None  # ya vigente: idempotente
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "company_id": row.company_id,
        "expected": {
            "event_type": row.event_type,
            "impact_direction": row.impact_direction,
            # El texto base fija la etiqueta: si cambia, el plan ya no aplica.
            "title": row.title,
            "summary": row.summary,
        },
        "new": new,
    }


def _candidates(db) -> list:
    """Filas auto-ingeridas (nunca las manuales del usuario), orden estable."""
    rows = db.scalars(
        select(NewsEvent)
        .where(NewsEvent.source != _MANUAL_SOURCE)
        .order_by(NewsEvent.id)
    ).all()
    return list(rows)


def _write_json_atomic(path: str, payload) -> None:
    tmp = f"{path}.tmp-{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def _write_backup_durable(path: str, payload: list[dict]) -> None:
    """Backup exclusivo ('x': nunca sobrescribe) y durable ANTES de la BD."""
    tmp = f"{path}.tmp-{os.getpid()}"
    # Exclusivo tambien el temporal: dos apply concurrentes no se pisan.
    with open(tmp, "x", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
        fh.flush()
        os.fsync(fh.fileno())
    if os.path.exists(path):
        os.unlink(tmp)
        raise FileExistsError(f"el backup {path} ya existe: no se sobrescribe")
    os.replace(tmp, path)
    dir_flag = getattr(os, "O_DIRECTORY", 0)
    if dir_flag:
        dir_fd = os.open(os.path.dirname(os.path.abspath(path)), dir_flag)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)


def _apply_plan(db, planned: list[dict]) -> tuple[int, list[int]]:
    """Aplica el plan re-verificando cada fila; devuelve (aplicadas, saltadas).

    El plan revisado en dry-run no es un chequeo permanente: al aplicar se
    re-verifica identidad (tenant/company), origen no manual y estado
    esperado (etiquetas y texto base) en el momento del apply. Una fila que
    cambio desde el preview se salta y se reporta, no se pisa.
    """
    applied = 0
    skipped: list[int] = []
    for item in planned:
        row = db.get(NewsEvent, item["id"])
        if (
            row is None
            or row.tenant_id != item["tenant_id"]
            or row.company_id != item.get("company_id")
            or row.source == _MANUAL_SOURCE
        ):
            skipped.append(item["id"])
            continue
        current = {
            "event_type": row.event_type,
            "impact_direction": row.impact_direction,
            "title": row.title,
            "summary": row.summary,
        }
        if current != item["expected"]:
            # La fila cambio desde el plan revisado: no se pisa.
            skipped.append(item["id"])
            continue
        for field in _LABEL_FIELDS:
            setattr(row, field, item["new"][field])
        applied += 1
    return applied, skipped


def _summarize(planned: list[dict]) -> str:
    transitions = Counter(
        (item["expected"]["impact_direction"], item["new"]["impact_direction"])
        for item in planned
    )
    type_changes = Counter(
        (item["expected"]["event_type"], item["new"]["event_type"])
        for item in planned
        if item["expected"]["event_type"] != item["new"]["event_type"]
    )
    lines = [f"filas a reetiquetar: {len(planned)}"]
    for (old, new), count in sorted(transitions.items()):
        lines.append(f"  insignia: {old} -> {new}: {count}")
    for (old, new), count in sorted(type_changes.items()):
        lines.append(f"  motivo: {old} -> {new}: {count}")
    for item in planned[:10]:
        lines.append(
            f"  #{item['id']}: {item['expected']['impact_direction']}/{item['expected']['event_type']}"
            f" -> {item['new']['impact_direction']}/{item['new']['event_type']}"
            f" | {item['expected']['title'][:90]}"
        )
    return "\n".join(lines)


def _load_json(path: str):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _cmd_plan(args) -> int:
    db = SessionLocal()
    try:
        planned = []
        for row in _candidates(db):
            if args.tenant_id is not None and row.tenant_id != args.tenant_id:
                continue
            item = _plan_row(row)
            if item is not None:
                planned.append(item)
    finally:
        db.close()
    print(_summarize(planned))
    if args.plan:
        _write_json_atomic(args.plan, planned)
        print(f"plan escrito en {args.plan}")
    print("DRY-RUN: nada escrito en la BD. Revisa el plan y aplica con --apply.")
    return 0


def _cmd_apply(args) -> int:
    planned = _load_json(args.plan)
    if not planned:
        print("plan vacio: nada que aplicar")
        return 0
    # Backup exclusivo y durable ANTES de tocar la BD.
    _write_backup_durable(args.backup, planned)
    db = SessionLocal()
    try:
        applied, skipped = _apply_plan(db, planned)
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()
    print(f"aplicadas: {applied}; saltadas (cambiaron desde el plan): {len(skipped)}")
    if skipped:
        print(f"ids saltadas: {skipped[:50]}")
    print(f"backup en {args.backup}")
    return 0


def _cmd_rollback(args) -> int:
    backup = _load_json(args.rollback)
    db = SessionLocal()
    try:
        restorable = []
        blocked = 0
        for item in backup:
            row = db.get(NewsEvent, item["id"])
            ok = (
                row is not None
                and row.tenant_id == item["tenant_id"]
                and all(getattr(row, f) == item["new"][f] for f in _LABEL_FIELDS)
                and all(getattr(row, f) == item["expected"][f] for f in _BASE_FIELDS)
            )
            if ok:
                restorable.append(item)
            else:
                blocked += 1
        if not args.apply:
            print(
                f"rollback DRY-RUN: {len(restorable)} filas restaurables, "
                f"{blocked} bloqueadas (editadas despues del plan)"
            )
            return 0
        for item in restorable:
            row = db.get(NewsEvent, item["id"])
            for field in _LABEL_FIELDS:
                setattr(row, field, item["expected"][field])
        db.commit()
        print(f"restauradas: {len(restorable)}; bloqueadas: {blocked}")
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--plan", help="ruta del plan JSON (dry-run lo escribe; --apply lo lee)")
    parser.add_argument("--apply", action="store_true", help="escribe en la BD (sin el, dry-run)")
    parser.add_argument("--backup", help="ruta del backup JSON (exclusivo, no sobrescribe)")
    parser.add_argument("--rollback", metavar="BACKUP", help="restaura desde un backup")
    parser.add_argument("--tenant-id", type=int, default=None, help="limita el plan a un tenant")
    args = parser.parse_args(argv)

    if args.rollback:
        return _cmd_rollback(args)
    if args.apply:
        if not args.plan or not args.backup:
            parser.error("--apply requiere --plan y --backup")
        return _cmd_apply(args)
    return _cmd_plan(args)


if __name__ == "__main__":
    raise SystemExit(main())
