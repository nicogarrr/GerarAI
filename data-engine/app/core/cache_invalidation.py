"""Invalidacion diferida de la cache Redis: se acumula en flush, se aplica tras commit.

app.core.cache esta desacoplada de los modelos para evitar ciclos de
importacion; este modulo es el punto de union. Los eventos ORM por fila
(after_insert/update/delete) saltan en el flush, ANTES del commit: otro
request podia recachear el dato viejo entre flush y commit y conservarlo
durante todo el TTL. En su lugar:

- ``after_flush`` solo ACUMULA en ``session.info`` las categorias y tenants
  tocados (sin tocar Redis: una escritura masiva cuesta dos sets).
- ``after_commit`` aplica las invalidaciones acumuladas: los datos nuevos ya
  son visibles para el resto de sesiones, asi que nadie puede recachear el
  estado anterior.
- ``after_rollback`` descarta lo acumulado: nada cambio, nada se invalida.

Las escrituras masivas por DML bulk no poblan session.new/dirty/deleted; los
flujos que las usan (market refresh, PATCH de precios, evaluate DCA) mantienen
su invalidacion explicita post-commit en el servicio o la ruta.

Se instala una sola vez desde app.models, que importan API, workers y tests.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_installed = False
_PENDING_KEY = "_cache_invalidation_pending"


def install_invalidation_listeners() -> None:
    """Registra los listeners de invalidacion diferida (idempotente)."""
    global _installed
    if _installed:
        return
    _installed = True

    from sqlalchemy import event
    from sqlalchemy.orm import Session as OrmSession

    from app.core.cache import invalidate_dca_cache, invalidate_portfolio_cache
    from app.models import (
        CashBalance,
        DcaAlertOverride,
        DcaAlertSettings,
        DcaSignalState,
        FxConversion,
        Portfolio,
        Position,
        Transaction,
        WatchItem,
    )

    # /portfolio/summary (RiskService.dashboard) lee posiciones, caja, cartera
    # y conversiones FX; los movimientos de dividendos entran como caja o
    # transacciones, cubiertas por CashBalance/Transaction.
    portfolio_models = (Transaction, CashBalance, Portfolio, FxConversion)
    # /watchlist/dca-signals mezcla watchlist, overrides, politica y estados.
    dca_models = (DcaSignalState, DcaAlertOverride, DcaAlertSettings, WatchItem)
    # Las posiciones alimentan AMBAS respuestas (la lista DCA incluye los
    # tickers de cartera via tracked_symbols).

    def _collect_pending(session: OrmSession, flush_context: Any) -> None:  # noqa: ANN401, ARG001
        try:
            pending = session.info.get(_PENDING_KEY)
            targets = [
                t
                for t in (*session.new, *session.dirty, *session.deleted)
                if isinstance(t, (*portfolio_models, *dca_models, Position))
            ]
            if not targets:
                return
            if pending is None:
                pending = {"portfolio": set(), "dca": set()}
                session.info[_PENDING_KEY] = pending
            for target in targets:
                tenant_id = getattr(target, "tenant_id", None)
                if isinstance(target, (*portfolio_models, Position)):
                    pending["portfolio"].add(tenant_id)
                if isinstance(target, (*dca_models, Position)):
                    pending["dca"].add(tenant_id)
        except Exception as exc:  # noqa: BLE001 -- nunca romper un flush
            logger.warning(f"Failed to collect pending cache invalidations: {exc}")

    def _apply_pending(session: OrmSession) -> None:
        pending = session.info.pop(_PENDING_KEY, None)
        if not pending:
            return
        try:
            for tenant_id in pending["portfolio"]:
                invalidate_portfolio_cache(tenant_id)
            for tenant_id in pending["dca"]:
                invalidate_dca_cache(tenant_id)
        except Exception as exc:  # noqa: BLE001 -- nunca romper un commit
            logger.warning(f"Failed to apply cache invalidations after commit: {exc}")

    def _discard_pending(session: OrmSession) -> None:
        session.info.pop(_PENDING_KEY, None)

    event.listen(OrmSession, "after_flush", _collect_pending)
    event.listen(OrmSession, "after_commit", _apply_pending)
    event.listen(OrmSession, "after_rollback", _discard_pending)
