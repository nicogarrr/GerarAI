"""Puerta de publicación del inventario de impulsores de valor.

El Recopilador guarda contratos, países, opciones y demás impulsores con su
fuente. Esta costura lee el inventario vigente del tenant y aplica la regla ya
existente: un impulsor firmado y material sin tratamiento bloquea la
publicación del valor. No inventa drivers ni trata rumores como firmados.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.services.value_driver_service import ValueDriverService, as_item


def _row_payload(row: Any) -> dict[str, Any]:
    item = as_item(row)
    return {
        "driver_key": item.driver_key,
        "category": item.category,
        "name": item.name,
        "status": item.status,
        "treatment": item.treatment,
        "source_type": item.source_type,
        "evidence": item.evidence,
        "source_url": item.source_url,
        "source_quote": item.source_quote,
        "as_of": item.as_of.isoformat() if item.as_of else None,
        "headline": bool(item.headline),
        "value_per_share_marginal": (
            float(item.value_per_share_marginal)
            if item.value_per_share_marginal is not None
            else None
        ),
        "model_link": item.model_link,
        "reason_if_not_valued": item.reason_if_not_valued,
    }


def value_driver_gate(db: Session, company: Any) -> dict[str, Any]:
    """Inventario vigente + veredicto de publicación (nunca lanza)."""
    info = getattr(db, "info", {}) or {}
    tenant_id = info.get("tenant_id") if isinstance(info, dict) else None
    if type(tenant_id) is not int or tenant_id <= 0 or company.id is None:
        return {"status": "no_tenant", "publishable": True, "drivers": [], "blocking": []}
    service = ValueDriverService()
    try:
        rows = service.current(db, company_id=company.id, tenant_id=tenant_id)
        check = service.check_publication(
            db, company_id=company.id, tenant_id=tenant_id
        )
    except Exception as exc:  # noqa: BLE001 - una puerta de publicación falla cerrada
        return {
            "status": "error",
            "publishable": False,
            "blocker": "inventario_impulsores_no_verificable",
            "reason": f"{type(exc).__name__}",
            "drivers": [],
            "blocking": [],
        }
    return {
        "status": "ok" if check.publishable else "blocked",
        "publishable": check.publishable,
        "blocker": None if check.publishable else "impulsor_material_sin_tratar",
        "reason": check.reason,
        "blocking": [block.as_dict() for block in check.blocking],
        "drivers": [_row_payload(row) for row in sorted(rows.values(), key=lambda r: r.driver_key)],
    }


__all__ = ["value_driver_gate"]
