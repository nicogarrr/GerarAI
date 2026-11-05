"""Global operations must fail closed before touching shared state."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException

from app.api.routes import cache, db_metrics


@pytest.mark.parametrize('allowed', [False, True])
def test_reset_stats_is_gated_before_mutation(monkeypatch, allowed):
    monkeypatch.setattr(cache, 'get_settings', lambda: SimpleNamespace(cache_global_invalidation_allowed=allowed))
    reset = Mock()
    monkeypatch.setattr(cache, 'reset_cache_stats', reset)
    if allowed:
        assert cache.reset_stats()['status'] == 'ok'
        reset.assert_called_once_with()
    else:
        with pytest.raises(HTTPException) as exc:
            cache.reset_stats()
        assert exc.value.status_code == 404
        reset.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize('allowed', [False, True])
async def test_db_metrics_is_gated_before_collecting(monkeypatch, allowed):
    monkeypatch.setattr(db_metrics, 'get_settings', lambda: SimpleNamespace(cache_global_invalidation_allowed=allowed))
    collect = AsyncMock(return_value={'metrics': 'ok'})
    monkeypatch.setattr(db_metrics, '_collect_metrics', collect)
    session = object()
    if allowed:
        assert await db_metrics.db_metrics(session) == {'metrics': 'ok'}
        collect.assert_awaited_once_with(session)
    else:
        with pytest.raises(HTTPException) as exc:
            await db_metrics.db_metrics(session)
        assert exc.value.status_code == 404
        collect.assert_not_awaited()
