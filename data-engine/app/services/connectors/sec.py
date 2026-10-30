from __future__ import annotations

import asyncio
import copy
import logging
import re
import threading
import time
from datetime import UTC, datetime
from pathlib import PurePosixPath
from urllib.parse import urlparse

import httpx

from app.core.config import get_settings
from app.services.connectors import sec_edgar
from app.services.connectors.base import ConnectorItem, ConnectorResult, retry_after_seconds
from app.services.sec_ticker import CikIndex

logger = logging.getLogger(__name__)

# Filings que declaran un cierre de ejercicio anual. Las enmiendas (10-K/A)
# re-declaran el mismo cierre y sirven de ancla para valores re-expresados.
ANNUAL_REPORT_FORMS = {"10-K", "10-K/A", "20-F", "20-F/A", "40-F", "40-F/A"}


# ---- Estado compartido de proceso (la SEC limita por IP, no por instancia) ----

_CACHE_MAX_ENTRIES = 256
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}
_BACKOFF_BASE_SECONDS = 1.0
_BACKOFF_CAP_SECONDS = 60.0

_pacing_lock = threading.Lock()
_next_slot_at = 0.0
_cache_lock = threading.Lock()
# url -> (expira_monotonic, payload). Solo respuestas JSON correctas.
_json_cache: dict[str, tuple[float, dict]] = {}
# Indice ticker -> CIK ligado a la entrada de cache del mapa de la SEC de la
# que salio: se reconstruye solo cuando esa entrada cambia o caduca.
_cik_index: tuple[tuple[float, dict] | None, CikIndex] | None = None


EFTS_FALLBACK_SOURCE = "efts-full-text-search"
EFTS_PARTIAL_NOTE = (
    "Cobertura parcial: listado reconstruido desde EDGAR full-text search "
    "(solo los documentos mas recientes, sin historico completo ni isInlineXBRL)."
)
_TRAILING_PAREN = re.compile(r"\s*\([^()]*\)\s*$")


class AnchorMap(dict):
    """{accession: reportDate} con la procedencia del listado.

    Se comporta como un dict normal; ``partial``/``source`` dicen si vino del
    fallback EFTS (cobertura parcial) para que el consumidor no lo trate como
    el historico completo.
    """

    partial: bool = False
    source: str = "sec-submissions"


def _efts_company_name(source: dict, cik: str) -> str | None:
    """Nombre del CIK consultado: por POSICION en ``ciks``, nunca el primero.

    Un hit EFTS puede listar varios CIKs (p. ej. el filer y un insider);
    ``display_names`` va alineado con ``ciks``.
    """
    ciks = [str(c).zfill(10) for c in (source.get("ciks") or [])]
    names = source.get("display_names") or []
    if cik not in ciks:
        return None
    index = ciks.index(cik)
    if index >= len(names):
        return None
    name = str(names[index]).strip()
    while True:
        stripped = _TRAILING_PAREN.sub("", name)
        if stripped == name:
            break
        name = stripped
    return name.strip() or None


def reset_sec_client_state() -> None:
    """Solo para tests: vacia cache y reloj compartido."""
    global _next_slot_at, _cik_index
    _cik_index = None
    with _pacing_lock:
        _next_slot_at = 0.0
    with _cache_lock:
        _json_cache.clear()


def _cache_get(url: str) -> dict | None:
    with _cache_lock:
        hit = _json_cache.get(url)
        if hit is None:
            return None
        if hit[0] <= time.monotonic():
            _json_cache.pop(url, None)
            return None
        # Copia: el llamador puede mutar el dict (p. ej. al normalizar) y eso
        # no debe contaminar a los siguientes lectores de la misma URL.
        return copy.deepcopy(hit[1])


def _cache_entry(url: str) -> tuple[float, dict] | None:
    """Entrada viva de la cache SIN copiar (solo para lectura interna)."""
    with _cache_lock:
        hit = _json_cache.get(url)
        if hit is None or hit[0] <= time.monotonic():
            return None
        return hit


def _cache_put(url: str, payload: dict, ttl: float) -> None:
    if ttl <= 0:
        return
    with _cache_lock:
        if len(_json_cache) >= _CACHE_MAX_ENTRIES:
            _json_cache.pop(next(iter(_json_cache)), None)
        _json_cache[url] = (time.monotonic() + ttl, copy.deepcopy(payload))


class SECClient:
    submissions_url = "https://data.sec.gov/submissions"
    companyfacts_url = "https://data.sec.gov/api/xbrl/companyfacts"
    ticker_map_url = "https://www.sec.gov/files/company_tickers.json"
    archives_url = "https://www.sec.gov/Archives/edgar/data"
    efts_url = "https://efts.sec.gov/LATEST/search-index"

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        *,
        user_agent: str | None = None,
        requests_per_second: float = 8,
        use_cache: bool | None = None,
        max_retries: int | None = None,
    ) -> None:
        self.settings = get_settings()
        self.client = client
        self.user_agent = user_agent or self.settings.sec_user_agent
        # Cache solo contra la SEC real: un cliente httpx inyectado (tests,
        # harness de evals con MockTransport) sirve fixtures distintos para la
        # MISMA URL y compartirlos entre casos los contaminaria. Se puede
        # forzar con use_cache=True/False.
        self.use_cache = (client is None) if use_cache is None else use_cache
        self.max_retries = (
            int(self.settings.sec_max_retries) if max_retries is None else max(0, max_retries)
        )
        self._minimum_interval = 1 / max(0.1, min(requests_per_second, 10))
        # Ultimo payload de submissions servido a ESTA instancia: las vistas del
        # indice (anclas anuales, accessions listados) se derivan de la MISMA
        # respuesta, sin duplicar la peticion. Por instancia, nunca compartido.
        self._last_submissions_payload: dict | None = None

    @property
    def headers(self) -> dict[str, str]:
        return {
            "User-Agent": self.user_agent,
            "Accept-Encoding": "gzip, deflate",
            "Accept": "application/json, text/html, */*",
        }

    async def _throttle(self) -> None:
        """Reserva un hueco en el reloj COMPARTIDO del proceso.

        El hueco se reserva bajo lock y se espera fuera de el: asi N tareas
        (o N instancias de SECClient, o varios event loops) salen separadas
        por el intervalo y ninguna bloquea el loop.
        """
        global _next_slot_at
        with _pacing_lock:
            now = time.monotonic()
            slot = max(now, _next_slot_at)
            _next_slot_at = slot + self._minimum_interval
        delay = slot - now
        if delay > 0:
            await asyncio.sleep(delay)

    async def _get(self, url: str) -> httpx.Response:
        """GET con ritmo compartido y reintentos con backoff exponencial.

        Reintenta 429/5xx y errores de red/timeout respetando Retry-After
        (con tope). 401/403/404 no se reintentan: un 403 es un bloqueo de IP
        que reintentar solo empeora; lo gestiona el fallback (mirror/EFTS).
        """
        max_retries = self.max_retries
        delay = _BACKOFF_BASE_SECONDS
        for attempt in range(max_retries + 1):
            await self._throttle()
            response: httpx.Response | None = None
            try:
                if self.client is not None:
                    response = await self.client.get(url, headers=self.headers)
                else:
                    async with httpx.AsyncClient(
                        timeout=30,
                        headers=self.headers,
                        follow_redirects=True,
                    ) as client:
                        response = await client.get(url)
            except httpx.TransportError as exc:  # incluye timeouts
                if attempt >= max_retries:
                    raise
                logger.warning("SEC red/timeout (%s), reintento %d", type(exc).__name__, attempt + 1)
                await asyncio.sleep(min(delay, _BACKOFF_CAP_SECONDS))
                delay *= 2
                continue
            if response.status_code in _RETRYABLE_STATUS and attempt < max_retries:
                wait = retry_after_seconds(response, cap=_BACKOFF_CAP_SECONDS) or delay
                logger.warning("SEC %s en %s, reintento %d en %.1fs", response.status_code, url, attempt + 1, wait)
                await asyncio.sleep(min(wait, _BACKOFF_CAP_SECONDS))
                delay *= 2
                continue
            response.raise_for_status()
            return response
        raise RuntimeError("unreachable")  # pragma: no cover

    async def _get_json(self, url: str) -> dict:
        snapshot = sec_edgar.read_snapshot_for(url)
        if snapshot is not None:
            return snapshot
        cached = _cache_get(url) if self.use_cache else None
        if cached is not None:
            return cached
        try:
            payload = (await self._get(url)).json()
            if self.use_cache:
                _cache_put(url, payload, float(self.settings.sec_cache_ttl_seconds))
            return payload
        except httpx.HTTPStatusError as exc:
            # La SEC bloquea IPs de datacenter con 403: el mirror HF sirve el
            # mismo JSON oficial. Un 404 de la SEC es un fallo de DATO y
            # nunca se enmascara como fallo de transporte.
            if exc.response is not None and exc.response.status_code in {401, 403}:
                return await sec_edgar.mirror_get_json(url, direct_error=exc)
            raise

    async def ticker_map(self) -> dict:
        return await self._get_json(self.ticker_map_url)

    async def cik_for_ticker(self, ticker: str) -> str | None:
        ticker = ticker.upper()
        manifest_cik = sec_edgar.manifest_cik(ticker)
        if manifest_cik:
            return manifest_cik
        # EDGAR nombra las clases con guion (BRK-B) y el master con punto
        # (BRK.B): el match exacto nunca casa para esos emisores. El
        # fallback normalizado exige match único (fail closed).
        return (await self._ticker_index()).lookup(ticker)

    async def _ticker_index(self) -> CikIndex:
        """Indice del mapa de la SEC, uno por entrada de cache.

        Antes cada ``cik_for_ticker`` hacia deepcopy del mapa (~10.000
        emisores) y lo recorria entero: ~35 ms por ticker, ~0,9 s por carga
        del calendario de catalizadores con la cache ya caliente.
        """
        global _cik_index
        entry = _cache_entry(self.ticker_map_url) if self.use_cache else None
        current = _cik_index
        if entry is not None and current is not None and current[0] is entry:
            return current[1]
        mapping = await self.ticker_map()
        index = CikIndex(
            (str(item.get("ticker", "")), str(item["cik_str"]).zfill(10))
            for item in mapping.values()
            if isinstance(item, dict) and item.get("cik_str") is not None
        )
        if self.use_cache:
            _cik_index = (_cache_entry(self.ticker_map_url), index)
        return index

    async def submissions(self, cik: str) -> dict:
        padded = str(cik).zfill(10)
        try:
            return await self._get_json(f"{self.submissions_url}/CIK{padded}.json")
        except httpx.HTTPStatusError as exc:
            # 404 = dato inexistente: nunca se enmascara con otra fuente.
            if exc.response is not None and exc.response.status_code == 404:
                raise
            direct_error: Exception = exc
        except Exception as exc:  # noqa: BLE001 - mirror caido/sin config, red, etc.
            direct_error = exc
        if not getattr(self.settings, "sec_efts_fallback_enabled", True):
            raise direct_error
        try:
            return await self.efts_submissions(padded)
        except Exception as efts_exc:  # noqa: BLE001
            logger.warning("Fallback EFTS fallo para CIK%s: %s", padded, efts_exc)
            raise direct_error from efts_exc

    async def efts_submissions(self, cik: str, *, max_pages: int = 3) -> dict:
        """Reconstruye un ``submissions`` minimo desde EDGAR full-text search.

        Fallback cuando data.sec.gov/submissions falla. Es dato oficial de la
        SEC pero PARCIAL: solo los ultimos ~``max_pages * 100`` documentos, sin
        ``isInlineXBRL`` ni ficheros historicos. El payload lo declara en
        ``_fallback`` para que nadie lo trate como el historico completo.
        """
        padded = str(cik).zfill(10)
        filings: dict[str, dict] = {}
        name: str | None = None
        for page in range(max_pages):
            url = f"{self.efts_url}?ciks={padded}&size=100&from={page * 100}"
            payload = await self._get_json(url)
            hits = (payload.get("hits") or {}).get("hits") or []
            for hit in hits:
                source = hit.get("_source") or {}
                accession = source.get("adsh")
                if not accession:
                    continue
                doc_id = str(hit.get("_id") or "")
                document = doc_id.split(":", 1)[1] if ":" in doc_id else ""
                sequence = source.get("sequence") or 99
                current = filings.get(accession)
                if current is not None and current["sequence"] <= sequence:
                    continue
                if name is None:
                    name = _efts_company_name(source, padded)
                filings[accession] = {
                    "sequence": sequence,
                    "form": source.get("form") or source.get("file_type"),
                    "filingDate": source.get("file_date"),
                    "reportDate": source.get("period_ending"),
                    "primaryDocument": document,
                }
            if len(hits) < 100:
                break
        if not filings:
            raise RuntimeError(f"EFTS sin filings para CIK{padded}")
        ordered = sorted(
            filings.items(), key=lambda kv: kv[1].get("filingDate") or "", reverse=True
        )
        recent = {
            "accessionNumber": [a for a, _ in ordered],
            "form": [v["form"] for _, v in ordered],
            "filingDate": [v["filingDate"] for _, v in ordered],
            "reportDate": [v["reportDate"] or "" for _, v in ordered],
            "primaryDocument": [v["primaryDocument"] for _, v in ordered],
            "isInlineXBRL": [None for _ in ordered],
        }
        return {
            "cik": padded,
            "name": name,
            "filings": {"recent": recent, "files": []},
            "_fallback": EFTS_FALLBACK_SOURCE,
            "_fallback_note": EFTS_PARTIAL_NOTE,
        }

    async def annual_report_anchors(self, cik: str) -> AnchorMap:
        """{accessionNumber: reportDate} de los filings anuales del emisor.

        Es la evidencia de calendario fiscal a nivel de filing: cada 10-K
        declara en portada el cierre del ejercicio que reporta. La ingesta
        anual ancla cada hecho a su filing por `accn` en vez de inferir el
        calendario por moda de hechos (una moda es envenenable con ruido TTM
        coherentemente distribuido; una fecha de portada, no). Fusiona
        `recent` con los ficheros historicos de submissions; si un fichero
        historico falla se sigue con cobertura parcial (visible en el
        resultado de la ingesta), nunca se sustituye por inferencia.
        """
        payload = await self.submissions(cik)
        self._last_submissions_payload = payload
        filings = payload.get("filings", {})
        anchors = AnchorMap()
        if payload.get("_fallback"):
            anchors.partial = True
            anchors.source = str(payload["_fallback"])

        def _absorb(recent: dict) -> None:
            forms = recent.get("form", [])
            accessions = recent.get("accessionNumber", [])
            report_dates = recent.get("reportDate", [])
            for index, accession in enumerate(accessions):
                form = str(forms[index]) if index < len(forms) else ""
                if form not in ANNUAL_REPORT_FORMS:
                    continue
                report_date = (
                    str(report_dates[index]) if index < len(report_dates) else ""
                )
                if accession and report_date:
                    anchors[str(accession)] = report_date

        _absorb(filings.get("recent", {}))
        for extra in filings.get("files", []) or []:
            name = extra.get("name") if isinstance(extra, dict) else None
            if not name:
                continue
            try:
                _absorb(await self._get_json(f"{self.submissions_url}/{name}"))
            except Exception:  # noqa: BLE001 - cobertura parcial > romper la ingesta
                continue
        return anchors

    async def index_accessions(self, cik: str) -> set[str]:
        """Todos los accessionNumber listados en el indice submissions del emisor.

        Es la verificacion minima de procedencia: un hecho que cita un filing
        que el indice ya no lista (salio de la ventana `recent` y de los
        historicos) no es verificable y no puede entrar como OFICIAL. Misma
        tolerancia que `annual_report_anchors`: un fichero historico caido
        deja cobertura parcial, nunca se sustituye por inferencia.
        """
        payload = self._last_submissions_payload or await self.submissions(cik)
        filings = payload.get("filings", {})
        accessions: set[str] = set()

        def _absorb(recent: dict) -> None:
            for accession in recent.get("accessionNumber", []) or []:
                if accession:
                    accessions.add(str(accession))

        _absorb(filings.get("recent", {}))
        for extra in filings.get("files", []) or []:
            name = extra.get("name") if isinstance(extra, dict) else None
            if not name:
                continue
            try:
                _absorb(await self._get_json(f"{self.submissions_url}/{name}"))
            except Exception:  # noqa: BLE001 - cobertura parcial > romper la ingesta
                continue
        return accessions

    async def company_facts(self, cik: str) -> dict:
        padded = str(cik).zfill(10)
        return await self._get_json(f"{self.companyfacts_url}/CIK{padded}.json")

    @classmethod
    def filing_index_url(cls, cik: str, accession_number: str) -> str:
        cik_number = str(int(str(cik)))
        accession = accession_number.replace("-", "")
        if not accession.isdigit():
            raise ValueError("SEC accession number must contain only digits and hyphens")
        return f"{cls.archives_url}/{cik_number}/{accession}/"

    @classmethod
    def filing_document_url(
        cls,
        cik: str,
        accession_number: str,
        primary_document: str,
    ) -> str:
        filename = PurePosixPath(primary_document).name
        if not filename or filename in {".", ".."}:
            raise ValueError("SEC primary document filename is required")
        return f"{cls.filing_index_url(cik, accession_number)}{filename}"

    async def recent_filings(
        self,
        cik: str,
        *,
        forms: set[str] | list[str] | tuple[str, ...] | None = None,
        limit: int = 40,
        ticker: str | None = None,
    ) -> ConnectorResult:
        metadata = {
            "cik": str(cik).zfill(10),
            "ticker": ticker,
            "forms": sorted(forms) if forms else None,
        }
        try:
            payload = await self.submissions(cik)
            recent = payload.get("filings", {}).get("recent", {})
            fallback = payload.get("_fallback")
            if fallback:
                metadata["source_fallback"] = fallback
                metadata["partial_coverage"] = True
                metadata["coverage_note"] = payload.get("_fallback_note") or EFTS_PARTIAL_NOTE
            allowed_forms = {form.upper() for form in forms} if forms else None
            accessions = recent.get("accessionNumber", [])
            items: list[ConnectorItem] = []
            if limit <= 0:
                return ConnectorResult(source="sec", items=[], metadata=metadata)
            for index, accession in enumerate(accessions):
                form = self._column(recent, "form", index)
                if allowed_forms and str(form).upper() not in allowed_forms:
                    continue
                primary_document = self._column(recent, "primaryDocument", index)
                if not primary_document:
                    url = self.filing_index_url(cik, str(accession))
                else:
                    url = self.filing_document_url(cik, str(accession), str(primary_document))
                filing_date = self._column(recent, "filingDate", index)
                report_date = self._column(recent, "reportDate", index)
                # Titular en español, sin ticker ni fecha: la UI los muestra
                # en campos propios (columna ticker, fecha del evento) y el
                # titular no debe repetirlos (quick win UX 4). El summary
                # queda vacío: la frase ES ya es el titular; un resumen
                # adicional duplicaría el texto en la ingesta de noticias.
                # headline_from_source=False: la SEC no publica un titular
                # para el filing, este texto ES de display creado por GerarAI
                # y NO debe persistir como source_headline (procedencia).
                title = f"{form or 'filing'} presentado ante la SEC"
                items.append(
                    ConnectorItem(
                        source="SEC",
                        title=title,
                        url=url,
                        summary="",
                        published_at=self._filing_datetime(filing_date),
                        ticker=ticker.upper() if ticker else None,
                        item_type="filing",
                        headline_from_source=False,
                        external_id=str(accession),
                        metadata={
                            "cik": str(cik).zfill(10),
                            "accession_number": accession,
                            "form": form,
                            "filing_date": filing_date,
                            "report_date": report_date,
                            "primary_document": primary_document,
                            # Apartados declarados del 8-K ("2.02, 9.01"): sin
                            # texto completo son lo unico veraz que mostrar.
                            "items": self._column(recent, "items", index),
                            "is_inline_xbrl": self._column(recent, "isInlineXBRL", index),
                            **(
                                {"source_fallback": fallback, "partial_coverage": True}
                                if fallback
                                else {}
                            ),
                        },
                    )
                )
                if len(items) >= limit:
                    break
            metadata["company_name"] = payload.get("name")
            return ConnectorResult(source="sec", items=items, metadata=metadata)
        except Exception as exc:
            return ConnectorResult.failed("sec", exc, metadata=metadata)

    async def filing_document(self, url: str) -> tuple[bytes, str | None]:
        """Download a filing with the same SEC identity and request throttle."""

        hostname = urlparse(url).hostname or ""
        if hostname.lower() not in {"sec.gov", "www.sec.gov"}:
            raise ValueError("SEC filing URL must use sec.gov")
        response = await self._get(url)
        return response.content, response.headers.get("content-type")

    async def filing_document_head(self, url: str, max_bytes: int = 32_768) -> bytes:
        """Primeros ``max_bytes`` de un documento de sec.gov (misma identidad y ritmo).

        Los exhibits 99.x de resultados pesan varios MB y aqui solo hace falta el encabezado:
        se lee en streaming y se corta la conexion al llegar al tope. Sin reintentos: un fallo
        se propaga y el llamante lo trata como no disponible, nunca como ausencia.
        """

        hostname = urlparse(url).hostname or ""
        if hostname.lower() not in {"sec.gov", "www.sec.gov"}:
            raise ValueError("SEC filing URL must use sec.gov")
        await self._throttle()

        async def _read(client: httpx.AsyncClient) -> bytes:
            async with client.stream("GET", url, headers=self.headers) as response:
                response.raise_for_status()
                chunks: list[bytes] = []
                total = 0
                async for chunk in response.aiter_bytes():
                    chunks.append(chunk)
                    total += len(chunk)
                    if total >= max_bytes:
                        break
                return b"".join(chunks)[:max_bytes]

        if self.client is not None:
            return await _read(self.client)
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            return await _read(client)

    @staticmethod
    def _column(recent: dict, name: str, index: int):
        values = recent.get(name, [])
        return values[index] if index < len(values) else None

    @staticmethod
    def _filing_datetime(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=UTC)
        except ValueError:
            return None

