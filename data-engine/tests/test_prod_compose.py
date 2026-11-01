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
    "worker-prices",
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


def test_memory_limits_fit_the_24gb_vm_with_host_reserve():
    """24 GB host verified 2026-10-30; reserve at least 8 GiB outside this stack.

    Old 10 GiB ceiling described the replaced 12 GB host and contradicted the
    documented 24 GB deployment. Keep a bounded 16 GiB stack ceiling rather
    than deriving the budget from the configured limits themselves.
    """
    compose = _load_compose()
    total = 0
    for name, service in compose["services"].items():
        limit = service.get("deploy", {}).get("resources", {}).get("limits", {})
        assert "memory" in limit, f"{name} sin limite de memoria"
        total += _memory_mib(limit["memory"])
    assert total <= 16384, f"los limites suman {total} MiB (> 16 GiB; host reserve < 8 GiB)"


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
        # El carril default (4 hilos) sube el defecto del mismo knob a 8; ver
        # test_default_worker_db_pool_covers_its_threads.
        expected_pool = (
            "${WORKER_DB_POOL_SIZE:-8}"
            if service == "worker"
            else "${WORKER_DB_POOL_SIZE:-4}"
        )
        assert env.get("DB_POOL_SIZE") == expected_pool, service
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


def test_prod_redis_requires_auth_and_all_clients_switch_together():
    compose = _load_compose()
    redis = compose["services"]["redis"]
    assert "${REDIS_PASSWORD:?" in _service_env(compose, "redis")["REDIS_PASSWORD"]
    command = "\n".join(redis["command"])
    assert "requirepass %s" in command
    assert "umask 077" in command
    assert "exec redis-server /tmp/redis-auth.conf" in command
    assert "--requirepass" not in command
    health = " ".join(redis["healthcheck"]["test"])
    assert "REDISCLI_AUTH" in health and "grep -qx PONG" in health
    for service in APP_SERVICES:
        url = _service_env(compose, service).get("REDIS_URL", "")
        assert url.startswith("redis://:${REDIS_PASSWORD:?") and url.endswith("@redis:6379/0"), service

def _command_parts(compose: dict, service: str) -> list[str]:
    command = compose["services"][service]["command"]
    return [str(part) for part in command]


def test_default_worker_scales_io_bound_threads_via_env():
    """Cola default: 8.709 pendientes, edad p50 39 h, CPU del worker 0,17 %.

    El cuello de botella es espera de E/S (HTTP externo), no CPU: un solo
    knob WORKER_THREADS (defecto 4 aqui) permite el despliegue gradual
    2 -> 4 -> 8 sin editar el fichero.
    """
    compose = _load_compose()
    parts = _command_parts(compose, "worker")
    threads = parts[parts.index("--threads") + 1]
    assert threads == "${WORKER_THREADS:-4}", parts


def test_prices_queue_has_a_dedicated_worker():
    """prices (frescura intradia de 15 min) esperaba detras del backlog de
    default en el mismo hilo: pasa a carril dedicado con el mismo knob de
    hilos (defecto 2), patron official-closes/dca-manual."""
    compose = _load_compose()
    default_parts = _command_parts(compose, "worker")
    assert default_parts[default_parts.index("-Q") + 1 :] == ["default"], default_parts
    assert "worker-prices" in compose["services"], "falta el carril dedicado de prices"
    prices_parts = _command_parts(compose, "worker-prices")
    assert prices_parts[prices_parts.index("-Q") + 1 :] == ["prices"], prices_parts
    threads = prices_parts[prices_parts.index("--threads") + 1]
    assert threads == "${WORKER_THREADS:-2}", prices_parts


def test_default_worker_db_pool_covers_its_threads():
    """4 hilos comparten el pool del proceso: 4+2 conexiones los serializaban;
    el carril default sube a 8+2 con el mismo knob WORKER_DB_POOL_SIZE."""
    compose = _load_compose()
    env = _service_env(compose, "worker")
    assert env.get("DB_POOL_SIZE") == "${WORKER_DB_POOL_SIZE:-8}"

