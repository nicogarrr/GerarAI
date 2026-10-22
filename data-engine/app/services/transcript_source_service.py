"""Obtencion reproducible de texto de transcripciones desde fuentes IR oficiales.

- Solo https y solo hosts de IR en lista blanca (ampliable por entorno
  COMMITMENT_TRANSCRIPT_HOSTS, separada por comas). Aplica tambien a redirects.
- SSRF/IP privadas/limite de bytes: los resuelve public_fetch (IP fijada).
- Solo PDF (magic %PDF), tope de paginas y de bytes. Texto extraido con pypdf.
- El texto se devuelve al llamador para extraer citas cortas; NO se persiste.
- No establece licencia de redistribucion: no republicar el texto.
"""

from __future__ import annotations

import os
import re
from datetime import date
from io import BytesIO
from urllib.parse import urlparse

from app.services.public_fetch import fetch_public_url

DEFAULT_HOSTS = frozenset(
    {"s21.q4cdn.com", "investor.atmeta.com", "bn.brookfield.com"}
)
MAX_BYTES = 8 * 1024 * 1024
MAX_PAGES = 80
TIMEOUT_SECONDS = 25.0


class TranscriptSourceError(ValueError):
    pass


def allowed_hosts() -> set[str]:
    extra = {
        h.strip().lower()
        for h in os.environ.get("COMMITMENT_TRANSCRIPT_HOSTS", "").split(",")
        if h.strip()
    }
    return set(DEFAULT_HOSTS) | extra


def is_allowed_source(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme == "https" and (parsed.hostname or "").lower() in allowed_hosts()


MAX_TEXT_CHARS = 1_500_000
_TZ_TOKENS = frozenset({"ET", "PT", "CT", "MT", "EST", "EDT", "PST", "PDT", "CST", "CDT", "UTC", "GMT", "CET", "CEST", "BST"})
_MONTHS = {m: i for i, m in enumerate(
    ["january","february","march","april","may","june","july","august","september","october","november","december"], 1)}


def observe_header(text: str) -> dict:
    """Lee SOLO la cabecera del texto: ticker entre parentesis y fecha. Observado, no verificado."""
    head = " ".join(text[:1200].split())
    ticker = next(
        (
            m
            for m in re.finditer(r"\(([A-Z][A-Z0-9.\-]{0,9})\)", head)
            if m.group(1) not in _TZ_TOKENS
        ),
        None,
    )
    date_m = re.search(
        r"\b(January|February|March|April|May|June|July|August|September|October|November|December)"
        r"\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(20\d{2})\b",
        head,
        re.I,
    )
    observed_date = None
    if date_m:
        try:
            observed_date = date(int(date_m.group(3)), _MONTHS[date_m.group(1).lower()], int(date_m.group(2)))
        except ValueError:
            observed_date = None
    return {"ticker": ticker.group(1) if ticker else None, "call_date": observed_date}


def check_source(text: str, *, ticker: str, call_date: date) -> str:
    """header_matches | header_unreadable. Lanza si la cabecera CONTRADICE ticker o fecha."""
    seen = observe_header(text)
    if seen["ticker"] and seen["ticker"].upper() != ticker.upper():
        raise TranscriptSourceError(f"La cabecera del documento indica {seen['ticker']}, no {ticker.upper()}")
    if seen["call_date"] and seen["call_date"] != call_date:
        raise TranscriptSourceError(
            f"La cabecera indica fecha {seen['call_date'].isoformat()}, no {call_date.isoformat()}"
        )
    if seen["ticker"] and seen["call_date"]:
        return "header_matches"
    return "header_unreadable"


def fetch_transcript_text(url: str) -> str:
    if not is_allowed_source(url):
        raise TranscriptSourceError("Fuente no permitida: solo https y hosts IR autorizados")
    try:
        content, _ctype, _final = fetch_public_url(
            url, max_bytes=MAX_BYTES, timeout=TIMEOUT_SECONDS, allowed_url=is_allowed_source
        )
    except ValueError as exc:
        raise TranscriptSourceError(str(exc)) from exc
    except Exception as exc:  # red/HTTP: error acotado, sin detalle interno
        raise TranscriptSourceError("No se pudo descargar la fuente oficial") from exc
    if not content.startswith(b"%PDF"):
        raise TranscriptSourceError("La fuente no es un PDF (HTML aun no soportado)")
    from pypdf import PdfReader

    try:
        reader = PdfReader(BytesIO(content))
        if len(reader.pages) > MAX_PAGES:
            raise TranscriptSourceError(f"PDF con mas de {MAX_PAGES} paginas")
        chunks: list[str] = []
        total = 0
        for page in reader.pages:
            piece = page.extract_text() or ""
            total += len(piece)
            if total > MAX_TEXT_CHARS:
                raise TranscriptSourceError("Texto extraido demasiado grande")
            chunks.append(piece)
        text = "\n".join(chunks)
    except TranscriptSourceError:
        raise
    except Exception as exc:
        raise TranscriptSourceError("No se pudo extraer texto del PDF") from exc
    if len(text.split()) < 200:
        raise TranscriptSourceError("Texto extraido insuficiente (PDF escaneado o vacio)")
    return text


_LAST_CALL: dict[int, float] = {}
THROTTLE_SECONDS = 20.0


def throttle(key: int) -> bool:
    """Una descarga cada THROTTLE_SECONDS por empresa y proceso (acota CPU/red; no es limite global)."""
    import time

    now = time.monotonic()
    if now - _LAST_CALL.get(key, -1e9) < THROTTLE_SECONDS:
        return False
    _LAST_CALL[key] = now
    return True
