"""Motor de propuestas LLM para el libro de paper trading (item 1).

Sin broker, sin capital y sin ejecucion: el modelo propone, esta capa valida y
solo entonces ``create_proposal`` guarda la propuesta; los fills los hace el
libro con cotizaciones forward observadas.

Fail-closed. Se rechaza (``ProposalRejected``) cuando:
- no hay cotizacion fresca (<24 h) con moneda, que es el ancla de los niveles;
- el modelo no devuelve JSON valido, o cita ids de titular que no recibio;
- la entrada se aleja mas de ``MAX_ENTRY_DEVIATION`` de la cotizacion;
- los niveles no cumplen stop < entrada < objetivo (long) o el inverso (short);
- el texto no pasa ``llm_output_guard`` tras el reintento.
La cantidad no la decide el modelo: es un nocional fijo, etiquetado supuesto.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from pydantic import ValidationError

from app.llm import LLMRequest, Message, ResponseFormat, parse_json_response
from app.llm.errors import ProviderResponseError, ProviderTransportError
from app.schemas.paper_trading import PaperProposal
from app.services.llm_output_guard import LLMOutputRejected, complete_guarded
from app.services.prompt_registry import get_prompt

TRANSIENT_RETRY_PAUSE = 3.0  # segundos antes del unico reintento por error transitorio
_EMPTY_REPLY_MARKERS = ("returned no assistant message", "returned an empty assistant message")
_TRANSIENT_TRANSPORT = {"read_timeout", "connect_timeout", "write_timeout", "pool_timeout", "timeout"}


def _is_transient(exc: Exception) -> bool:
    """Respuesta vacia/sin mensaje o timeout del proveedor. Nada de salidas invalidas."""
    if isinstance(exc, ProviderTransportError):
        return exc.reason in _TRANSIENT_TRANSPORT
    if isinstance(exc, ProviderResponseError):
        return any(marker in str(exc) for marker in _EMPTY_REPLY_MARKERS)
    return False


class _TransientRetryProvider:
    """Envuelve provider.complete: UN reintento por propuesta ante error transitorio.

    Presupuesto comprobado (before_retry) y sesion liberada antes del reintento. El
    contador es de toda la propuesta, asi que un fallo de transporte intercalado entre
    dos salidas rechazadas no concede reintentos extra.
    """

    def __init__(self, inner: Any, before_retry=None) -> None:
        self._inner, self._before_retry, self._used = inner, before_retry, False

    async def complete(self, request):
        try:
            return await self._inner.complete(request)
        except (ProviderResponseError, ProviderTransportError) as exc:
            if self._used or not _is_transient(exc):
                raise
            self._used = True
            if self._before_retry is not None:
                self._before_retry()
            await asyncio.sleep(TRANSIENT_RETRY_PAUSE)
            return await self._inner.complete(request)


NOTIONAL = Decimal("1000")  # supuesto: importe simulado por propuesta, no capital real
MAX_ENTRY_DEVIATION = Decimal("0.05")
MAX_QUOTE_AGE = timedelta(hours=24)

_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "direction",
        "horizon",
        "thesis",
        "conviction",
        "entry",
        "stop",
        "target",
        "evidence_ids",
        "inference_basis",
    ],
    "properties": {
        "direction": {"type": "string", "enum": ["long", "short"]},
        "horizon": {"type": "string", "enum": ["short", "five_years"]},
        "thesis": {"type": "string"},
        "conviction": {"type": "number"},
        "entry": {"type": "number"},
        "stop": {"type": "number"},
        "target": {"type": "number"},
        "evidence_ids": {"type": "array", "items": {"type": "string"}},
        "inference_basis": {"type": "string"},
    },
}

_PROMPT = get_prompt("paper_trade_proposal", allow_remote=False)
SYSTEM = _PROMPT.text
PROPOSAL_TASK = _PROMPT.task


def _prompt():
    """i18n B: resuelve el prompt en el idioma activo de la peticion.

    La constante de modulo queda en espanol (los tests la fijan); cada
    llamada pasa por ``get_prompt`` para heredar el idioma del scope.
    """
    return get_prompt("paper_trade_proposal", allow_remote=False)



class ProposalRejected(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _fresh_quote(quote: dict | None, now: datetime) -> tuple[Decimal, str]:
    if not quote:
        raise ProposalRejected("sin_cotizacion")
    try:
        price = Decimal(str(quote.get("live_c")))
        stamp = quote.get("live_t")
        if isinstance(stamp, bool) or not isinstance(stamp, (int, float)):
            raise ProposalRejected("cotizacion_sin_fecha")
        at = datetime.fromtimestamp(stamp, UTC)
    except (InvalidOperation, ValueError, TypeError, OverflowError, OSError) as exc:
        raise ProposalRejected("cotizacion_invalida") from exc
    currency = quote.get("currency")
    if not price.is_finite() or price <= 0 or not isinstance(currency, str) or not currency.isalpha():
        raise ProposalRejected("cotizacion_invalida")
    if not timedelta(0) <= _utc(now) - at <= MAX_QUOTE_AGE:
        raise ProposalRejected("cotizacion_vieja")
    return price, currency


def _finite(value: Any) -> Decimal:
    """Numero finito o rechazo: bool, texto no numerico, NaN e inf no son niveles."""
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        raise ProposalRejected("niveles_invalidos")
    try:
        number = Decimal(str(value))
    except InvalidOperation as exc:
        raise ProposalRejected("niveles_invalidos") from exc
    if not number.is_finite():
        raise ProposalRejected("niveles_invalidos")
    return number


def build_request(
    ticker: str,
    price: Decimal,
    currency: str,
    headlines: list[dict],
    momentum: dict | None,
    thesis: dict | None = None,
) -> LLMRequest:
    payload = {
        "ticker": ticker.upper(),
        "cotizacion": {"precio": str(price), "moneda": currency},
        "momentum": momentum or None,
        "titulares": [
            {"id": h["id"], "titulo": h["title"], "fecha": h.get("published_at"), "medio": h.get("source")}
            for h in headlines
        ],
        # Copia de paper_thesis_anchor.prompt_context: solo campos publicables.
        "tesis_vigente": thesis or None,
    }
    return LLMRequest(
        messages=[
            Message("system", _prompt().text),
            Message("user", json.dumps(payload, ensure_ascii=False, default=str)),
        ],
        task=_prompt().task,
        temperature=0.2,
        max_tokens=900,
        response_format=ResponseFormat.json_schema(_SCHEMA, name="paper_proposal"),
        metadata=_prompt().trace_metadata(),
    )


def validate_output(
    raw: dict,
    *,
    ticker: str,
    price: Decimal,
    headline_ids: set[str],
    now: datetime,
    currency: str,
    thesis_id: str | None = None,
) -> PaperProposal:
    if not isinstance(raw, dict):
        raise ProposalRejected("json_invalido")
    evidence = raw.get("evidence_ids")
    # La tesis recibida puede citarse, pero no sustituye a un titular fechado.
    allowed = headline_ids | ({thesis_id} if thesis_id else set())
    if (
        not isinstance(evidence, list)
        or not evidence
        or any(not isinstance(e, str) or e not in allowed for e in evidence)
        or not any(e in headline_ids for e in evidence)
    ):
        raise ProposalRejected("evidencia_no_recibida")
    inference = raw.get("inference_basis")
    if not isinstance(inference, str) or len(inference.strip()) < 10:
        raise ProposalRejected("sin_base_de_inferencia")
    thesis = raw.get("thesis")
    if not isinstance(thesis, str) or not thesis.strip():
        raise ProposalRejected("tesis_invalida")
    conviction = _finite(raw.get("conviction"))
    entry = _finite(raw.get("entry"))
    stop = _finite(raw.get("stop"))
    target = _finite(raw.get("target"))
    if conviction <= 0:
        raise ProposalRejected("sin_conviccion")
    if entry <= 0:
        raise ProposalRejected("niveles_invalidos")
    if abs(entry - price) / price > MAX_ENTRY_DEVIATION:
        raise ProposalRejected("entrada_lejos_de_cotizacion")
    basis = f"{inference.strip()} Evidencia: {', '.join(evidence)}."
    digest = hashlib.sha256(f"{thesis}|{entry}|{stop}|{target}".encode()).hexdigest()[:10]
    try:
        return PaperProposal(
            proposal_key=f"llm:{ticker.upper()}:{_utc(now):%Y%m%d}:{digest}",
            ticker=ticker,
            direction=raw.get("direction"),
            horizon=raw.get("horizon"),
            thesis=thesis,
            conviction=conviction,
            proposed_entry=entry,
            stop=stop,
            target=target,
            quantity=(NOTIONAL / entry),
            inference_basis=basis,
            currency=currency,
        )
    except (ValidationError, ValueError, InvalidOperation, TypeError) as exc:
        raise ProposalRejected("niveles_invalidos") from exc


async def propose(
    provider: Any,
    ticker: str,
    *,
    quote: dict | None,
    headlines: list[dict],
    momentum: dict | None = None,
    thesis: dict | None = None,
    now: datetime | None = None,
    on_response=None,
    before_retry=None,
) -> PaperProposal:
    """Pide una propuesta al modelo y la valida. No persiste."""
    now = now or datetime.now(UTC)
    price, currency = _fresh_quote(quote, now)
    if not headlines:
        raise ProposalRejected("sin_titulares")
    request = build_request(ticker, price, currency, headlines, momentum, thesis)
    # El reintento transitorio vive en el limite de provider.complete: no reinicia
    # complete_guarded, asi que el unico reintento de salida del guard no se resetea.
    guarded_provider = _TransientRetryProvider(provider, before_retry)
    try:
        guarded = await complete_guarded(
            guarded_provider, request, source="llm_proposal", on_response=on_response, before_retry=before_retry
        )
    except LLMOutputRejected as exc:
        raise ProposalRejected(f"salida_rechazada:{','.join(exc.reasons)}") from exc
    try:
        raw = parse_json_response(guarded.response.text)
    except Exception as exc:  # noqa: BLE001 - JSON roto = rechazo, no excepcion al llamador
        raise ProposalRejected("json_invalido") from exc
    return validate_output(
        raw, ticker=ticker, price=price, headline_ids={h["id"] for h in headlines}, now=now,
        currency=currency, thesis_id=(thesis or {}).get("id"),
    )
