"""Hermetic tests: explicit model costs and env-overridable default model.

- Zero costs are only legal with cost_basis="unknown" (never silent "free").
- The default OpenCode Go model resolves from OPENCODE_GO_MODEL with fallback.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.core.config import Settings
from app.llm import create_llm_provider
from app.llm.model_aliases import (
    DEFAULT_MODEL_ENV_VAR,
    DEFAULT_MODEL_FALLBACK,
    MODEL_ALIASES,
    ModelAlias,
    default_model_from_env,
)


def _alias(**overrides) -> ModelAlias:
    base = {
        "internal_alias": "test-model",
        "provider": "opencode-go",
        "provider_model_id": "test-model",
        "enabled": True,
        "context_window": 1024,
        "input_cost": Decimal("0"),
        "output_cost": Decimal("0"),
        "supported_capabilities": frozenset({"text"}),
    }
    base.update(overrides)
    return ModelAlias(**base)


def test_registered_alias_costs_are_explicitly_unknown_not_free():
    for model in ("deepseek-v4.1-flash", "deepseek-v4.1-flash-free"):
        alias = MODEL_ALIASES.get(model)
        assert alias is not None
        assert alias.cost_basis == "unknown"
        assert not alias.has_known_costs


def test_list_price_basis_requires_positive_costs():
    with pytest.raises(ValueError, match="requires positive costs"):
        _alias(cost_basis="list_price")
    priced = _alias(
        cost_basis="list_price",
        input_cost=Decimal("0.10"),
        output_cost=Decimal("0.40"),
    )
    assert priced.has_known_costs


def test_unknown_cost_basis_is_rejected():
    with pytest.raises(ValueError, match="cost_basis"):
        _alias(cost_basis="subscription")


def test_default_model_from_env(monkeypatch):
    monkeypatch.delenv(DEFAULT_MODEL_ENV_VAR, raising=False)
    assert default_model_from_env() == DEFAULT_MODEL_FALLBACK
    monkeypatch.setenv(DEFAULT_MODEL_ENV_VAR, "qwen3.7-plus")
    assert default_model_from_env() == "qwen3.7-plus"
    monkeypatch.setenv(DEFAULT_MODEL_ENV_VAR, "   ")
    assert default_model_from_env() == DEFAULT_MODEL_FALLBACK


def test_settings_default_model_overridable_via_env(monkeypatch):
    monkeypatch.delenv(DEFAULT_MODEL_ENV_VAR, raising=False)
    assert (
        Settings(_env_file=None, opencode_go_api_key="k").opencode_go_model
        == DEFAULT_MODEL_FALLBACK
    )
    monkeypatch.setenv(DEFAULT_MODEL_ENV_VAR, "qwen3.7-plus")
    settings = Settings(_env_file=None, opencode_go_api_key="k")
    assert settings.opencode_go_model == "qwen3.7-plus"
    provider = create_llm_provider(settings)
    assert provider.model_router.default_model == "qwen3.7-plus"
