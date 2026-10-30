"""Regression tests for docker-compose.prod.yml deployment safety."""

import re
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


def test_prod_chat_uses_the_go_subscription_and_backups_are_auto():
    # Hallazgo M1: respaldos en modo auto (solo con clave + plan gratuito
    # confirmado); sin clave siguen apagados. Ver test_llm_degraded_mode.py.
    compose = _load_compose()
    env = _service_env(compose, "backend")
    assert env.get("CHAT_GO_SUBSCRIPTION_ENABLED") == "${CHAT_GO_SUBSCRIPTION_ENABLED:-true}"
    assert env.get("GROQ_CHAT_FALLBACK_ENABLED") == "${GROQ_CHAT_FALLBACK_ENABLED:-auto}"
    assert env.get("GEMINI_CHAT_FALLBACK_ENABLED") == "${GEMINI_CHAT_FALLBACK_ENABLED:-auto}"
    assert env.get("OPENROUTER_API_KEY") == "${OPENROUTER_API_KEY:-}"


APP_SERVICES = (
    "backend",
    "worker",
    "worker-thesis",
    "worker-kpis",
    "worker-alerts",
    "worker-gdelt",
    "worker-knowledge",
    "worker-official-closes",
    "worker-dca-manual",
    "scheduler",
)


def _memory_mib(value: str | int) -> int:
    text = str(value).strip().upper()
    match = re.fullmatch(r"(\d+(?:\.\d+)?)([MG])", text)
    assert match, f"unidad de memoria no reconocida: {value!r}"
    amount = float(match.group(1))
    return int(amount * 1024) if match.group(2) == "G" else int(amount)


def test_every_app_process_runs_with_app_env_production():
    """Un worker sin APP_ENV se saltaba las validaciones de produccion."""
    compose = _load_compose()
    for service in APP_SERVICES:
        env = _service_env(compose, service)
        assert env.get("APP_ENV") == "production", service


def test_every_app_process_receives_the_required_auth_secret():
    """APP_ENV=production exige RESEARCH_AUTH_SECRET: sin el, el worker no arranca."""
    compose = _load_compose()
    for service in APP_SERVICES:
        env = _service_env(compose, service)
        assert env.get("RESEARCH_AUTH_REQUIRED") == "true", service
        assert "RESEARCH_AUTH_SECRET" in env, service
        assert ":?" in env["RESEARCH_AUTH_SECRET"], service


def test_scheduler_receives_retention_and_storage_configuration():
    """El job privacy_retention borra originales/chunks/vectores: sin MinIO,
    Qdrant y RETENTION_* arrancaba degradado y no purgaba nada."""
    compose = _load_compose()
    env = _service_env(compose, "scheduler")
    assert env.get("RETENTION_JOB_ENABLED") == "${RETENTION_JOB_ENABLED:-false}"
    assert env.get("RETENTION_DRY_RUN") == "${RETENTION_DRY_RUN:-true}"
    assert env.get("RETENTION_BATCH_LIMIT") == "${RETENTION_BATCH_LIMIT:-500}"
    assert env.get("FINANCIAL_DOCUMENT_RETENTION_DAYS") == (
        "${FINANCIAL_DOCUMENT_RETENTION_DAYS:-2555}"
    )
    assert env.get("CHAT_TELEMETRY_RETENTION_DAYS") == (
        "${CHAT_TELEMETRY_RETENTION_DAYS:-90}"
    )
    assert env.get("MINIO_ENDPOINT") == "${OBJECT_STORAGE_ENDPOINT:-minio:9000}"
    assert env.get("MINIO_BUCKET") == "research"
    assert env.get("QDRANT_URL") == "http://qdrant:6333"


def test_memory_limits_fit_the_12gb_vm():
    """La suma anterior (~23,5 GiB) hacia OOM en una VM de 12 GB."""
    compose = _load_compose()
    total = 0
    for name, service in compose["services"].items():
        limit = service.get("deploy", {}).get("resources", {}).get("limits", {})
        assert "memory" in limit, f"{name} sin limite de memoria"
        total += _memory_mib(limit["memory"])
    assert total <= 10240, f"los limites suman {total} MiB (> 10 GiB)"


def test_every_service_has_cpu_limits_and_rotated_logs():
    compose = _load_compose()
    for name, service in compose["services"].items():
        limits = service.get("deploy", {}).get("resources", {}).get("limits", {})
        assert "cpus" in limits, f"{name} sin limite de cpus"
        logging = service.get("logging")
        assert logging and logging.get("driver") == "json-file", f"{name} sin logging JSON"
        assert logging["options"]["max-size"] and logging["options"]["max-file"], name


def test_prod_does_not_run_the_vercel_frontend():
    compose = _load_compose()
    assert "frontend" not in compose["services"]


def test_workers_run_the_image_code_not_a_source_bind_mount():
    """Dockerfile.prod already COPYs data-engine/; the prod bind mount let a
    host checkout override the image and masked a broken build."""
    compose = _load_compose()
    for service in ("worker-thesis", "worker-kpis", "worker-alerts", "worker-gdelt", "worker-knowledge"):
        volumes = compose["services"][service].get("volumes", [])
        assert not any("data-engine" in str(volume) for volume in volumes), service


def test_postgres_accepts_the_pool_budget_and_redis_has_headroom():
    compose = _load_compose()
    postgres_cmd = " ".join(compose["services"]["postgres"]["command"])
    assert "max_connections=200" in postgres_cmd
    redis_cmd = " ".join(compose["services"]["redis"]["command"])
    assert "768mb" in redis_cmd
    backend_env = _service_env(compose, "backend")
    assert backend_env.get("DB_POOL_SIZE") == "${DB_POOL_SIZE:-20}"
    assert backend_env.get("DB_MAX_OVERFLOW") == "${DB_MAX_OVERFLOW:-10}"
    for service in APP_SERVICES[1:]:
        env = _service_env(compose, service)
        assert env.get("DB_POOL_SIZE") == "${WORKER_DB_POOL_SIZE:-4}", service
        assert env.get("DB_MAX_OVERFLOW") == "${WORKER_DB_MAX_OVERFLOW:-2}", service


def test_knowledge_rag_collection_matches_the_1024_dim_model():
    compose = _load_compose()
    expected = "${KNOWLEDGE_RAG_COLLECTION:-knowledge_rag_v2}"
    assert _service_env(compose, "backend").get("KNOWLEDGE_RAG_COLLECTION") == expected
    assert _service_env(compose, "worker-knowledge").get("KNOWLEDGE_RAG_COLLECTION") == expected
    raw = COMPOSE_PATH.read_text()
    assert "knowledge_rag_v1" not in raw


def test_caddy_bind_is_configurable_not_hardcoded():
    compose = _load_compose()
    ports = [str(port) for port in compose["services"]["caddy"]["ports"]]
    assert all("${BIND_IP:-0.0.0.0}" in port for port in ports), ports


def test_prod_requires_a_real_sec_user_agent():
    """El default .local no es contactable y la SEC responde 403 sin contacto."""
    compose = _load_compose()
    env = _service_env(compose, "scheduler")
    assert env.get("SEC_USER_AGENT", "").startswith("${SEC_USER_AGENT:?"), env.get(
        "SEC_USER_AGENT"
    )


def test_data_services_explicitly_reset_inherited_host_ports():
    """Omitting ports does not remove mappings from a merged base file."""
    compose = _load_compose()
    source = COMPOSE_PATH.read_text()
    for name in ("postgres", "redis", "minio"):
        assert compose["services"][name]["ports"] == []
        section = re.split(r"\n  [A-Za-z_][\w-]*:", source.split(f"\n  {name}:\n", 1)[1], maxsplit=1)[0]
        assert "ports: !reset []" in section
