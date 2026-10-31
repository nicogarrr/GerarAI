"""Transporte compartido de la via edgartools: identidad, throttle y snapshot.

- Identidad: la SEC exige User-Agent declarado con contacto (mismo requisito
  que ``connectors/sec_edgar.py`` y ``connectors/form4.py``). Se publica via
  ``edgar.set_identity`` cuando la libreria esta instalada; sin ella la via
  edgartools solo puede leer el snapshot local.
- Throttle: maximo SEC 10 req/s. Es propio y esta documentado aqui porque los
  del repo no son reutilizables por import: ``form4._throttle`` es sincrono con
  estado global de modulo y ``SECClient._throttle`` es un metodo de instancia
  async atado a su cliente. Misma constante (0.1 s) y mismo cap (10 req/s).
- Circuit breaker de 429: espejo en memoria de ``_SEC_429_*`` de
  ``app/workers/dramatiq_app.py`` (ventana 600 s, racha 5, cooldown 3600 s).
  El breaker de Redis sigue siendo la autoridad en los workers; este freno
  evita que la propia via edgartools reintente en bucle antes de llegar alli.
  Ante 429 la via NO reintenta: contabiliza la racha y degrada al snapshot.
- Snapshot: ``$EDGARTOOLS_SNAPSHOT_DIR/manifest.json`` (tickers + synced_at)
  + ``companyfacts/CIK##########.json`` + ``submissions/CIK##########.json``
  + ``filings/<ACCESSION_SIN_GUIONES>/<primary|infotable>.xml``. Mismo patron
  versionado que ``SEC_SNAPSHOT_DIR``: el dato viaja con la app.
- 401/403 de la SEC (caso OCI: IP baneada, permanente) degradan al snapshot
  con estado explicito; jamas se reintenta en bucle.
"""

from __future__ import annotations

import asyncio
import json
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Pin verificado de edgartools (2026-10-01, ``pip index versions``: 5.59.1 es
# la ultima). NO anadir a requirements.txt (prohibido en este task): instalar
# con ``.\.venv\Scripts\python.exe -m pip install edgartools==5.59.1``.
EDGARTOOLS_VERSION_PIN = "5.59.1"

# SEC fair-access: maximo 10 peticiones/segundo (misma constante que
# connectors/form4.py MIN_INTERVAL_SECONDS y que SECClient con cap a 10).
SEC_MAX_REQUESTS_PER_SECOND = 10.0
MIN_INTERVAL_SECONDS = 0.1

# Espejo en memoria del breaker de dramatiq_app.py (misma semantica, mismos
# valores): racha de _STREAK_LIMIT 429s dentro de _WINDOW_S abre el breaker
# durante _COOLDOWN_S. Alla el estado vive en Redis (global); aqui es por
# proceso y solo frena a esta via.
BREAKER_WINDOW_S = 600.0
BREAKER_STREAK_LIMIT = 5
BREAKER_COOLDOWN_S = 3600.0

DEFAULT_CONTACT = "contact@gerarai.local"
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
_STATUS_RE = re.compile(r"\b(4\d\d|5\d\d)\b")


def is_installed() -> bool:
    """True si edgartools esta importable (la via live lo exige)."""
    try:
        import edgar  # noqa: F401

        return True
    except ImportError:
        return False


def resolve_identity() -> str:
    """Identidad ``Nombre email`` para ``edgar.set_identity``.

    Env ``EDGARTOOLS_IDENTITY`` > settings.edgartools_identity > derivado de
    settings.sec_user_agent (del que se extrae el email). Nunca devuelve un
    valor sin email: la SEC lo rechaza con 403.
    """
    from app.core.config import get_settings

    settings = get_settings()
    candidate = (getattr(settings, "edgartools_identity", None) or "").strip() or (
        settings.sec_user_agent or ""
    ).strip()
    match = _EMAIL_RE.search(candidate)
    contact = match.group(0) if match else DEFAULT_CONTACT
    if any(brand in candidate for brand in ("CavaAI", "GerarAI")):
        return f"GerarAI research {contact}"
    return candidate if "@" in candidate else f"GerarAI research {contact}"


def ensure_identity() -> str | None:
    """Publica la identidad en edgartools. None si no esta instalado.

    No lanza nunca: sin libreria la via solo lee snapshot (estado explicito
    en el resultado de la ingesta).
    """
    try:
        from edgar import set_identity
    except ImportError:
        return None
    identity = resolve_identity()
    try:
        set_identity(identity)
    except Exception:
        return None
    return identity


class EdgarToolsThrottle:
    """Throttle SEC 10 req/s, sincrono y asincrono, con cap documentado."""

    def __init__(self, requests_per_second: float = 8.0) -> None:
        capped = max(0.1, min(requests_per_second, SEC_MAX_REQUESTS_PER_SECOND))
        self.min_interval = 1.0 / capped
        self._sync_lock = threading.Lock()
        self._async_lock = asyncio.Lock()
        self._last_at = 0.0

    def wait_sync(self) -> None:
        with self._sync_lock:
            elapsed = time.monotonic() - self._last_at
            wait = self.min_interval - elapsed
            if wait > 0:
                time.sleep(wait)
            self._last_at = time.monotonic()

    async def wait_async(self) -> None:
        async with self._async_lock:
            elapsed = time.monotonic() - self._last_at
            wait = self.min_interval - elapsed
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_at = time.monotonic()

    def reset_for_tests(self) -> None:
        with self._sync_lock:
            self._last_at = 0.0


_default_throttle = EdgarToolsThrottle()


def default_throttle() -> EdgarToolsThrottle:
    return _default_throttle


def throttle_sync() -> None:
    _default_throttle.wait_sync()


async def throttle_async() -> None:
    await _default_throttle.wait_async()


class RateLimitBreaker:
    """Racha de 429 que abre 3600 s (espejo en memoria de dramatiq_app)."""

    def __init__(
        self,
        *,
        window_s: float = BREAKER_WINDOW_S,
        streak_limit: int = BREAKER_STREAK_LIMIT,
        cooldown_s: float = BREAKER_COOLDOWN_S,
    ) -> None:
        self.window_s = window_s
        self.streak_limit = streak_limit
        self.cooldown_s = cooldown_s
        self._lock = threading.Lock()
        self._streak = 0
        self._window_start = 0.0
        self._opened_until = 0.0

    def is_open(self) -> bool:
        with self._lock:
            return time.monotonic() < self._opened_until

    def record_429(self) -> bool:
        """Contabiliza un 429. Devuelve True si el breaker queda abierto."""
        now = time.monotonic()
        with self._lock:
            if now < self._opened_until:
                return True
            if now - self._window_start > self.window_s:
                self._streak = 0
                self._window_start = now
            self._streak += 1
            if self._streak >= self.streak_limit:
                self._opened_until = now + self.cooldown_s
                self._streak = 0
                return True
            return False

    def record_success(self) -> None:
        with self._lock:
            self._streak = 0

    def reset_for_tests(self) -> None:
        with self._lock:
            self._streak = 0
            self._window_start = 0.0
            self._opened_until = 0.0


_default_breaker = RateLimitBreaker()


def default_breaker() -> RateLimitBreaker:
    return _default_breaker


def http_status_from_error(exc: BaseException) -> int | None:
    """Status HTTP de una excepcion (edgartools/httpx envuelven el codigo).

    Misma idea que ``_status_from_message`` de dramatiq_app: el codigo viaja
    en el texto ("request failed (403 ...)", "'429 Too Many Requests'") o en
    ``exc.response.status_code``. Solo acepta 4xx/5xx reales.
    """
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    if isinstance(status, int) and 400 <= status <= 599:
        return status
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        match = _STATUS_RE.search(str(current))
        if match:
            candidate = int(match.group(1))
            if 400 <= candidate <= 599:
                return candidate
        current = current.__cause__ or current.__context__
    return None


def is_sec_block(exc: BaseException) -> bool:
    """True si el fallo es 401/403 (IP baneada): degrada a snapshot, sin reintento."""
    return http_status_from_error(exc) in {401, 403}


_SEC_REGISTRY_KEY = "sec_edgar"


def report_sec_failure_to_health(status: int | None, *, registry: Any = None) -> bool:
    """Registra un fallo live de SEC EDGAR en el registry central de fuentes.

    Devuelve True si conto como fallo de FUENTE. 400/404 son dato por ticker
    (companyfacts inexistente para ese CIK): la fuente respondio y el circuito
    no se mueve. 429, 401/403 (IP baneada, caso OCI documentado), 5xx y fallo
    de red sin status si degradan. El breaker propio (RateLimitBreaker) sigue
    igual; esto solo hace visible la salud en /api/health/data-sources.
    """
    if status in (400, 404):
        return False
    if registry is None:
        from app.services.data_source_health import get_data_source_registry

        registry = get_data_source_registry()
    if status == 429:
        reason = "429 rate limit"
    elif status in (401, 403):
        reason = f"SEC bloqueada (HTTP {status}, IP baneada)"
    elif status is None:
        reason = "error de red o cliente sin status"
    else:
        reason = f"HTTP {status}"
    registry.record_failure(_SEC_REGISTRY_KEY, reason)
    return True


def report_sec_success_to_health(*, registry: Any = None) -> None:
    """Marca SEC EDGAR sana en el registry central tras una llamada live ok."""
    if registry is None:
        from app.services.data_source_health import get_data_source_registry

        registry = get_data_source_registry()
    registry.record_success(_SEC_REGISTRY_KEY)


# ---------------- Snapshot en disco (offline-first) ----------------


def snapshot_root() -> Path | None:
    from app.core.config import get_settings

    base = get_settings().edgartools_snapshot_dir
    if not base:
        return None
    root = Path(base)
    return root if root.exists() else None


def read_manifest(root: Path | None = None) -> dict[str, Any] | None:
    base = root or snapshot_root()
    if base is None:
        return None
    path = base / "manifest.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def manifest_cik(ticker: str, root: Path | None = None) -> str | None:
    manifest = read_manifest(root)
    if not manifest:
        return None
    tickers = manifest.get("tickers", {})
    if not isinstance(tickers, dict):
        return None
    cik = tickers.get(ticker.strip().upper())
    return str(cik).strip().zfill(10) if cik else None


def manifest_synced_at(root: Path | None = None) -> str | None:
    manifest = read_manifest(root)
    if not manifest:
        return None
    synced = manifest.get("synced_at")
    return str(synced) if synced else None


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def read_companyfacts(cik: str | int, root: Path | None = None) -> dict[str, Any] | None:
    base = root or snapshot_root()
    if base is None:
        return None
    padded = str(cik).strip().zfill(10)
    return _read_json(base / "companyfacts" / f"CIK{padded}.json")


def read_submissions(cik: str | int, root: Path | None = None) -> dict[str, Any] | None:
    base = root or snapshot_root()
    if base is None:
        return None
    padded = str(cik).strip().zfill(10)
    return _read_json(base / "submissions" / f"CIK{padded}.json")


def read_filing_xml(accession_number: str, filename: str, root: Path | None = None) -> str | None:
    """XML crudo de un filing del snapshot (Form 4 o information table 13F)."""
    base = root or snapshot_root()
    if base is None:
        return None
    folder = str(accession_number).replace("-", "")
    path = base / "filings" / folder / filename
    if not path.exists():
        return None
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


@dataclass(frozen=True)
class TransportState:
    """Procedencia de transporte, siempre explicita en el resultado."""

    transport: str  # "live" | "snapshot"
    synced_at: str | None = None
    reason: str | None = None
