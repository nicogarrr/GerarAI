import asyncio
import logging
import re
from xml.etree import ElementTree  # nosec B314  # stdlib solo para tipos (Element) y ParseError: defusedxml no los exporta; el parseo usa defusedxml

import httpx

# XML externo (servicio web de IBKR): defusedxml solo para PARSEAR.
from defusedxml import ElementTree as DefusedElementTree

from app.core.config import get_settings

_FLEX_URL_RE = re.compile(r"https://ndcdyn\.interactivebrokers\.com[^\s\"']+")
_FLEX_T_PARAM_RE = re.compile(r"([?&]t=)[^&\s\"']+")


class _FlexTokenRedactor(logging.Filter):
    """Redacta el token Flex en los logs de httpx: su request logging incluye la URL completa.

    Cubre TODAS las apariciones del parametro t= dentro de la URL del Flex
    Web Service (una URL con ?t=A&t=B no deja ninguna copia en claro).
    """

    @staticmethod
    def _redact_url(match: "re.Match[str]") -> str:
        return _FLEX_T_PARAM_RE.sub(r"\1***", match.group(0))

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # defensivo: un record roto no debe romper el logging
            return True
        redacted = _FLEX_URL_RE.sub(self._redact_url, message)
        if redacted != message:
            record.msg = redacted
            record.args = ()
        return True


logging.getLogger("httpx").addFilter(_FlexTokenRedactor())


def _safe_code(code: str | None) -> str:
    """Solo el codigo numerico de IBKR; nunca texto libre del servidor (puede reflejar el token)."""
    text = (code or "").strip()
    return text if text.isdigit() and len(text) <= 6 else "n/d"


class IBKRFlexError(RuntimeError):
    """Error del Flex Web Service sin URL ni parametros: el token viaja en la query string."""


# Codigos de IBKR que significan "vuelve a pedirlo en unos segundos".
_RETRY_CODES = {"1001", "1004", "1005", "1006", "1007", "1008", "1009", "1019", "1021"}


class IBKRFlexClient:
    send_url = "https://ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService/SendRequest"
    get_url = "https://ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService/GetStatement"
    poll_attempts = 6
    poll_delay_seconds = 10.0

    def __init__(self, *, token: str | None = None, query_id: str | None = None) -> None:
        self.settings = get_settings()
        # Explicit credentials never fall back to another tenant's global key.
        self._token = token
        self._query_id = query_id

    @property
    def token(self) -> str | None:
        return self.settings.ibkr_flex_token if self._token is None else self._token

    @property
    def query_id(self) -> str | None:
        return self.settings.ibkr_flex_query_id if self._query_id is None else self._query_id

    def configured(self) -> bool:
        return bool(self.token and self.query_id)

    def _require_config(self) -> None:
        if not self.configured():
            raise RuntimeError("IBKR_FLEX_TOKEN and IBKR_FLEX_QUERY_ID are not configured")

    async def _get(self, url: str, params: dict[str, str], timeout: float) -> str:
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.get(url, params=params)
                response.raise_for_status()
                return response.text
        except httpx.HTTPStatusError as exc:
            # str(exc) lleva la URL completa, token incluido.
            raise IBKRFlexError(f"IBKR Flex HTTP {exc.response.status_code}") from None
        except httpx.HTTPError as exc:
            raise IBKRFlexError(f"IBKR Flex network error: {type(exc).__name__}") from None

    @staticmethod
    def _status(text: str) -> tuple[str | None, str | None, str | None]:
        try:
            root = DefusedElementTree.fromstring(text)
        except ElementTree.ParseError:
            return None, None, None
        return root.findtext(".//Status"), root.findtext(".//ErrorCode"), root.findtext(".//ErrorMessage")

    async def request_statement(self, from_date: str | None = None, to_date: str | None = None) -> str:
        """``from_date``/``to_date`` (yyyyMMdd) sustituyen el periodo de la query.

        IBKR exige ambas, un rango de como mucho 366 dias y un ``to_date`` ya cerrado
        (dia habil pasado); sin ellas la query devuelve su periodo por defecto.
        """
        self._require_config()
        params = {
            "t": self.token,
            "q": self.query_id,
            "v": "3",
        }
        if from_date or to_date:
            if not (from_date and to_date):
                raise IBKRFlexError("IBKR Flex range needs both from_date and to_date")
            params["fd"] = from_date
            params["td"] = to_date
        text = await self._get(self.send_url, params, 30)
        status, code, message = self._status(text)
        if status != "Success":
            raise IBKRFlexError(f"IBKR Flex request failed (code {_safe_code(code)})")
        root = DefusedElementTree.fromstring(text)
        reference_code = root.findtext(".//ReferenceCode")
        if not reference_code:
            raise IBKRFlexError("IBKR Flex did not return a ReferenceCode")
        return reference_code

    async def fetch_statement(self, reference_code: str) -> str:
        self._require_config()
        params = {"t": self.token, "q": reference_code, "v": "3"}
        last = "sin respuesta"
        for attempt in range(self.poll_attempts):
            text = await self._get(self.get_url, params, 60)
            status, code, message = self._status(text)
            if status is None:
                # El extracto real no trae <Status>: es FlexQueryResponse.
                return text
            last = f"code {_safe_code(code)}"
            if code not in _RETRY_CODES:
                raise IBKRFlexError(f"IBKR Flex statement failed ({last})")
            if attempt + 1 < self.poll_attempts:
                await asyncio.sleep(self.poll_delay_seconds)
        raise IBKRFlexError(f"IBKR Flex statement not ready ({last})")

    async def fetch_range_xml(self, from_date: str, to_date: str) -> str:
        reference_code = await self.request_statement(from_date, to_date)
        return await self.fetch_statement(reference_code)

    async def fetch_latest_xml(self) -> str:
        reference_code = await self.request_statement()
        return await self.fetch_statement(reference_code)
