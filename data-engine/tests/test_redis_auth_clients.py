"""Redis con contraseña (#3232): todo cliente del servicio usa la URL de Settings.

En producción la contraseña viaja SOLO dentro de ``REDIS_URL``
(``redis://:${REDIS_PASSWORD}@redis:6379/0``, docker-compose.prod.yml; el
compose lo fija ``test_prod_compose``). Un cliente que construya su propia URL,
use ``Redis(host=...)`` o una URL fija se conectaría sin AUTH y fallaría
(NOAUTH) en cuanto se despliega. Este guard exige que cada ``from_url`` de
``app/`` reciba ``redis_url`` (de Settings o de un parámetro con ese nombre) y
comprueba que la contraseña llega al pool del broker de colas y de los clientes
de caché/rate limit.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
URL = "redis://:s3cretPw42@127.0.0.1:6390/0"


def _py_files():
    yield ROOT / "main.py"
    yield from (ROOT / "app").rglob("*.py")


def _enclosing_assignments(tree: ast.AST) -> dict[int, list[str]]:
    """Para cada Call (por id), los textos de las asignaciones de su función."""
    out: dict[int, list[str]] = {}
    for func in ast.walk(tree):
        if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        texts = [ast.unparse(n) for n in ast.walk(func) if isinstance(n, (ast.Assign, ast.AnnAssign))]
        texts += [a.arg for a in func.args.args + func.args.kwonlyargs]
        for node in ast.walk(func):
            if isinstance(node, ast.Call):
                out.setdefault(id(node), texts)
    return out


def test_every_redis_client_reads_the_settings_url_with_its_password():
    offenders = []
    checked = 0
    for path in _py_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        scope = _enclosing_assignments(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            owner = ast.unparse(func.value).lower() if isinstance(func, ast.Attribute) else ""
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            where = f"{path.relative_to(ROOT)}:{node.lineno}"
            if name == "Redis" and any(kw.arg in {"host", "port", "unix_socket_path"} for kw in node.keywords):
                offenders.append(f"{where} Redis(host=...) sin la URL con contraseña")
                continue
            if name != "from_url" or "redis" not in owner:
                continue
            checked += 1
            arg = node.args[0] if node.args else next((kw.value for kw in node.keywords if kw.arg == "url"), None)
            if arg is None:
                offenders.append(f"{where} from_url sin URL")
                continue
            text = ast.unparse(arg)
            if "redis_url" in text:
                continue
            if isinstance(arg, ast.Name) and any(
                t.startswith(f"{arg.id} =") and "redis_url" in t or t == arg.id == "redis_url"
                for t in scope.get(id(node), [])
            ):
                continue
            offenders.append(f"{where} from_url({text}) no sale de Settings.redis_url")
    assert checked >= 10, checked  # el guard ve los clientes reales
    assert offenders == []


def test_queue_broker_authenticates_with_the_url_password():
    from app.workers.bounded_broker import BoundedRedisBroker

    broker = BoundedRedisBroker(url=URL)
    kwargs = broker.client.connection_pool.connection_kwargs
    assert kwargs["password"] == "s3cretPw42"
    assert kwargs["host"] == "127.0.0.1" and kwargs["port"] == 6390


def test_cache_rate_limit_and_lease_clients_get_the_password(monkeypatch):
    import redis
    import redis.asyncio

    from app.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "redis_url", URL, raising=False)
    seen: list[str] = []

    def capture(original):
        def wrapper(url, *args, **kwargs):
            seen.append(url)
            return original(url, *args, **kwargs)
        return wrapper

    monkeypatch.setattr(redis.Redis, "from_url", capture(redis.Redis.from_url))
    monkeypatch.setattr(redis, "from_url", capture(redis.from_url))
    monkeypatch.setattr(redis.asyncio, "from_url", capture(redis.asyncio.from_url))

    from app.services import market_refresh_service, movers_cache
    from app.workers import dramatiq_app

    for factory in (
        getattr(movers_cache, "_redis", None),
        getattr(market_refresh_service, "_marketdata_breaker_client", None),
    ):
        if factory is None:
            continue
        try:
            factory()
        except Exception:  # noqa: BLE001 - sin servidor: basta con la URL usada
            pass
    assert dramatiq_app._lease_redis_url() == URL
    assert seen, "ningún cliente Redis se construyó"
    assert all(url == URL for url in seen), seen
    client = redis.Redis.from_url(seen[0])
    assert client.connection_pool.connection_kwargs["password"] == "s3cretPw42"
