"""Contratos y utilidades compartidas por los connectors de ingesta."""


from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

# ---------------- Ritmo de salida a la SEC (estado GLOBAL de proceso) ----------------

# SEC fair-use: maximo 10 peticiones/segundo. El limite lo aplica la SEC por
# IP/proceso, NO por modulo de Python: cada modulo con su propio reloj se
# persuade a si mismo y dos conectores distintos disparan a la vez. Por eso el
# estado vive aqui y no duplicado en ``form4`` / ``form13f``: un fetch 13F y un
# Form 4 seguidos deben contar desde la MISMA ultima llamada, o la SEC responde
# 403 y el barrido pierde ambos tramites sin error visible.
SEC_MAX_REQUESTS_PER_SECOND = 10.0
SEC_MIN_INTERVAL_SECONDS = 1.0 / SEC_MAX_REQUESTS_PER_SECOND


class SecRateLimiter:
    """Separador de llamadas a data.sec.gov, compartido por todos los conectores.

    Un unico lock por proceso: el sleep ocurre DENTRO del lock a proposito. Es
    lo que hace correcto el calculo bajo concurrencia — si se midiera fuera, N
    hilos verian el mismo ``_next_allowed_at`` y saldrian todos juntos.

    Dos detalles no negociables para que 10 req/s sea 10 req/s y no "casi":

    - El reloj es ``perf_counter``, no ``monotonic``. En Windows ``monotonic``
      es ``GetTickCount64`` y resuelve a ~15.6 ms: con el, ``sleep(0.1)`` se
      mide como 0.094 s y la llamada siguiente se adelanta, dando ~12.8 req/s.
      ``perf_counter`` usa ``QueryPerformanceCounter`` (~100 ns) y es igual de
      monotono.
    - El reinicio del hueco se comprueba en bucle tras el sleep. Registrar el
      instante de una sola lectura puede dejar el plazo ya vencido; asi el hueco
      siguiente nunca se acorta.
    """

    def __init__(self, min_interval: float = SEC_MIN_INTERVAL_SECONDS) -> None:
        if min_interval <= 0:
            raise ValueError(f"min_interval must be > 0, got {min_interval}")
        self.min_interval = float(min_interval)
        self._lock = threading.Lock()
        self._next_allowed_at = 0.0

    def wait(self) -> None:
        with self._lock:
            while True:
                remaining = self._next_allowed_at - time.perf_counter()
                if remaining <= 0:
                    break
                time.sleep(remaining)
            self._next_allowed_at = time.perf_counter() + self.min_interval

    def reset(self) -> None:
        """Solo para tests: deja el reloj como recien arrancado."""
        with self._lock:
            self._next_allowed_at = 0.0


# Singleton de proceso. Importarlo por referencia desde cada conector es lo que
# convierte "un throttle por modulo" en "un throttle para la SEC".
_sec_rate_limiter = SecRateLimiter()


def sec_throttle() -> None:
    """Bloquea hasta poder emitir otra peticion a la SEC sin pasar de 10 req/s."""
    from app.services.connectors.sec_pacing import pacer

    _sec_rate_limiter.wait()
    pacer.wait_sync()


def reset_sec_rate_limiter() -> None:
    """Solo para tests: reinicia el reloj global de la SEC."""
    from app.services.connectors.sec_pacing import pacer

    _sec_rate_limiter.reset()
    pacer.reset()


# Tope de reintentos por llamada y espera maxima por uno. El presupuesto
# acota el tiempo total en el peor caso.
DEFAULT_MAX_RETRIES = 2
DEFAULT_RETRY_BASE_SECONDS = 0.5
# Las ventanas de Retry-After de cuotas por minuto caben con margen en 120s.
# Por encima NO se reintenta inline: una cuota diaria agotada (FMP free: 250
# llamadas/dia) devuelve ventanas de horas y esperarlas dentro de la corrida
# contradice el header y quema llamadas en ventana prohibida. Se pospone
# via UpstreamRateLimited.
DEFAULT_RETRY_CAP_SECONDS = 120.0


class UpstreamRateLimited(RuntimeError):
    """El proveedor respondio 429 y se agotaron los reintentos con presupuesto.

    ``retry_after`` conserva la ventana que pidio el servidor (si la mando)
    para que el llamante marque un cooldown global en vez de seguir
    martilleando (medido 31-oct-2026: 1.077 429 de Finnhub en 10 min).
    """

    def __init__(self, message: str, *, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


def _raw_retry_after(response: Any) -> float | None:
    """Valor crudo de la cabecera Retry-After, o None si no hay/ no parsea."""
    header = None
    try:
        header = response.headers.get("retry-after")
    except AttributeError:
        return None
    if not header:
        return None
    try:
        return max(0.0, float(header))
    except (TypeError, ValueError):
        return None


def retry_after_seconds(response: Any, cap: float = DEFAULT_RETRY_CAP_SECONDS) -> float:
    """Segundos a esperar antes del reintento inline, nunca mas de ``cap``.

    Ignorarla y reintentar con backoff propio es lo que convierte un 429 en un
    baneo de la clave: el proveedor dice explicitamente cuando puede volver a
    intentarse. Solo se usa para esperas que CABEN en el cap (cuotas por
    minuto); ``get_with_retry`` nunca la invoca para ventanas mayores, que se
    posponen sin reintento inline.
    """
    raw = _raw_retry_after(response)
    if raw is None:
        return 0.0
    return min(raw, cap)


def _backoff_seconds(
    attempt: int, base_seconds: float, cap_seconds: float, *, jitter: bool
) -> float:
    """Exponencial acotado; con ``jitter`` la espera es uniforme en [0, expo].

    El jitter decorrelaciona workers que reciben 429 a la vez: sin el, los
    reintentos de N procesos salen en el mismo segundo y vuelven a chocar
    (thundering herd medido en prod, 31-oct-2026). Retry-After se aplica
    ENCIMA como suelo en el llamante: el jitter nunca lo recorta.
    """
    expo = min(base_seconds * (2**attempt), cap_seconds)
    if not jitter:
        return expo
    import random

    return random.uniform(0.0, expo)


async def get_with_retry(
    fetch: Any,
    *,
    max_retries: int = DEFAULT_MAX_RETRIES,
    base_seconds: float = DEFAULT_RETRY_BASE_SECONDS,
    cap_seconds: float = DEFAULT_RETRY_CAP_SECONDS,
    jitter: bool = False,
) -> Any:
    """Ejecuta ``fetch()`` reintentando 429 y 5xx con backoff y presupuesto.

Finnhub free son 60 llamadas/minuto (fuente: finnhub.io/pricing, consultada
2026-09-26) y FMP free 250 llamadas/DIA
(fuente: site.financialmodelingprep.com/developer/docs/pricing, consultada
2026-09-26). Antes sus clients hacian ``raise_for_status()`` y nada
mas: un 429 era un fallo definitivo, el llamante lo tragaba como
``status="unavailable"`` y el barrido de precios perdia la cobertura sin
reintentar nunca. Con 6 peticiones concurrentes sobre un tier de 60/min, un
unico reflejo de trafico agotaba la cuota y no habia forma de recuperarse
dentro de la misma corrida.

    Reintenta solo 429 y 5xx: un 401/403/404 es un problema de configuracion o
    de entitlement y reintentar solo gasta cuota.
    """
    import httpx

    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            response = await fetch()
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            last_exc = exc
            if attempt >= max_retries:
                raise
            await asyncio.sleep(min(base_seconds * (2**attempt), cap_seconds))
            continue

        status = getattr(response, "status_code", 200)
        if status == 429:
            raw_retry_after = _raw_retry_after(response)
            if raw_retry_after is not None and raw_retry_after > cap_seconds:
                # El proveedor pide esperar mas de lo que esta corrida puede
                # pagar (p.ej. cuota diaria agotada: ventanas de horas). No se
                # trunca ni se reintenta inline: se pospone y el caller marca
                # el proveedor no disponible para esta corrida.
                raise UpstreamRateLimited(
                    f"upstream pidio Retry-After {raw_retry_after:.0f}s "
                    f"(> cap {cap_seconds:.0f}s): pospuesto sin reintento inline",
                    retry_after=raw_retry_after,
                )
            if attempt < max_retries:
                await asyncio.sleep(
                    max(
                        retry_after_seconds(response, cap_seconds),
                        _backoff_seconds(attempt, base_seconds, cap_seconds, jitter=jitter),
                    )
                )
                continue
            raise UpstreamRateLimited(
                f"upstream rate limited after {max_retries} retries",
                retry_after=raw_retry_after,
            )
        if status >= 500 and attempt < max_retries:
            await asyncio.sleep(_backoff_seconds(attempt, base_seconds, cap_seconds, jitter=jitter))
            continue
        response.raise_for_status()
        return response

    if last_exc is not None:  # pragma: no cover - solo por tipos
        raise last_exc
    raise RuntimeError("unreachable")  # pragma: no cover


@dataclass(slots=True)
class ConnectorItem:
    """Provider-neutral item returned by every polling connector."""

    source: str
    title: str
    url: str | None = None
    summary: str = ""
    published_at: datetime | None = None
    ticker: str | None = None
    item_type: str = "news"
    external_id: str | None = None
    # False = el conector no recibio un titular real del medio: `title` es
    # texto de display generado por GerarAI y NO debe guardarse como
    # source_headline (ese campo promete el titular verbatim de la fuente).
    headline_from_source: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "title": self.title,
            "url": self.url,
            "summary": self.summary,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "ticker": self.ticker,
            "item_type": self.item_type,
            "external_id": self.external_id,
            "metadata": self.metadata,
        }


@dataclass(slots=True)
class ConnectorResult:
    """Shared polling result that preserves partial failures and diagnostics."""

    source: str
    items: list[ConnectorItem] = field(default_factory=list)
    fetched_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    errors: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def connector(self) -> str:
        return self.source

    @property
    def status(self) -> str:
        if self.errors and self.items:
            return "partial"
        if self.errors:
            return "error"
        return "ok"

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "source": self.source,
            "fetched_at": self.fetched_at.isoformat(),
            "items": [item.as_dict() for item in self.items],
            "errors": list(self.errors),
            "metadata": self.metadata,
        }

    @classmethod
    def failed(
        cls,
        source: str,
        error: Exception | str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> ConnectorResult:
        return cls(source=source, errors=[str(error)], metadata=metadata or {})
