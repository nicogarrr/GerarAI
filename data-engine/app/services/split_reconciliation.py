"""Planificador DRY-RUN de reconciliación de splits duplicados.

Solo LEE. No borra, no aplica y no modifica ninguna fila: devuelve un plan que
una persona revisa. Cualquier saneamiento posterior es un paso aparte, con su
propia autorización.

Qué es un duplicado
-------------------
Dos filas de ``corporate_actions`` del MISMO tenant, MISMA empresa y MISMO
tipo de evento (split / reverse_split) con el MISMO ratio y fechas efectivas a
``SAME_EVENT_DAYS`` días o menos entre sí (Yahoo y FMP fechan el mismo split con
un día de diferencia; ver ``SplitIngestionService._existing_record``).

Qué NO es un duplicado (evento legítimo, jamás se propone tocarlo)
------------------------------------------------------------------
- Mismo ratio con fechas separadas por más de ``SAME_EVENT_DAYS`` días: dos
  splits 2:1 distintos (p. ej. años distintos).
- Misma fecha con ratios distintos: eventos distintos (2:1 y 1:2, o
  ordinario más especial). Se informa como ``same_day_different_ratio`` sin
  proponer nada.
- Filas de otro tenant o de otra empresa, aunque coincidan ratio y fecha.
- Tipos que no son split (merger, spin_off, ticker_change).

La ventana se ancla en la primera fila del grupo (sin encadenar): A, A+3, A+6
no forman un solo grupo.

Reglas de seguridad del plan
----------------------------
- Una fila ``applied`` es inmutable: nunca se propone borrarla. Si un grupo
  tiene más de una fila aplicada, se marca ``double_applied`` (posible doble
  ajuste de acciones y coste) y exige revisión manual: no se propone nada.
- Entre filas sin aplicar, se conserva la preferida (aplicada > fuente de
  proveedor con ``fetched_at`` > id menor) y se proponen las demás.
- Idempotente: el plan solo depende del contenido de las filas; dos llamadas
  seguidas dan el mismo plan y la misma huella (``fingerprint``). Tras retirar
  las filas propuestas, un nuevo plan sale vacío.
- Seguro por tenant: con ``tenant_id`` lee solo ese tenant; sin él y sin
  contexto de tenant, falla cerrado igual que ``tenant_filters`` salvo que se
  pida ``all_tenants=True`` de forma explícita (comando de operación).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.tenancy import tenant_filters
from app.models import CorporateAction

SPLIT_TYPES = ("split", "reverse_split")
SAME_EVENT_DAYS = 3
# Un split con fecha del 1/1/1970 es casi siempre una época Unix mal parseada.
EPOCH_SUSPECT_BEFORE = date(1971, 1, 1)


@dataclass(frozen=True)
class ActionRow:
    id: int
    tenant_id: int | None
    company_id: int
    action_type: str
    effective_date: date
    ratio: Decimal
    applied: bool
    source: str
    has_fetched_at: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "action_type": self.action_type,
            "effective_date": self.effective_date.isoformat(),
            "ratio": format(self.ratio.normalize(), "f"),
            "applied": self.applied,
            "source": self.source,
        }


@dataclass
class DuplicateGroup:
    tenant_id: int | None
    company_id: int
    ratio: Decimal
    kind: str  # exact_duplicate | provider_date_skew
    status: str  # proposed | double_applied
    keep: ActionRow | None
    remove: list[ActionRow] = field(default_factory=list)
    members: list[ActionRow] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "company_id": self.company_id,
            "ratio": format(self.ratio.normalize(), "f"),
            "kind": self.kind,
            "status": self.status,
            "keep": self.keep.as_dict() if self.keep else None,
            "propose_remove_unapplied_ids": [r.id for r in self.remove],
            "members": [m.as_dict() for m in self.members],
        }


@dataclass
class ReconciliationPlan:
    dry_run: bool
    duplicate_groups: list[DuplicateGroup]
    same_day_different_ratio: list[dict[str, Any]]
    epoch_suspects: list[ActionRow]
    rows_examined: int

    @property
    def proposed_removals(self) -> list[int]:
        return sorted(r.id for g in self.duplicate_groups for r in g.remove)

    def as_dict(self) -> dict[str, Any]:
        body = {
            "dry_run": self.dry_run,
            "rows_examined": self.rows_examined,
            "duplicate_group_count": len(self.duplicate_groups),
            "double_applied_group_count": sum(
                1 for g in self.duplicate_groups if g.status == "double_applied"
            ),
            "proposed_removal_count": len(self.proposed_removals),
            "duplicate_groups": [g.as_dict() for g in self.duplicate_groups],
            "same_day_different_ratio": self.same_day_different_ratio,
            "epoch_suspects": [r.as_dict() for r in self.epoch_suspects],
        }
        body["fingerprint"] = hashlib.sha256(
            json.dumps(body, sort_keys=True, default=str).encode()
        ).hexdigest()
        return body


def _keeper_key(row: ActionRow) -> tuple[int, int, int]:
    # Menor es mejor: aplicada primero, luego fila con procedencia de
    # proveedor (fetched_at), luego id menor (determinista).
    return (0 if row.applied else 1, 0 if row.has_fetched_at else 1, row.id)


def _load_rows(db: Session, *, tenant_id: int | None, all_tenants: bool) -> list[ActionRow]:
    stmt = select(CorporateAction).where(CorporateAction.action_type.in_(SPLIT_TYPES))
    if tenant_id is not None:
        stmt = stmt.where(CorporateAction.tenant_id == tenant_id)
    elif not all_tenants:
        # Falla cerrado sin contexto de tenant (producción / auth requerida).
        for predicate in tenant_filters(db, CorporateAction):
            stmt = stmt.where(predicate)
    with db.no_autoflush:
        rows = db.scalars(stmt.order_by(CorporateAction.id)).all()
    return [
        ActionRow(
            id=r.id,
            tenant_id=r.tenant_id,
            company_id=r.company_id,
            action_type=r.action_type,
            effective_date=r.effective_date,
            ratio=Decimal(r.ratio),
            applied=bool(r.applied),
            source=r.source or "",
            has_fetched_at=r.fetched_at is not None,
        )
        for r in rows
    ]


def plan_split_reconciliation(
    db: Session,
    *,
    tenant_id: int | None = None,
    all_tenants: bool = False,
) -> ReconciliationPlan:
    """Calcula el plan sin escribir nada (``db`` no se modifica ni se confirma)."""
    rows = _load_rows(db, tenant_id=tenant_id, all_tenants=all_tenants)

    by_scope: dict[tuple[int | None, int], list[ActionRow]] = {}
    for row in rows:
        by_scope.setdefault((row.tenant_id, row.company_id), []).append(row)

    groups: list[DuplicateGroup] = []
    conflicts: list[dict[str, Any]] = []
    for (tenant, company), scope_rows in sorted(
        by_scope.items(), key=lambda item: (item[0][0] is None, item[0][0] or 0, item[0][1])
    ):
        # Mismo día con ratios distintos: información, nunca duplicado.
        by_day: dict[date, set[Decimal]] = {}
        for row in scope_rows:
            by_day.setdefault(row.effective_date, set()).add(row.ratio.normalize())
        for day, ratios in sorted(by_day.items()):
            if len(ratios) > 1:
                conflicts.append(
                    {
                        "tenant_id": tenant,
                        "company_id": company,
                        "effective_date": day.isoformat(),
                        "ratios": sorted(format(r, "f") for r in ratios),
                    }
                )

        # Agrupa por ratio exacto y ancla la ventana en la primera fila.
        by_ratio: dict[Decimal, list[ActionRow]] = {}
        for row in scope_rows:
            by_ratio.setdefault(row.ratio.normalize(), []).append(row)
        for ratio, ratio_rows in sorted(by_ratio.items()):
            pending = sorted(ratio_rows, key=lambda r: (r.effective_date, r.id))
            while pending:
                anchor = pending[0]
                window_end = anchor.effective_date + timedelta(days=SAME_EVENT_DAYS)
                members = [r for r in pending if r.effective_date <= window_end]
                pending = [r for r in pending if r.effective_date > window_end]
                if len(members) < 2:
                    continue
                kind = (
                    "exact_duplicate"
                    if len({m.effective_date for m in members}) == 1
                    else "provider_date_skew"
                )
                applied_rows = [m for m in members if m.applied]
                if len(applied_rows) > 1:
                    groups.append(
                        DuplicateGroup(
                            tenant_id=tenant, company_id=company, ratio=ratio, kind=kind,
                            status="double_applied", keep=None, remove=[], members=members,
                        )
                    )
                    continue
                keeper = min(members, key=_keeper_key)
                remove = [m for m in members if m.id != keeper.id and not m.applied]
                groups.append(
                    DuplicateGroup(
                        tenant_id=tenant, company_id=company, ratio=ratio, kind=kind,
                        status="proposed", keep=keeper,
                        remove=sorted(remove, key=lambda r: r.id), members=members,
                    )
                )

    epoch = [r for r in rows if r.effective_date < EPOCH_SUSPECT_BEFORE]
    return ReconciliationPlan(
        dry_run=True,
        duplicate_groups=groups,
        same_day_different_ratio=conflicts,
        epoch_suspects=epoch,
        rows_examined=len(rows),
    )
