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
        text = "\n".join((page.extract_text() or "") for page in reader.pages)
    except TranscriptSourceError:
        raise
    except Exception as exc:
        raise TranscriptSourceError("No se pudo extraer texto del PDF") from exc
    if len(text.split()) < 200:
        raise TranscriptSourceError("Texto extraido insuficiente (PDF escaneado o vacio)")
    return text
