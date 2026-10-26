"""Audio de la tesis: texto plano del memo -> sidecar TTS local (Piper, EUR 0).

El sidecar (`cavaai-tts`) sintetiza una tesis a la vez y cachea el mp3 por
clave. La clave lleva ticker, version, estado y el dia del ultimo dato: si cambian
los datos (otro dia) el audio se regenera; ademas el sidecar caduca el mp3 a las 24 h. Aqui solo se prepara el texto y se habla con el sidecar; no
hay LLM ni proveedores de pago.
"""
from __future__ import annotations

import os
import re

import httpx

TTS_URL = os.environ.get("TTS_URL", "http://cavaai-tts:8080").rstrip("/")
_TIMEOUT = httpx.Timeout(10.0, connect=3.0)
MAX_CHARS = 60000

_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_FENCE = re.compile(r"```.*?```", re.S)

# Aviso legal hablado: el memo lo cierra siempre y el audio no puede perderlo
# por el corte de MAX_CHARS.
_DISCLAIMER_SPOKEN = (
    "Documento informativo de investigación. "
    "No es asesoramiento financiero ni recomendación de compra o venta."
)


def memo_to_speech_text(markdown: str, *, ticker: str, version: int) -> str:
    """Markdown del memo -> parrafos hablables (sin sintaxis ni tablas)."""
    text = _FENCE.sub(" ", markdown or "")
    lines: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or set(line) <= set("-|: "):
            continue
        if line.startswith("|"):
            continue
        line = _LINK.sub(r"\1", line)
        line = re.sub(r"^[#>\-*+\s]+", "", line)
        line = re.sub(r"[*_`]+", "", line).strip()
        if len(line) >= 2:
            lines.append(line)
    head = f"Tesis de {ticker.upper()}, versión {version}."
    text = "\n".join([head, *lines])
    if len(text) <= MAX_CHARS:
        return text
    # Corte en borde de palabra (no a media palabra) y el aviso legal siempre
    # al final: un audio truncado sin él leería la tesis sin la advertencia.
    cut = text[: MAX_CHARS - len(_DISCLAIMER_SPOKEN) - 1]
    last_space = cut.rfind(" ")
    if last_space > 0:
        cut = cut[:last_space]
    cut = cut.rstrip()
    if "Documento informativo de investigación" in cut:
        return cut
    return f"{cut} {_DISCLAIMER_SPOKEN}"


_FORMAT = "f3"  # subir al cambiar memo_to_speech_text para invalidar la cache


def audio_key(
    ticker: str,
    version: int,
    speech_text: str = "",
    *,
    draft: bool = False,
    data_day: str = "nd",
) -> str:
    """Clave estable: ticker + version + estado + dia del ultimo dato + formato.

    No depende del texto (el memo lleva datos vivos y su hash cambiaba entre
    llamadas). ``data_day`` (YYYYMMDD) cambia solo cuando llegan datos de otro
    dia, asi que el audio no queda con cifras viejas indefinidamente.
    """
    safe = re.sub(r"[^A-Za-z0-9]", "", ticker.upper())[:20] or "X"
    day = re.sub(r"[^0-9a-z]", "", str(data_day).lower())[:8] or "nd"
    return f"{safe}-v{int(version)}-{'d' if draft else 'p'}-{day}-{_FORMAT}"


def data_day(latest_data_at) -> str:
    return latest_data_at.strftime("%Y%m%d") if latest_data_at is not None else "nd"


def status_info(key: str) -> dict:
    """{state, generated_at?}: generated_at (ISO UTC) cuando el mp3 esta listo."""
    try:
        resp = httpx.get(f"{TTS_URL}/status/{key}", timeout=_TIMEOUT)
        resp.raise_for_status()
        body = resp.json()
    except (httpx.HTTPError, ValueError):
        return {"state": "unavailable"}
    state = str(body.get("state") or "missing")
    info = {"state": "error" if state.startswith("error") else state}
    if body.get("generated_at"):
        info["generated_at"] = str(body["generated_at"])
    return info


def status(key: str) -> str:
    """ready | pending | missing | unavailable | error"""
    try:
        resp = httpx.get(f"{TTS_URL}/status/{key}", timeout=_TIMEOUT)
        resp.raise_for_status()
        state = str(resp.json().get("state") or "missing")
    except (httpx.HTTPError, ValueError):
        return "unavailable"
    return "error" if state.startswith("error") else state


def start(key: str, speech_text: str) -> str:
    """Encola la sintesis (idempotente). Devuelve el estado resultante."""
    try:
        resp = httpx.post(f"{TTS_URL}/tts/{key}", json={"text": speech_text}, timeout=_TIMEOUT)
        resp.raise_for_status()
        return str(resp.json().get("state") or "pending")
    except (httpx.HTTPError, ValueError):
        return "unavailable"


def fetch_mp3(key: str) -> bytes | None:
    try:
        resp = httpx.get(f"{TTS_URL}/audio/{key}", timeout=httpx.Timeout(60.0, connect=3.0))
        if resp.status_code != 200:
            return None
        return resp.content
    except httpx.HTTPError:
        return None
