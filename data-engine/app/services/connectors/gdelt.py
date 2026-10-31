from __future__ import annotations

import asyncio
import math
import threading
import time
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

import httpx

from app.core.config import get_settings
from app.services.connectors.base import ConnectorItem, ConnectorResult
from app.services.connectors.global_pacing import GlobalPacer
from app.services.data_source_health import get_data_source_registry

# Clave de este proveedor en el registry de salud de fuentes. El 429 de GDELT
# es POR IP (afecta a todo el carril), asi que SI degrada la fuente; un 400
# es una query invalida (nivel de consulta, no de fuente) y NO degrada.
REGISTRY_KEY = "gdelt"


class GdeltRateLimited(Exception):
    """GDELT cerro la ventana (429): sube tipada con el Retry-After.

    El cliente honra la ventana inline un numero acotado de veces; agotados
    los reintentos inline (o ventana mayor que la que una corrida puede
    pagar), el 429 sube con la ventana real para que el actor dramatiq
    reencole el LOTE tras ella en vez de seguir quemando cuota por IP
    contra una ventana cerrada.
    """

    def __init__(self, retry_after: float) -> None:
        super().__init__(f"GDELT 429: ventana cerrada, reintentar tras {retry_after:.0f}s")
        self.retry_after = retry_after


def _gdelt_redis_client():
    try:
        import redis as _redis

        from app.core.redis_retry import no_retry

        url = get_settings().redis_url
        if not url:
            return None
        return _redis.from_url(url, socket_connect_timeout=0.5, socket_timeout=1.0, retry=no_retry())
    except Exception:  # noqa: BLE001 - sin Redis: cooldown solo de clase
        return None


# Cooldown 429 compartido entre procesos (scheduler + workers + API, misma IP
# de salida). El pacing de 5s entre peticiones sigue siendo de clase: la cola
# gdelt la consume un solo proceso por diseño.
_gdelt_pacer = GlobalPacer(
    "gdelt",
    min_interval_seconds=5.0,
    redis_client_factory=_gdelt_redis_client,
    # Sin fallback local: el pacing por clase (_next_allowed_at) ya rige este
    # proceso; el pacer aporta el ritmo ENTRE procesos via Redis. Un fallback
    # con reloj monotonic real colgaria los tests de reloj falso.
    fallback_local=False,
    # Resuelto EN CADA LLAMADA desde el namespace del modulo: los tests
    # sustituyen gdelt.asyncio (fake_clock) y cubren tambien la espera del
    # pacer; con Redis real era una espera real no cubierta (cluster rojo CI).
    sleep_async=lambda seconds: asyncio.sleep(seconds),
)


class GDELTClient:
    """Cliente GDELT DOC 2.0 con pacing global y respeto a 429.

    GDELT (tier gratuito) pide ~1 petición cada 5 segundos. Sin pacing, un
    ciclo de ``refresh_news`` sobre todas las compañías y tenants provoca una
    tormenta de 429 que satura la cola dramatiq. El pacing es a nivel de
    clase (proceso): todas las instancias comparten la misma ventana.

    429: se honra ``Retry-After`` (acotado) hasta ``max_429_retries`` veces;
    después el 429 sube TIPADO (``GdeltRateLimited``, con la ventana) y el
    actor reencola el lote tras ella. Una cabecera por encima de
    ``MAX_RETRY_AFTER`` pide una espera que esta corrida no puede pagar: NO
    se trunca ni se reintenta inline, sube tipada con la ventana real.
    """

    base_url = "https://api.gdeltproject.org/api/v2/doc/doc"

    _rate_lock = threading.Lock()
    _next_allowed_at = 0.0  # time.monotonic()
    # Ventana 429 POR IP compartida por TODOS los jobs del carril (un solo
    # proceso consume la cola gdelt por diseño: el estado de clase ES el
    # cooldown global EN ESE PROCESO). Sin esto, tras reencolar un lote los
    # demás mensajes (macro/empresa/backlog) entraban con el pacing de 5s y
    # violaban la ventana de 45/3600s que GDELT acababa de imponer.
    _blocked_until = 0.0  # time.monotonic()

    DEFAULT_MIN_INTERVAL = 5.0
    DEFAULT_MAX_429_RETRIES = 2
    MAX_RETRY_AFTER = 120.0
    # Suelo para ventana 0/ausente: un 429 sin Retry-After (o con 0) no
    # puede reintentar en menos de 60s — ni inline, ni el mensaje
    # reencolado, ni el cooldown global POR IP. Un Retry(delay=0) eludiria
    # el min_backoff del actor y buclearia contra la ventana cerrada.
    RETRY_AFTER_FLOOR = 60.0
    DEFAULT_RETRY_AFTER = RETRY_AFTER_FLOOR

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        *,
        min_interval: float | None = None,
        max_429_retries: int | None = None,
    ) -> None:
        self.client = client
        self.min_interval = self.DEFAULT_MIN_INTERVAL if min_interval is None else min_interval
        self.max_429_retries = self.DEFAULT_MAX_429_RETRIES if max_429_retries is None else max_429_retries

    @classmethod
    def _block_for(cls, seconds: float) -> None:
        """Marca la ventana 429 como POR IP: todo el carril espera hasta ella.

        Solo extiende, nunca acorta una ventana ya marcada (dos 429 seguidos
        se quedan con la ventana mayor). Ademas del estado de clase (un
        proceso), la ventana se publica en Redis: scheduler, API y otros
        workers comparten la MISMA IP de salida y deben respetarla (medido
        31-oct-2026: rachas de 3-16 429 por relojes independientes).
        """
        if not math.isfinite(seconds) or seconds <= 0:
            # Ventana 0/ausente/no finita: el cooldown global tambien paga
            # el suelo (sin el, tras reencolar el mensaje los demas jobs del
            # carril entraban a los 5s contra una ventana aun cerrada).
            seconds = GDELTClient.RETRY_AFTER_FLOOR
        with GDELTClient._rate_lock:
            until = time.monotonic() + seconds
            if until > GDELTClient._blocked_until:
                GDELTClient._blocked_until = until
        _gdelt_pacer.cool_down(seconds)

    async def _throttle(self) -> None:
        """Guarantee at least ``min_interval`` between two real requests.

        The reservation used to be claimed BEFORE sleeping, from a slot
        computed off the previous reservation. A slow wake-up then consumed the
        slot without having waited, and the next call found ``_next_allowed_at``
        already in the past and went out immediately: the spacing collapsed
        exactly under load, which is when GDELT starts answering 429.

        The slot is now claimed only once it is genuinely available, and the
        next slot is measured from the real current time, so an overrun pushes
        the following request out instead of letting it through.
        """
        blocked_redis = _gdelt_pacer.blocked_for_remote()
        # Deadline monotono: esta llamada nunca duerme mas que la ventana
        # remota que vio al entrar. Si el TTL remoto se re-extiende (otro
        # proceso refrescando cooldown) o un Redis devuelve siempre el mismo
        # valor, sin deadline el while dormiria ese delta para siempre.
        deadline = time.monotonic() + blocked_redis if blocked_redis > 0 else None
        while True:
            remote = _gdelt_pacer.blocked_for_remote()
            if deadline is not None:
                remote = min(remote, max(0.0, deadline - time.monotonic()))
            with GDELTClient._rate_lock:
                now = time.monotonic()
                wait = max(
                    GDELTClient._next_allowed_at - now,
                    GDELTClient._blocked_until - now,
                    remote,
                )
                if wait > self.MAX_RETRY_AFTER:
                    # Ventana POR IP mas larga de lo que esta corrida puede
                    # pagar (el time_limit del actor mataria al worker
                    # durmiendo dentro): el mensaje va a diferidos con la
                    # ventana restante en vez de ocupar el carril.
                    raise GdeltRateLimited(wait)
                if wait <= 0 and self.min_interval > 0:
                    GDELTClient._next_allowed_at = now + self.min_interval
                    break
                if wait <= 0:
                    break
            await asyncio.sleep(wait)
        # Ritmo global real (1 req / min_interval entre TODOS los procesos)
        # via Redis; sin Redis es no-op y el pacing local por clase ya rige.
        await _gdelt_pacer.wait()

    @classmethod
    def _raw_retry_after(cls, response: httpx.Response) -> float | None:
        raw = response.headers.get("Retry-After")
        if raw:
            try:
                value = float(raw)
            except ValueError:
                # Retry-After tambien admite HTTP-date (RFC 9110): una fecha
                # futura marca el fin de la ventana; ignorarla devolvia el
                # default (30s) y violaba la ventana real.
                try:
                    parsed = parsedate_to_datetime(raw)
                except (TypeError, ValueError, IndexError, OverflowError):
                    return None
                if parsed is None:
                    return None
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=UTC)
                value = (parsed - datetime.now(UTC)).total_seconds()
            if not math.isfinite(value):
                # Inf/NaN bloquearian indefinido (y desbordan el delay en
                # ms al reencolar): cae al default acotado.
                return None
            return max(0.0, value)
        return None

    @classmethod
    def _retry_after_seconds(cls, response: httpx.Response) -> float:
        raw = cls._raw_retry_after(response)
        if raw is not None and raw > 0:
            return min(raw, cls.MAX_RETRY_AFTER)
        # 0/ausente: la misma ventana que el suelo del mensaje reencolado.
        return cls.DEFAULT_RETRY_AFTER

    async def news_search(self, query: str, max_records: int = 50) -> dict:
        params = {
            "query": query,
            "mode": "artlist",
            "format": "json",
            "maxrecords": max_records,
            "sort": "hybridrel",
        }
        registry = get_data_source_registry()
        attempt = 0
        while True:
            await self._throttle()
            # monotonic (no perf_counter): los tests de pacing sustituyen el
            # reloj del modulo por uno falso que solo conoce monotonic.
            started = time.monotonic()
            try:
                if self.client is not None:
                    response = await self.client.get(self.base_url, params=params)
                else:
                    async with httpx.AsyncClient(timeout=30) as client:
                        response = await client.get(self.base_url, params=params)
            except httpx.TransportError as exc:
                registry.record_failure(REGISTRY_KEY, f"error de red: {type(exc).__name__}")
                raise
            if response.status_code == 429:
                registry.record_failure(REGISTRY_KEY, "HTTP 429: rate limit por IP")
                raw_retry_after = self._raw_retry_after(response)
                # El 429 es POR IP: la ventana la respetan TODOS los jobs del
                # carril, no solo este mensaje.
                self._block_for(raw_retry_after if raw_retry_after is not None else self.DEFAULT_RETRY_AFTER)
                if raw_retry_after is not None and raw_retry_after > self.MAX_RETRY_AFTER:
                    # Ventana prohibida demasiado larga para esta corrida:
                    # no se trunca ni se reintenta inline; sube tipada con la
                    # ventana real para que el actor decida la espera.
                    raise GdeltRateLimited(raw_retry_after)
                if attempt < self.max_429_retries:
                    attempt += 1
                    await asyncio.sleep(self._retry_after_seconds(response))
                    continue
                # Reintentos inline agotados: sube tipada con la ventana
                # acotada; el actor reencola el lote tras ella.
                raise GdeltRateLimited(self._retry_after_seconds(response))
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 400:
                    # Query invalida: la fuente respondio; no se degrada.
                    raise
                registry.record_failure(REGISTRY_KEY, f"HTTP {exc.response.status_code}")
                raise
            try:
                payload = response.json()
            except ValueError:
                # 200 con HTML (pagina de error de GDELT): la fuente cambio.
                registry.record_failure(REGISTRY_KEY, "respuesta no JSON")
                raise
            registry.record_success(REGISTRY_KEY, (time.monotonic() - started) * 1000)
            return payload


def _gdelt_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    for date_format in ("%Y%m%dT%H%M%SZ", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(value, date_format).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


# Idiomas admitidos en la ingesta GDELT (UI es/en; veracidad: un titular
# en otro idioma no es legible ni verificable por el usuario).
GDELT_ALLOWED_LANGUAGES = frozenset({"english", "spanish"})


class GDELTConnector:
    """Normalize the existing GDELT client into the connector result contract."""

    def __init__(self, client: GDELTClient | None = None) -> None:
        self.client = client or GDELTClient()

    async def poll(
        self,
        query: str,
        *,
        ticker: str | None = None,
        max_records: int = 50,
    ) -> ConnectorResult:
        metadata = {"query": query, "ticker": ticker, "max_records": max_records}
        try:
            payload = await self.client.news_search(query, max_records=max_records)
            articles = payload.get("articles", []) if isinstance(payload, dict) else []
            items: list[ConnectorItem] = []
            seen: set[str] = set()
            for article in articles:
                if not isinstance(article, dict):
                    continue
                # Idioma: GDELT devuelve titulares en cualquier lengua y los
                # ru/de/... llegaban al carril macro sin poder verificarse ni
                # mostrarse con honestidad en una UI es/en. Solo se descarta
                # cuando el idioma es CONOCIDO y distinto de en/es; si GDELT
                # no informa el idioma, el artículo se conserva.
                language = str(article.get("language") or "").strip().lower()
                if language and language not in GDELT_ALLOWED_LANGUAGES:
                    continue
                url = article.get("url")
                title = " ".join(str(article.get("title") or "").split())
                key = url or title
                if not key or key in seen:
                    continue
                seen.add(key)
                items.append(
                    ConnectorItem(
                        source=str(article.get("domain") or "GDELT"),
                        title=title or "Untitled GDELT article",
                        url=url,
                        summary=" ".join(str(article.get("snippet") or "").split()),
                        published_at=_gdelt_datetime(article.get("seendate")),
                        ticker=ticker.upper() if ticker else None,
                        item_type="news",
                        external_id=url,
                        metadata={
                            "language": article.get("language"),
                            "source_country": article.get("sourcecountry"),
                            "social_image": article.get("socialimage"),
                        },
                    )
                )
            metadata["article_count"] = len(articles)
            return ConnectorResult(source="gdelt", items=items, metadata=metadata)
        except GdeltRateLimited:
            # El 429 NO degrada a failed: sube al actor, que reencola el lote
            # tras la ventana del servidor en vez de barrer contra ella.
            raise
        except Exception as exc:
            return ConnectorResult.failed("gdelt", exc, metadata=metadata)
