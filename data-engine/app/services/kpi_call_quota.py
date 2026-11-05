"""Tope de intentos LLM diarios; exceso diferido, no datos descartados."""
import os
from types import SimpleNamespace

from app.core.config import get_settings
from app.services.asts_llm_quota import QuotaNamespace, reserve_quota

NAMESPACE = QuotaNamespace(key="kpi-extraction", minute_setting="minute_cap", day_setting="day_cap",
                           missing_tenant_error="KPI extraction requires tenant")


class KPIDailyDeferred(RuntimeError):
    pass


def reserve(tenant_id):
    settings = get_settings()
    cap = max(0, int(os.getenv("KPI_EXTRACTION_CALLS_PER_DAY", "20")))
    result = reserve_quota(tenant_id, SimpleNamespace(is_production=settings.is_production,
        redis_url=settings.redis_url, minute_cap=max(cap, 1), day_cap=cap), namespace=NAMESPACE)
    if not result["allowed"]:
        raise KPIDailyDeferred("KPI daily call limit reached; document deferred")
    return result
