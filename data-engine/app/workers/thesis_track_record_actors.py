"""Actor diario de «Nuestro acierto» (puntuar valores razonables vs precio real).

Módulo propio para no tocar dramatiq_app.py más de una línea; registrado con
``import app.workers.thesis_track_record_actors`` al final de dramatiq_app.py.
"""

from __future__ import annotations

from typing import Any

import dramatiq

from app.workers.dramatiq_app import _coalesce_on_success, _handle_actor_error, _session
from app.workers.dramatiq_app import broker as _broker  # noqa: F401


@dramatiq.actor(max_retries=1)
@_coalesce_on_success("refresh_thesis_track_record", 20 * 3600, ("tenant_id",))
def refresh_thesis_track_record(
    tenant_id: int | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    """Rellena los horizontes vencidos (6 y 12 meses) del tenant. Idempotente."""
    from app.services.thesis_track_record_service import refresh_track_record

    actor_name = "refresh_thesis_track_record"
    try:
        db = _session(tenant_id, user_id)
    except Exception as exc:
        return _handle_actor_error(actor_name, exc)
    try:
        result = refresh_track_record(db)
        return {**result, "actor": actor_name, "tenant_id": tenant_id}
    except Exception as exc:
        db.rollback()
        return _handle_actor_error(actor_name, exc)
    finally:
        db.close()
