#!/bin/sh
set -eu
cd "$(dirname "$0")/../data-engine"
APP_ENV=test .venv/bin/pytest \
tests/test_hy4_default_routing.py tests/test_hy4_guard.py tests/test_llm_free_only_gate.py tests/test_llm_provider.py tests/test_llm_cascade.py tests/test_chat_free_fallback.py tests/test_chat_go_subscription_optin.py tests/test_background_fallback.py tests/test_debate_free_failover.py tests/test_gemini_interactive_fallback.py tests/test_thesis_go_provider.py tests/test_llm_respaldo_solo_si_falla.py tests/test_llm_background_quota_breaker.py tests/test_llm_free_tier_breaker.py tests/test_tenant_llm_invalid_settings.py tests/test_tenant_llm_unknown_provider.py \
--cov=app.llm.chat_provider --cov=app.llm.factory --cov=app.llm.free_interactive --cov=app.llm.free_only --cov=app.llm.hy4 --cov=app.llm.thesis_go --cov-report=term-missing --cov-report=json:/tmp/hy4-defaults-coverage.json --cov-fail-under=0 -q --disable-warnings
