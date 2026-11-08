"""Cliente de la API REST de Companies House (registro mercantil del Reino Unido).

Fuente oficial y gratuita: perfil de cada sociedad, historial de presentaciones,
cuentas depositadas (API de documentos), PSC (quien controla la sociedad) y
administradores. Sirve para las filiales britanicas que no cotizan de un holding
(desglose por partes) y como respaldo de los informes de un emisor britanico.

- Autenticacion: HTTP Basic con la clave como usuario y contraseña vacia. La
  clave es un ajuste (``COMPANIES_HOUSE_API_KEY``); vacia = funcion apagada.
  Nunca se registra ni se devuelve.
- Limite de Companies House: 600 peticiones cada 5 minutos por clave. Este
  cliente lleva su propia ventana deslizante (nunca pasa de ``RATE_LIMIT`` en
  ``RATE_WINDOW_S``) y un presupuesto por uso (``max_requests``) para que una
  sola tesis no gaste la cuota de todos.
- Cada cifra se cita con la URL publica de Companies House (find-and-update),
  que abre sin clave: la ficha, el historial o el propio documento.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from typing import Any

import httpx

API_BASE_URL = "https://api.company-information.service.gov.uk"
DOCUMENT_API_HOST = "document-api.company-information.service.gov.uk"
PUBLIC_BASE_URL = "https://find-and-update.company-information.service.gov.uk"
RATE_LIMIT = 600
RATE_WINDOW_S = 300.0
DEFAULT_MAX_REQUESTS = 250
IXBRL_MIME = "application/xhtml+xml"
PDF_MIME = "application/pdf"


class CompaniesHouseError(RuntimeError):
    """Respuesta inesperada de Companies House (sin la clave en el mensaje)."""


class CompaniesHouseBudgetExceeded(CompaniesHouseError):
    """Se agoto el presupuesto de peticiones de este uso."""


def normalize_company_number(raw: Any) -> str | None:
    """'7811410' -> '07811410'; 'sc123' -> 'SC000123'. None si no parece un numero de registro."""
    text = "".join(str(raw or "").split()).upper()
    if not text:
        return None
    prefix = "".join(ch for ch in text[:2] if ch.isalpha())
    digits = text[len(prefix):]
    if not digits.isdigit() or len(prefix) + len(digits) > 8:
        return None
    return prefix + digits.zfill(8 - len(prefix))


def public_company_url(number: str) -> str:
    return f"{PUBLIC_BASE_URL}/company/{number}"


def public_filing_history_url(number: str) -> str:
    return f"{PUBLIC_BASE_URL}/company/{number}/filing-history"


def public_document_url(number: str, transaction_id: str, *, fmt: str = "pdf") -> str:
    """Documento presentado, visible sin clave (Companies House redirige al fichero)."""
    return f"{PUBLIC_BASE_URL}/company/{number}/filing-history/{transaction_id}/document?format={fmt}&download=0"


class _RateWindow:
    """Ventana deslizante compartida por proceso: nunca mas de ``limit`` en ``seconds``."""

    def __init__(self, limit: int = RATE_LIMIT, seconds: float = RATE_WINDOW_S) -> None:
        self.limit, self.seconds = limit, seconds
        self._stamps: deque[float] = deque()

    def wait_seconds(self, now: float) -> float:
        while self._stamps and now - self._stamps[0] >= self.seconds:
            self._stamps.popleft()
        if len(self._stamps) < self.limit:
            return 0.0
        return self.seconds - (now - self._stamps[0])

    def record(self, now: float) -> None:
        self._stamps.append(now)


_WINDOW = _RateWindow()


class CompaniesHouseClient:
    """Cliente asincrono. ``client`` es inyectable (los tests pasan un MockTransport)."""

    def __init__(self, api_key: str, *, client: httpx.AsyncClient | None = None,
                 max_requests: int = DEFAULT_MAX_REQUESTS, window: _RateWindow | None = None,
                 max_wait_s: float = 30.0) -> None:
        if not api_key:
            raise ValueError("Companies House necesita una clave")
        self._client = client or httpx.AsyncClient(timeout=30.0)
        self._owns_client = client is None
        self._auth = httpx.BasicAuth(api_key, "")
        self._window = window or _WINDOW
        self.max_requests = max_requests
        self.max_wait_s = max_wait_s
        self.requests_used = 0

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _throttle(self) -> None:
        if self.requests_used >= self.max_requests:
            raise CompaniesHouseBudgetExceeded(f"presupuesto de {self.max_requests} peticiones agotado")
        wait = self._window.wait_seconds(time.monotonic())
        if wait > self.max_wait_s:
            raise CompaniesHouseBudgetExceeded("limite de 600 peticiones / 5 min alcanzado")
        if wait > 0:
            await asyncio.sleep(wait)
        self._window.record(time.monotonic())
        self.requests_used += 1

    async def _get(self, url: str, *, params: dict[str, Any] | None = None,
                   accept: str = "application/json") -> httpx.Response:
        await self._throttle()
        resp = await self._client.get(url, params=params, auth=self._auth,
                                      headers={"Accept": accept}, follow_redirects=False)
        if resp.status_code == 429:
            raise CompaniesHouseBudgetExceeded("Companies House respondio 429 (limite de peticiones)")
        return resp

    async def _json(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
        url = path if path.startswith("https://") else f"{API_BASE_URL}{path}"
        resp = await self._get(url, params=params)
        if resp.status_code == 404:
            return None
        if resp.status_code != 200:
            raise CompaniesHouseError(f"Companies House {resp.status_code} en {path.split('?')[0]}")
        try:
            data = resp.json()
        except ValueError as exc:
            raise CompaniesHouseError(f"respuesta no JSON en {path.split('?')[0]}") from exc
        return data if isinstance(data, dict) else None

    # -- endpoints -------------------------------------------------------------
    async def search_companies(self, query: str, *, items: int = 20) -> list[dict[str, Any]]:
        data = await self._json("/search/companies", {"q": query, "items_per_page": items})
        return list((data or {}).get("items") or [])

    async def company_profile(self, number: str) -> dict[str, Any] | None:
        return await self._json(f"/company/{number}")

    async def filing_history(self, number: str, *, category: str | None = "accounts",
                             items: int = 25) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"items_per_page": items}
        if category:
            params["category"] = category
        data = await self._json(f"/company/{number}/filing-history", params)
        return list((data or {}).get("items") or [])

    async def persons_with_significant_control(self, number: str) -> list[dict[str, Any]]:
        data = await self._json(f"/company/{number}/persons-with-significant-control", {"items_per_page": 50})
        return list((data or {}).get("items") or [])

    async def officers(self, number: str) -> list[dict[str, Any]]:
        data = await self._json(f"/company/{number}/officers", {"items_per_page": 100})
        return list((data or {}).get("items") or [])

    async def officer_appointments(self, path: str) -> list[dict[str, Any]]:
        if not path.startswith("/officers/"):
            raise CompaniesHouseError("ruta de nombramientos no reconocida")
        data = await self._json(path, {"items_per_page": 100})
        return list((data or {}).get("items") or [])

    async def document_metadata(self, url: str) -> dict[str, Any] | None:
        if httpx.URL(url).host != DOCUMENT_API_HOST:
            raise CompaniesHouseError("el documento no es de la API de documentos de Companies House")
        return await self._json(url)

    async def document_content(self, metadata: dict[str, Any], mime: str, *, max_bytes: int = 20_000_000) -> bytes:
        """Contenido del documento en ``mime``. La API responde 302 a un enlace firmado
        (S3) que se descarga SIN la clave: el Basic solo va a Companies House."""
        url = str(((metadata.get("links") or {}).get("document")) or "")
        if httpx.URL(url).host != DOCUMENT_API_HOST:
            raise CompaniesHouseError("enlace de documento no reconocido")
        resp = await self._get(url, accept=mime)
        if resp.status_code in (301, 302, 303, 307):
            target = resp.headers.get("location") or ""
            resp = await self._client.get(target, headers={"Accept": mime})
        if resp.status_code != 200:
            raise CompaniesHouseError(f"documento {resp.status_code}")
        if len(resp.content) > max_bytes:
            raise CompaniesHouseError("documento demasiado grande")
        return resp.content


def client_from_settings(**kwargs: Any) -> CompaniesHouseClient | None:
    """Cliente con la clave de los ajustes, o None si la funcion esta apagada (clave vacia)."""
    from app.core.config import get_settings

    key = (get_settings().companies_house_api_key or "").strip()
    return CompaniesHouseClient(key, **kwargs) if key else None


__all__ = [
    "API_BASE_URL",
    "CompaniesHouseBudgetExceeded",
    "CompaniesHouseClient",
    "CompaniesHouseError",
    "IXBRL_MIME",
    "PDF_MIME",
    "PUBLIC_BASE_URL",
    "client_from_settings",
    "normalize_company_number",
    "public_company_url",
    "public_document_url",
    "public_filing_history_url",
]
