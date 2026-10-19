"""No real network: adversarial slow-primary canaries use the real factory/adapter."""
import asyncio
import json

import httpx
import pytest

from app.core.config import Settings
from app.llm import LLMRequest, Message, create_llm_provider
from app.llm.errors import ProviderTransportError

PRIMARY = 'deepseek-v4.1-flash-free'
FALLBACK = 'space-bunny-free'
BODY = {
    'choices': [{'message': {'content': 'ok'}, 'finish_reason': 'stop'}],
    'usage': {'prompt_tokens': 1, 'completion_tokens': 1, 'total_tokens': 2},
}


def provider(client, fallback=FALLBACK, retries=2):
    return create_llm_provider(Settings(
        _env_file=None,
        opencode_go_api_key='test-secret',
        opencode_go_base_url='https://opencode.test/v1',
        opencode_go_model=PRIMARY,
        opencode_go_fallback_model=fallback,
        llm_total_timeout_seconds=0.3,
        llm_timeout_seconds=30,
        llm_max_retries=retries,
    ), client=client)


def request():
    return LLMRequest(messages=[Message('user', 'x')], cache=False)


def test_slow_primary_and_real_factory_gives_fallback_time():
    seen = []
    cancelled = []

    async def handler(req):
        model = json.loads(req.content)['model']
        seen.append(model)
        if model == PRIMARY:
            try:
                await asyncio.sleep(5)
            except asyncio.CancelledError:
                cancelled.append(model)
                raise
        # Consume some of the reserved budget, not an instantaneous response.
        await asyncio.sleep(0.04)
        return httpx.Response(200, json={**BODY, 'model': model})

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            response = await provider(client).complete(request())
            assert response.text == 'ok'
            assert response.model == FALLBACK

    asyncio.run(asyncio.wait_for(scenario(), timeout=2))
    assert seen == [PRIMARY, FALLBACK]
    assert cancelled == [PRIMARY]


def test_primary_budget_also_interrupts_retry_backoff():
    seen = []

    async def handler(req):
        model = json.loads(req.content)['model']
        seen.append(model)
        if model == PRIMARY:
            raise httpx.ReadTimeout('isolated slow primary', request=req)
        return httpx.Response(200, json={**BODY, 'model': model})

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            assert (await provider(client).complete(request())).model == FALLBACK

    asyncio.run(asyncio.wait_for(scenario(), timeout=2))
    assert seen[0] == PRIMARY
    assert FALLBACK in seen


def test_hung_fallback_still_obeys_total_deadline():
    seen = []
    cancelled = []

    async def handler(req):
        model = json.loads(req.content)['model']
        seen.append(model)
        try:
            await asyncio.sleep(5)
        except asyncio.CancelledError:
            cancelled.append(model)
            raise
        return httpx.Response(200, json=BODY)

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(ProviderTransportError) as exc:
                await provider(client).complete(request())
            assert exc.value.reason == 'timeout'

    asyncio.run(asyncio.wait_for(scenario(), timeout=2))
    assert seen == [PRIMARY, FALLBACK]
    assert cancelled == [PRIMARY, FALLBACK]


@pytest.mark.parametrize('fallback', ['', PRIMARY])
def test_no_usable_fallback_keeps_primary_full_budget(fallback):
    seen = []

    async def handler(req):
        seen.append(json.loads(req.content)['model'])
        await asyncio.sleep(0.24)  # Longer than 2/3 of the 0.3 s total.
        return httpx.Response(200, json=BODY)

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            assert (await provider(client, fallback=fallback).complete(request())).text == 'ok'

    asyncio.run(asyncio.wait_for(scenario(), timeout=2))
    assert seen == [PRIMARY]


def test_successful_primary_never_calls_fallback():
    seen = []

    async def handler(req):
        seen.append(json.loads(req.content)['model'])
        return httpx.Response(200, json={**BODY, 'model': PRIMARY})

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            assert (await provider(client).complete(request())).model == PRIMARY

    asyncio.run(asyncio.wait_for(scenario(), timeout=2))
    assert seen == [PRIMARY]


def test_caller_cancellation_is_not_reinterpreted_as_primary_failure():
    started = asyncio.Event()
    seen = []

    async def handler(req):
        seen.append(json.loads(req.content)['model'])
        started.set()
        await asyncio.sleep(5)
        return httpx.Response(200, json=BODY)

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            job = asyncio.create_task(provider(client).complete(request()))
            await started.wait()
            job.cancel()
            with pytest.raises(asyncio.CancelledError):
                await job

    asyncio.run(asyncio.wait_for(scenario(), timeout=2))
    assert seen == [PRIMARY]


def test_fast_primary_failure_leaves_all_remaining_time_for_fallback():
    seen = []

    async def handler(req):
        model = json.loads(req.content)['model']
        seen.append(model)
        if model == PRIMARY:
            return httpx.Response(403, json={'error': 'isolated primary rejection'})
        await asyncio.sleep(0.24)  # More than the reserved last third alone.
        return httpx.Response(200, json={**BODY, 'model': model})

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            assert (await provider(client).complete(request())).model == FALLBACK

    asyncio.run(asyncio.wait_for(scenario(), timeout=2))
    assert seen == [PRIMARY, FALLBACK]



def test_valid_slow_primary_survives_backup_failure_without_restart():
    seen = []
    cancelled = []

    async def handler(req):
        model = json.loads(req.content)['model']
        seen.append(model)
        if model == FALLBACK:
            return httpx.Response(403, json={'error': 'backup unavailable'})
        try:
            await asyncio.sleep(0.25)  # After hedge at 0.2, before total 0.3.
        except asyncio.CancelledError:
            cancelled.append(model)
            raise
        return httpx.Response(200, json={**BODY, 'model': model})

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            assert (await provider(client, retries=0).complete(request())).model == PRIMARY

    asyncio.run(asyncio.wait_for(scenario(), timeout=2))
    assert seen == [PRIMARY, FALLBACK]
    assert cancelled == []


def test_valid_slow_primary_wins_and_cancels_hung_backup():
    seen = []
    cancelled = []

    async def handler(req):
        model = json.loads(req.content)['model']
        seen.append(model)
        try:
            await asyncio.sleep(0.25 if model == PRIMARY else 5)
        except asyncio.CancelledError:
            cancelled.append(model)
            raise
        return httpx.Response(200, json={**BODY, 'model': model})

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            assert (await provider(client).complete(request())).model == PRIMARY

    asyncio.run(asyncio.wait_for(scenario(), timeout=2))
    assert seen == [PRIMARY, FALLBACK]
    assert cancelled == [FALLBACK]


def test_caller_cancellation_after_hedge_collects_both_generations():
    backup_started = asyncio.Event()
    cancelled = []

    async def handler(req):
        model = json.loads(req.content)['model']
        if model == FALLBACK:
            backup_started.set()
        try:
            await asyncio.sleep(5)
        except asyncio.CancelledError:
            cancelled.append(model)
            raise
        return httpx.Response(200, json=BODY)

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            job = asyncio.create_task(provider(client).complete(request()))
            await backup_started.wait()
            job.cancel()
            with pytest.raises(asyncio.CancelledError):
                await job

    asyncio.run(asyncio.wait_for(scenario(), timeout=2))
    assert sorted(cancelled) == sorted([PRIMARY, FALLBACK])


@pytest.mark.parametrize('slow_primary', [True, False])
def test_real_shadow_tracer_keeps_fallback_reason_and_cancelled_generation(slow_primary):
    from app.services import tracing

    sink = []

    class Span:
        def start_observation(self, **kwargs):
            sink.append(kwargs)
            return self

        def end(self):
            pass

    class Client:
        def create_trace_id(self):
            return 'isolated-trace'

        def start_observation(self, **kwargs):
            return Span()

    async def handler(req):
        model = json.loads(req.content)['model']
        if model == PRIMARY:
            if slow_primary:
                await asyncio.sleep(5)
            else:
                return httpx.Response(403, json={'error': 'private upstream body'})
        return httpx.Response(200, json={**BODY, 'model': model})

    async def scenario():
        tracer = tracing.ShadowTracer(
            client_factory=Client, workflow_name='test', run_id=None,
            metadata={}, active=True,
        )
        token = tracing.set_current_tracer(tracer)
        try:
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                req = LLMRequest(messages=[Message('user', 'PRIVATE PROMPT')], cache=False,
                                 metadata={'prompt': 'PRIVATE PROMPT', 'completion': 'PRIVATE ANSWER'})
                assert (await provider(client, retries=0).complete(req)).model == FALLBACK
        finally:
            tracing.reset_current_tracer(token)

    asyncio.run(asyncio.wait_for(scenario(), timeout=2))
    generations = [item for item in sink if item.get('as_type') == 'generation']
    assert len(generations) == 2
    backup = next(item for item in generations if item['model'] == FALLBACK)
    assert backup['metadata']['fallback_from'] == PRIMARY
    if slow_primary:
        assert backup['metadata']['fallback_trigger'] == 'primary_slow'
        primary = next(item for item in generations if item['model'] == PRIMARY)
        assert primary['metadata']['status'] == 'cancelled'
        assert primary['status_message'] is None
        assert primary['level'] == 'DEFAULT'
        assert 'duration_ms' in primary['metadata']
    else:
        assert backup['metadata']['primary_error'] == 'ProviderHTTPError'
    assert 'PRIVATE PROMPT' not in repr(sink)
    assert 'PRIVATE ANSWER' not in repr(sink)
    assert 'private upstream body' not in repr(sink)
    assert tracing.sanitize_metadata({'prompt': 'x', 'content': 'y'}) == {}


def test_fallback_aliased_to_primary_by_override_is_not_called():
    seen = []

    async def handler(req):
        seen.append(json.loads(req.content)['model'])
        return httpx.Response(429, json={'error': {'message': 'FreeTierLimitError'}})

    def build(client, overrides):
        return create_llm_provider(Settings(
            _env_file=None,
            opencode_go_api_key='test-secret',
            opencode_go_base_url='https://opencode.test/v1',
            opencode_go_model=PRIMARY,
            opencode_go_fallback_model=FALLBACK,
            llm_model_overrides=overrides,
            llm_total_timeout_seconds=5,
            llm_timeout_seconds=5,
            llm_max_retries=0,
        ), client=client)

    async def scenario(overrides):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(Exception):
                await build(client, overrides).complete(request())

    asyncio.run(scenario({FALLBACK: PRIMARY}))
    assert seen == [PRIMARY]
    seen.clear()
    asyncio.run(scenario({}))
    assert seen == [PRIMARY, FALLBACK]
