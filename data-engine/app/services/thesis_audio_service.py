"""Audio de la tesis: texto plano del memo -> sidecar TTS local (Piper, EUR 0).

El sidecar (`cavaai-tts`) sintetiza una tesis a la vez y cachea el mp3 por
clave. La clave lleva ticker, version y un hash del texto: si el memo cambia, el
audio se regenera. Aqui solo se prepara el texto y se habla con el sidecar; no
hay LLM ni proveedores de pago.
"""
from __future__ import annotations

import hashlib
import os
import re

import httpx

TTS_URL = os.environ.get("TTS_URL", "http://cavaai-tts:8080").rstrip("/")
_TIMEOUT = httpx.Timeout(10.0, connect=3.0)
MAX_CHARS = 60000

_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_FENCE = re.compile(r"```.*?```", re.S)


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
    return ("\n".join([head, *lines]))[:MAX_CHARS]


def audio_key(ticker: str, version: int, speech_text: str) -> str:
    digest = hashlib.sha256(speech_text.encode("utf-8")).hexdigest()[:10]
    safe = re.sub(r"[^A-Za-z0-9]", "", ticker.upper())[:20] or "X"
    return f"{safe}-v{int(version)}-{digest}"


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
