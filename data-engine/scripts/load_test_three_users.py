"""Arnes de carga reproducible para tres usuarios/tenants simultaneos.

Por defecto solo habla con loopback: cualquier URL remota exige --allow-remote.
El arnes firma cada peticion con la identidad de su tenant, mide latencias y
errores por escenario y verifica que la sesion siga tenant-scoped. No modifica
datos de negocio: solo GETs y un POST /api/chat corto (opcional).
"""

from __future__ import annotations

import argparse
import asyncio
import ipaddress
import json
import math
import os
import re
import sys
import time
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
from research_auth import load_secret, signed_headers

DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_TENANT_PREFIX = "cavaai-loadtest"
DEFAULT_PORTFOLIO_PATH = "/api/portfolio/summary"
CHAT_PROMPT = "Resume en una frase el estado de mi cartera."
TENANT_KEYS = frozenset({"tenant", "tenant_id", "tenant_external_id"})
STATUS_KEYS = ("2xx", "3xx", "4xx", "5xx")
ERROR_KEYS = ("connection_error", "timeout", "http_error", "unexpected_error")


@dataclass(frozen=True)
class Identity:
    label: str
    tenant: str
    user: str


@dataclass(frozen=True)
class Scenario:
    name: str
    method: str
    path: str
    body: bytes | None = None


@dataclass(frozen=True)
class LoadConfig:
    base_url: str
    rounds: int
    timeout_s: float
    p95_ms: float
    chat_p95_ms: float
    skip_llm: bool


@dataclass
class Sample:
    scenario: str
    tenant: str
    latency_ms: float
    status_code: int | None
    outcome: str
    error: str | None = None
    fallback_reason: str | None = None


@dataclass
class RequestResult:
    sample: Sample
    payload: Any = None


@dataclass
class ProbeOutcome:
    llm_configured: bool | None
    issues: list[str]
    notes: list[str]


def is_loopback_host(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def validate_base_url(raw: str, *, allow_remote: bool) -> str:
    parts = urlsplit(raw.strip())
    if parts.scheme not in {"http", "https"}:
        raise ValueError("--base-url debe usar http:// o https://")
    if not parts.hostname:
        raise ValueError("--base-url no incluye host")
    if parts.query or parts.fragment:
        raise ValueError("--base-url no admite query ni fragmento")
    if parts.path.rstrip("/"):
        raise ValueError("--base-url debe apuntar a la raiz, sin ruta")
    if not is_loopback_host(parts.hostname) and not allow_remote:
        raise ValueError(
            f"--base-url {parts.netloc} no es loopback; usa --allow-remote solo contra un stack de prueba"
        )
    return f"{parts.scheme}://{parts.netloc}"


def validate_endpoint_path(path: str) -> str:
    parts = urlsplit(path)
    if parts.scheme or parts.netloc or not parts.path.startswith("/"):
        raise ValueError("--portfolio-path debe ser una ruta del backend que empiece por /")
    return path


def build_identities(prefix: str) -> list[Identity]:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,40}", prefix):
        raise ValueError(
            "--tenant-prefix debe empezar por letra o numero y usar solo A-Z, a-z, 0-9, _, . o -"
        )
    return [
        Identity(f"usuario-{index}", f"{prefix}-u{index}", f"{prefix}-u{index}-user") for index in range(1, 4)
    ]


# Perfil ligero de solo lectura para los endpoints que usan Inicio y Watchlist,
# incluidos los historicamente lentos (metric-coverage, data-health). Pensado
# para el barrido de rendimiento: GETs idempotentes, sin escrituras ni LLM.
INICIO_WATCHLIST_SCENARIOS = [
    Scenario("watchlist_list", "GET", "/api/watchlist"),
    Scenario("watchlist_monitor", "GET", "/api/watchlist/monitor?tickers=MSFT,NVDA,ASTS"),
    Scenario("calendar_earnings", "GET", "/api/calendar/earnings"),
    Scenario("metric_coverage", "GET", "/api/screeners/metric-coverage"),
    Scenario("data_health", "GET", "/api/data-health"),
]


def build_scenarios(
    *, include_chat: bool, portfolio_path: str, include_inicio_watchlist: bool = False
) -> list[Scenario]:
    scenarios = [
        Scenario("health_live", "GET", "/health/live"),
        Scenario("thesis_tickers", "GET", "/api/companies/thesis-tickers"),
        Scenario("portfolio_summary", "GET", validate_endpoint_path(portfolio_path)),
        Scenario("screeners_real", "GET", "/api/screeners/real?limit=5"),
    ]
    if include_inicio_watchlist:
        scenarios.extend(INICIO_WATCHLIST_SCENARIOS)
    if include_chat:
        body = json.dumps(
            {"question": CHAT_PROMPT, "scope": "portfolio"},
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        scenarios.append(Scenario("chat", "POST", "/api/chat", body))
    return scenarios


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Carga reproducible con 3 usuarios/tenants contra un stack LOCAL de GerarAI."
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=30.0, dest="timeout_s")
    parser.add_argument("--p95-ms", type=float, default=2000.0)
    parser.add_argument("--chat-p95-ms", type=float, default=30000.0)
    parser.add_argument("--skip-llm", action="store_true")
    parser.add_argument(
        "--inicio-watchlist",
        action="store_true",
        help="suma el perfil ligero de solo lectura de Inicio/Watchlist (watchlist, monitor, earnings, metric-coverage, data-health)",
    )
    parser.add_argument("--allow-remote", action="store_true")
    parser.add_argument("--json-out", type=Path, default=None)
    parser.add_argument("--env-file", type=Path, default=None)
    parser.add_argument("--tenant-prefix", default=DEFAULT_TENANT_PREFIX)
    parser.add_argument("--portfolio-path", default=DEFAULT_PORTFOLIO_PATH)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if args.rounds < 1:
        parser.error("--rounds debe ser >= 1")
    if args.timeout_s <= 0:
        parser.error("--timeout debe ser > 0")
    if args.p95_ms <= 0:
        parser.error("--p95-ms debe ser > 0")
    if args.chat_p95_ms <= 0:
        parser.error("--chat-p95-ms debe ser > 0")
    return args


def resolve_secret(env_file: Path | None) -> str:
    from_env = os.environ.get("RESEARCH_AUTH_SECRET", "").strip()
    if from_env:
        if len(from_env) < 32:
            raise RuntimeError("RESEARCH_AUTH_SECRET debe tener al menos 32 caracteres")
        return from_env

    candidates: list[Path] = []
    if env_file is not None:
        candidates.append(env_file)
    else:
        candidates.append(Path.cwd() / ".env")
        candidates.append(Path(__file__).resolve().parents[2] / ".env")

    for candidate in dict.fromkeys(candidates):
        if not candidate.is_file():
            continue
        try:
            secret = load_secret(str(candidate)).strip()
        except RuntimeError:
            continue
        if len(secret) < 32:
            raise RuntimeError(f"{candidate} contiene un RESEARCH_AUTH_SECRET de menos de 32 caracteres")
        return secret

    if env_file is not None:
        raise RuntimeError(f"{env_file} no existe o no contiene RESEARCH_AUTH_SECRET")
    raise RuntimeError("RESEARCH_AUTH_SECRET no definido: exportalo o usa --env-file con el .env del backend")


def percentile(values: Sequence[float], pct: float) -> float | None:
    if not 0 < pct <= 100:
        raise ValueError("el percentil debe estar entre 0 y 100")
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(pct / 100.0 * len(ordered)))
    return ordered[rank - 1]


def classify_status(status_code: int) -> str:
    return f"{status_code // 100}xx"


def classify_exception(exc: BaseException) -> str:
    if isinstance(exc, httpx.TimeoutException):
        return "timeout"
    if isinstance(exc, httpx.TransportError):
        return "connection_error"
    if isinstance(exc, httpx.HTTPError):
        return "http_error"
    return "unexpected_error"


def inspect_tenant_payload(payload: Any, *, expected_tenant: str, other_tenants: Sequence[str]) -> list[str]:
    issues: list[str] = []

    def walk(value: Any, trail: str) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                key_text = str(key)
                if (
                    key_text.lower() in TENANT_KEYS
                    and isinstance(item, str)
                    and item
                    and item != expected_tenant
                ):
                    issues.append(
                        f"{expected_tenant} recibio {trail + '.' if trail else ''}{key_text}={item}"
                    )
                walk(item, f"{trail}.{key_text}" if trail else key_text)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                walk(item, f"{trail}[{index}]")

    walk(payload, "")
    try:
        text = json.dumps(payload, ensure_ascii=False)
    except (TypeError, ValueError):
        text = ""
    for other in other_tenants:
        if other != expected_tenant and other and other in text:
            issues.append(f"{expected_tenant} recibio una respuesta que menciona {other}")
    return list(dict.fromkeys(issues))


def _problem(sample: Sample) -> str:
    if sample.error:
        return f"{sample.outcome}: {sample.error}"
    return f"HTTP {sample.status_code}"


async def fetch(
    client: httpx.AsyncClient,
    identity: Identity,
    scenario: Scenario,
    *,
    secret: str,
    timeout_s: float,
) -> RequestResult:
    body = scenario.body or b""
    signed_path = urlsplit(scenario.path).path
    headers = signed_headers(
        secret,
        identity.tenant,
        identity.user,
        method=scenario.method,
        path=signed_path,
        body=body,
    )
    headers["Accept"] = "application/json"
    if body:
        headers["Content-Type"] = "application/json"
    started = time.perf_counter()
    try:
        response = await client.request(
            scenario.method,
            scenario.path,
            content=body or None,
            headers=headers,
            timeout=timeout_s,
        )
    except Exception as exc:
        latency_ms = (time.perf_counter() - started) * 1000.0
        return RequestResult(
            Sample(
                scenario=scenario.name,
                tenant=identity.tenant,
                latency_ms=latency_ms,
                status_code=None,
                outcome=classify_exception(exc),
                error=f"{type(exc).__name__}: {exc}",
            )
        )

    latency_ms = (time.perf_counter() - started) * 1000.0
    status_code = response.status_code
    try:
        payload: Any = response.json()
    except ValueError:
        payload = None
    fallback_reason = None
    if scenario.name == "chat" and isinstance(payload, dict):
        trace = payload.get("llm_trace")
        if isinstance(trace, dict) and trace.get("fallback_reason"):
            fallback_reason = str(trace["fallback_reason"])[:80]
    return RequestResult(
        Sample(
            scenario=scenario.name,
            tenant=identity.tenant,
            latency_ms=latency_ms,
            status_code=status_code,
            outcome=classify_status(status_code),
            fallback_reason=fallback_reason,
        ),
        payload,
    )


async def probe_identities(
    client: httpx.AsyncClient,
    *,
    secret: str,
    identities: Sequence[Identity],
    timeout_s: float,
) -> ProbeOutcome:
    scenario = Scenario("settings_probe", "GET", "/api/settings")
    results = await asyncio.gather(
        *(fetch(client, identity, scenario, secret=secret, timeout_s=timeout_s) for identity in identities)
    )
    issues: list[str] = []
    notes: list[str] = []
    configured_values: list[bool] = []
    all_tenants = [identity.tenant for identity in identities]

    for identity, result in zip(identities, results, strict=True):
        sample = result.sample
        payload = result.payload
        if sample.status_code in (401, 403):
            issues.append(
                f"auth rechazada en /api/settings para {identity.tenant}: "
                "revisa RESEARCH_AUTH_SECRET, reloj y APP_ENV"
            )
        elif sample.status_code != 200 or not isinstance(payload, dict):
            issues.append(f"no se pudo verificar aislamiento para {identity.tenant}: {_problem(sample)}")
        else:
            budget = payload.get("budget")
            scoped = budget.get("tenant_scoped") if isinstance(budget, dict) else None
            if scoped is not True:
                issues.append(
                    f"aislamiento no verificado para {identity.tenant}: "
                    f"/api/settings devolvio budget.tenant_scoped={scoped!r}"
                )
            issues.extend(
                inspect_tenant_payload(
                    payload,
                    expected_tenant=identity.tenant,
                    other_tenants=all_tenants,
                )
            )
            llm = payload.get("llm")
            configured = llm.get("configured") if isinstance(llm, dict) else None
            if isinstance(configured, bool):
                configured_values.append(configured)

    llm_configured: bool | None = None
    if configured_values:
        llm_configured = all(configured_values)
        if len(set(configured_values)) > 1:
            notes.append("las identidades no coinciden en llm.configured; se usa el criterio conservador")
    return ProbeOutcome(llm_configured=llm_configured, issues=issues, notes=notes)


async def run_rounds(
    client: httpx.AsyncClient,
    *,
    secret: str,
    identities: Sequence[Identity],
    scenarios: Sequence[Scenario],
    rounds: int,
    timeout_s: float,
) -> list[RequestResult]:
    results: list[RequestResult] = []
    for _ in range(rounds):
        batch = await asyncio.gather(
            *(
                fetch(client, identity, scenario, secret=secret, timeout_s=timeout_s)
                for identity in identities
                for scenario in scenarios
            )
        )
        results.extend(batch)
    return results


def scenario_stats(samples: Sequence[Sample]) -> dict[str, Any]:
    outcomes = Counter(sample.outcome for sample in samples)
    latencies = [sample.latency_ms for sample in samples]
    stats: dict[str, Any] = {"count": len(samples)}
    for key in STATUS_KEYS:
        stats[key] = outcomes.get(key, 0)
    for key in ERROR_KEYS:
        stats[key] = outcomes.get(key, 0)
    stats["auth_errors"] = sum(1 for sample in samples if sample.status_code in (401, 403))
    for label, pct in (("p50_ms", 50), ("p95_ms", 95), ("p99_ms", 99)):
        value = percentile(latencies, pct)
        stats[label] = None if value is None else round(value, 2)
    return stats


def build_failures(
    stats_by_scenario: dict[str, dict[str, Any]],
    isolation_issues: Sequence[str],
    cfg: LoadConfig,
) -> list[str]:
    failures: list[str] = []
    for name, stats in stats_by_scenario.items():
        if stats["5xx"]:
            failures.append(f"5xx en {name}: {stats['5xx']}")
        request_errors = sum(stats[key] for key in ERROR_KEYS)
        if request_errors:
            failures.append(f"errores de conexion/timeout en {name}: {request_errors}")
        if stats["auth_errors"]:
            failures.append(f"401/403 en {name}: {stats['auth_errors']}")
        threshold = cfg.chat_p95_ms if name == "chat" else cfg.p95_ms
        if stats["p95_ms"] is not None and stats["p95_ms"] > threshold:
            failures.append(f"p95 de {name}={stats['p95_ms']} ms supera el umbral {threshold} ms")
    for issue in isolation_issues:
        failures.append(f"aislamiento: {issue}")
    return failures


def aggregate(
    results: Sequence[RequestResult],
    *,
    cfg: LoadConfig,
    identities: Sequence[Identity],
    scenarios: Sequence[Scenario],
    isolation_issues: Sequence[str],
    notes: Sequence[str],
    started_at: datetime,
    duration_s: float,
) -> dict[str, Any]:
    samples = [result.sample for result in results]
    stats_by_scenario = {
        scenario.name: scenario_stats([s for s in samples if s.scenario == scenario.name])
        for scenario in scenarios
    }
    per_user = {
        identity.tenant: {
            scenario.name: scenario_stats(
                [s for s in samples if s.scenario == scenario.name and s.tenant == identity.tenant]
            )
            for scenario in scenarios
        }
        for identity in identities
    }
    fallbacks = Counter(s.fallback_reason for s in samples if s.scenario == "chat" and s.fallback_reason)
    failures = build_failures(stats_by_scenario, isolation_issues, cfg)
    return {
        "ok": not failures,
        "base_url": cfg.base_url,
        "started_at": started_at.isoformat(),
        "duration_s": round(duration_s, 3),
        "rounds": cfg.rounds,
        "timeout_s": cfg.timeout_s,
        "skip_llm": cfg.skip_llm,
        "scenarios_plan": [
            {"name": scenario.name, "method": scenario.method, "path": scenario.path}
            for scenario in scenarios
        ],
        "identities": [
            {"label": identity.label, "tenant": identity.tenant, "user": identity.user}
            for identity in identities
        ],
        "scenarios": stats_by_scenario,
        "per_user": per_user,
        "chat_fallback_reasons": dict(fallbacks),
        "isolation": {
            "ok": not isolation_issues,
            "checked": True,
            "method": "budget.tenant_scoped en /api/settings y escaneo de tenant* en la respuesta propia",
            "limits": (
                "Los endpoints medidos no devuelven el tenant; esto detecta ecos o fugas "
                "visibles, no demuestra propiedad de cada fila."
            ),
            "issues": list(isolation_issues),
        },
        "thresholds": {"p95_ms": cfg.p95_ms, "chat_p95_ms": cfg.chat_p95_ms},
        "notes": list(notes),
        "failures": failures,
    }


async def run_load(
    client: httpx.AsyncClient,
    *,
    cfg: LoadConfig,
    secret: str,
    identities: Sequence[Identity],
    portfolio_path: str = DEFAULT_PORTFOLIO_PATH,
    include_inicio_watchlist: bool = False,
) -> dict[str, Any]:
    started_at = datetime.now(UTC)
    started = time.perf_counter()
    probe = await probe_identities(client, secret=secret, identities=identities, timeout_s=cfg.timeout_s)
    notes = list(probe.notes)

    if cfg.skip_llm:
        include_chat = False
        notes.append("POST /api/chat omitido por --skip-llm")
    elif probe.llm_configured is False:
        include_chat = False
        notes.append("POST /api/chat omitido: /api/settings informa llm.configured=false (sin clave/mock)")
    elif probe.llm_configured is None:
        include_chat = True
        notes.append(
            "No se pudo confirmar LLM en /api/settings; se incluye POST /api/chat "
            "y puede medir la ruta determinista"
        )
    else:
        include_chat = True

    scenarios = build_scenarios(
        include_chat=include_chat,
        portfolio_path=portfolio_path,
        include_inicio_watchlist=include_inicio_watchlist,
    )
    if include_inicio_watchlist:
        notes.append("perfil Inicio/Watchlist activo (--inicio-watchlist): 5 GETs de solo lectura")
    results = await run_rounds(
        client,
        secret=secret,
        identities=identities,
        scenarios=scenarios,
        rounds=cfg.rounds,
        timeout_s=cfg.timeout_s,
    )
    isolation_issues = list(probe.issues)
    all_tenants = [identity.tenant for identity in identities]
    for result in results:
        if result.payload is not None:
            isolation_issues.extend(
                inspect_tenant_payload(
                    result.payload,
                    expected_tenant=result.sample.tenant,
                    other_tenants=all_tenants,
                )
            )
    isolation_issues = list(dict.fromkeys(isolation_issues))
    duration_s = time.perf_counter() - started
    return aggregate(
        results,
        cfg=cfg,
        identities=identities,
        scenarios=scenarios,
        isolation_issues=isolation_issues,
        notes=notes,
        started_at=started_at,
        duration_s=duration_s,
    )


def _fmt_ms(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:.1f}".replace(".", ",")


def print_report(report: dict[str, Any]) -> None:
    print(f"Arnes de carga 3 usuarios · {report['base_url']}")
    print(
        f"Rondas: {report['rounds']} · timeout: {report['timeout_s']} s · duracion: {report['duration_s']} s"
    )
    print("")
    header = f"{'Escenario':<20} {'n':>3} {'2xx':>4} {'4xx':>4} {'5xx':>4} {'err':>4} {'p50 ms':>9} {'p95 ms':>9} {'p99 ms':>9}"
    print(header)
    print("-" * len(header))
    for name, stats in report["scenarios"].items():
        request_errors = sum(stats[key] for key in ERROR_KEYS)
        print(
            f"{name:<20} {stats['count']:>3} {stats['2xx']:>4} {stats['4xx']:>4} "
            f"{stats['5xx']:>4} {request_errors:>4} {_fmt_ms(stats['p50_ms']):>9} "
            f"{_fmt_ms(stats['p95_ms']):>9} {_fmt_ms(stats['p99_ms']):>9}"
        )
    print("")
    print(
        f"Umbrales: p95 <= {_fmt_ms(report['thresholds']['p95_ms'])} ms "
        f"(chat <= {_fmt_ms(report['thresholds']['chat_p95_ms'])} ms)"
    )
    isolation = report["isolation"]
    print(f"Aislamiento: {'OK' if isolation['ok'] else 'FALLO'}")
    if report["chat_fallback_reasons"]:
        print(f"Fallbacks de chat: {report['chat_fallback_reasons']}")
    for note in report["notes"]:
        print(f"Nota: {note}")
    print("Resultado:", "OK" if report["ok"] else "FALLO")
    for failure in report["failures"]:
        print(f"  - {failure}")


def print_plan(
    *,
    base_url: str,
    identities: Sequence[Identity],
    scenarios: Sequence[Scenario],
    cfg: LoadConfig,
    json_out: Path | None,
) -> None:
    print("DRY-RUN: no se hara ninguna peticion de red ni se leera el secreto.")
    print(f"base_url: {base_url}")
    print(f"rondas: {cfg.rounds} · timeout: {cfg.timeout_s} s")
    print("identidades:")
    for identity in identities:
        print(f"  - {identity.label}: tenant={identity.tenant} user={identity.user}")
    print("escenarios:")
    for scenario in scenarios:
        print(f"  - {scenario.name}: {scenario.method} {scenario.path}")
    if cfg.skip_llm:
        print("  - chat: omitido por --skip-llm")
    else:
        print("  - nota chat: se omite si /api/settings informa llm.configured=false")
    per_round = len(scenarios) * len(identities)
    print(
        f"peticiones medidas: {per_round} por ronda · "
        f"{per_round * cfg.rounds} en total + {len(identities)} sondas /api/settings"
    )
    print(f"umbrales: p95 <= {_fmt_ms(cfg.p95_ms)} ms · chat p95 <= {_fmt_ms(cfg.chat_p95_ms)} ms")
    if json_out is not None:
        print(f"json-out: {json_out} (no se escribe en dry-run)")


async def _execute(
    client: httpx.AsyncClient,
    cfg: LoadConfig,
    secret: str,
    identities: Sequence[Identity],
    portfolio_path: str,
    include_inicio_watchlist: bool = False,
) -> dict[str, Any]:
    return await run_load(
        client,
        cfg=cfg,
        secret=secret,
        identities=identities,
        portfolio_path=portfolio_path,
        include_inicio_watchlist=include_inicio_watchlist,
    )


def _run_async(
    cfg: LoadConfig,
    secret: str,
    identities: Sequence[Identity],
    portfolio_path: str,
    include_inicio_watchlist: bool = False,
) -> dict[str, Any]:
    limits = httpx.Limits(max_connections=32, max_keepalive_connections=16)

    async def runner() -> dict[str, Any]:
        async with httpx.AsyncClient(
            base_url=cfg.base_url,
            timeout=cfg.timeout_s,
            follow_redirects=False,
            limits=limits,
        ) as client:
            return await _execute(
                client,
                cfg,
                secret,
                identities,
                portfolio_path,
                include_inicio_watchlist=include_inicio_watchlist,
            )

    return asyncio.run(runner())


def write_json_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        base_url = validate_base_url(args.base_url, allow_remote=args.allow_remote)
        identities = build_identities(args.tenant_prefix)
        portfolio_path = validate_endpoint_path(args.portfolio_path)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if not is_loopback_host(urlsplit(base_url).hostname or "") and args.allow_remote:
        print(
            "AVISO: --allow-remote activo; el arnes puede golpear un host no loopback. "
            "No lo uses contra produccion.",
            file=sys.stderr,
        )

    cfg = LoadConfig(
        base_url=base_url,
        rounds=args.rounds,
        timeout_s=args.timeout_s,
        p95_ms=args.p95_ms,
        chat_p95_ms=args.chat_p95_ms,
        skip_llm=args.skip_llm,
    )
    if args.dry_run:
        include_chat = not args.skip_llm
        print_plan(
            base_url=base_url,
            identities=identities,
            scenarios=build_scenarios(
                include_chat=include_chat,
                portfolio_path=portfolio_path,
                include_inicio_watchlist=args.inicio_watchlist,
            ),
            cfg=cfg,
            json_out=args.json_out,
        )
        return 0

    try:
        secret = resolve_secret(args.env_file)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    try:
        report = _run_async(
            cfg,
            secret,
            identities,
            portfolio_path,
            include_inicio_watchlist=args.inicio_watchlist,
        )
    except KeyboardInterrupt:
        print("interrumpido", file=sys.stderr)
        return 130

    print_report(report)
    if args.json_out is not None:
        write_json_report(args.json_out, report)
        print(f"JSON: {args.json_out}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
