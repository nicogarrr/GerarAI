"""Regression tests for docker-compose.prod.yml deployment safety."""

from pathlib import Path

import yaml


class _ComposeLoader(yaml.SafeLoader):
    """SafeLoader que tolera los tags de merge de Compose (!override/!reset).

    Los tags son sintaxis de docker compose, no errores de YAML; los tests
    solo afirman sobre la estructura de servicios resultante.
    """


def _compose_unknown_tag(loader, tag_suffix, node):
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node)
    return loader.construct_scalar(node)


_ComposeLoader.add_multi_constructor("!", _compose_unknown_tag)


COMPOSE_PATH = Path(__file__).resolve().parents[2] / "docker-compose.prod.yml"


def _load_compose() -> dict:
    return yaml.load(COMPOSE_PATH.read_text(), Loader=_ComposeLoader)


def _service_env(compose: dict, service: str) -> dict[str, str]:
    """Normalize a compose service environment (list or mapping form)."""
    env = compose["services"][service].get("environment", [])
    if isinstance(env, dict):
        return {str(k): str(v) for k, v in env.items()}
    result: dict[str, str] = {}
    for entry in env:
        key, _, value = str(entry).partition("=")
        result[key] = value
    return result


def test_backend_does_not_duplicate_the_standalone_scheduler():
    """The backend embeds a scheduler when WORKERS_ENABLED=true (the default).

    docker-compose.prod.yml also runs a dedicated scheduler service, so the
    backend must set WORKERS_ENABLED=false or every periodic job fires twice.
    """
    compose = _load_compose()
    assert "scheduler" in compose["services"], "expected a standalone scheduler service"
    backend_env = _service_env(compose, "backend")
    assert backend_env.get("WORKERS_ENABLED") == "false", (
        "backend service must disable its embedded scheduler "
        "(WORKERS_ENABLED=false) because cavaai-scheduler runs it"
    )


def test_prod_backend_forces_signed_research_identity():
    compose = _load_compose()
    backend_env = _service_env(compose, "backend")
    assert backend_env.get("APP_ENV") == "production"
    assert backend_env.get("RESEARCH_AUTH_REQUIRED") == "true"


def test_prod_llm_defaults_match_the_owner_approved_go_model():
    compose = _load_compose()
    for service in ("backend", "worker", "worker-thesis", "worker-kpis"):
        env = _service_env(compose, service)
        assert env.get("LLM_PROVIDER") == "${LLM_PROVIDER:-opencode-go}", service
        assert env.get("CHAT_TOTAL_TIMEOUT_SECONDS") == "${CHAT_TOTAL_TIMEOUT_SECONDS:-45}", service
        assert env.get("OPENCODE_GO_CHAT_REASONING_EFFORT") == (
            "${OPENCODE_GO_CHAT_REASONING_EFFORT:-high}"
        ), service
        assert env.get("OPENCODE_GO_BASE_URL") == (
            "${OPENCODE_GO_BASE_URL:-https://opencode.ai/zen/go/v1}"
        ), service
        assert env.get("OPENCODE_GO_MODEL") == (
            "${OPENCODE_GO_MODEL:-deepseek-v4.1-flash}"
        ), service
        assert env.get("OPENCODE_GO_FALLBACK_MODEL") == "${OPENCODE_GO_FALLBACK_MODEL:-}", service


def test_prod_chat_uses_the_go_subscription_and_backups_stay_off():
    compose = _load_compose()
    env = _service_env(compose, "backend")
    assert env.get("CHAT_GO_SUBSCRIPTION_ENABLED") == "${CHAT_GO_SUBSCRIPTION_ENABLED:-true}"
    assert env.get("GROQ_CHAT_FALLBACK_ENABLED") == "${GROQ_CHAT_FALLBACK_ENABLED:-false}"
    assert env.get("GEMINI_CHAT_FALLBACK_ENABLED") == "${GEMINI_CHAT_FALLBACK_ENABLED:-false}"
    assert "OPENROUTER_API_KEY=${OPENROUTER_API_KEY:-}" in compose["services"]["backend"]["environment"]
