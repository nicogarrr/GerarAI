"""Helpers de micro-duplicados unificados (tenant, idioma, effort, as_date).

Cada par de modulos consumidores comparte ahora UN solo objeto (alias), y el
hogar canonico fija el contrato que antes estaba copiado byte a byte.
"""

from datetime import UTC, date, datetime

from app.core.i18n import current_language_is_english
from app.core.local_date import as_date
from app.core.tenancy import session_tenant_id
from app.services import (
    brain_account_tools,
    brain_data_tools,
    chat_service,
    fair_value_service,
    journal_trade_link,
    thesis_deep_narrative,
    thesis_news_narrative,
    user_context,
)
from app.services.thesis_narrative_common import narrative_reasoning_effort


def test_session_tenant_id_contrato():
    class FakeSession:
        def __init__(self, info):
            self.info = info

    assert session_tenant_id(FakeSession({"tenant_id": 3})) == 3
    assert session_tenant_id(FakeSession({"tenant_id": 0})) is None
    assert session_tenant_id(FakeSession({"tenant_id": -2})) is None
    assert session_tenant_id(FakeSession({"tenant_id": "3"})) is None
    assert session_tenant_id(FakeSession({"tenant_id": True})) is None
    assert session_tenant_id(FakeSession({})) is None


def test_as_date_contrato():
    assert as_date(datetime(2026, 11, 1, 23, 59, tzinfo=UTC)) == date(2026, 11, 1)
    assert as_date(date(2026, 11, 1)) == date(2026, 11, 1)
    assert as_date("2026-11-01") is None
    assert as_date(None) is None


def test_narrative_reasoning_effort_explicito_gana():
    assert narrative_reasoning_effort("tesis_profunda", "  high ") == "high"
    # Sin explicito cae a la tabla por seccion de settings.
    assert narrative_reasoning_effort("tesis_profunda", None) == "low"
    assert narrative_reasoning_effort("tesis_profunda", "   ") == "low"


def test_alias_son_el_mismo_objeto():
    assert brain_account_tools._tenant is session_tenant_id
    assert user_context._tenant is session_tenant_id
    assert brain_data_tools._english is current_language_is_english
    assert chat_service._english is current_language_is_english
    assert thesis_deep_narrative._effort is narrative_reasoning_effort
    assert thesis_news_narrative._effort is narrative_reasoning_effort
    assert fair_value_service._as_date is as_date
    assert journal_trade_link._as_date is as_date
