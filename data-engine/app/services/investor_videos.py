"""Videos publicos de un canal identificado, nunca cartera ni canal personal inferido."""
from __future__ import annotations

import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from threading import Lock

# Atom externo (YouTube): defusedxml solo para PARSEAR.
import defusedxml.ElementTree as DefusedET
import httpx

_CHANNEL = re.compile(r"UC[A-Za-z0-9_-]{22}\Z")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)\Z")
_VIDEO = re.compile(r"[A-Za-z0-9_-]{11}\Z")
_LETTER = re.compile(r"[\w\u00c0-\u024f]")
_ATOM = "{http://www.w3.org/2005/Atom}"
_YT = "{http://www.youtube.com/xml/schemas/2015}"
# Canales confirmados en el directorio verificado de channels.ts
# (VERIFIED_PICK 2026-10-11) o canal de archivo de referencia, nunca canal
# personal inferido. El nombre sale del RSS; no se atribuye su propiedad sin prueba.
CHANNELS: dict[str, tuple[str, str]] = {
    "buffett": ("UCyMGOTSE13Uf9Big_Ppj8Wg", "archive"),
    "pabrai": ("UCw-OcYmKtk7ut-Ay7hIBaWg", "personal_confirmed"),
    "terry-smith": ("UCEW0yRVs0CbqT9CrP8i3mSQ", "firm_confirmed"),
}
_KINDS = ("personal_confirmed", "firm_confirmed", "archive")
_CACHE: dict[str, tuple[float, list[dict[str, str]]]] = {}
_LOCK = Lock()
TTL_SECONDS = 3600
MAX_BYTES = 256_000


def parse_feed(content: bytes, channel_id: str, channel_kind: str) -> list[dict[str, str]]:
    if not _CHANNEL.fullmatch(channel_id) or channel_kind not in _KINDS:
        return []
    if len(content) > MAX_BYTES:
        return []
    # Solo UTF-8: ET no recibe bytes que puedan reinterpretarse como UTF-16.
    # Rechaza NUL y una declaracion de encoding distinta, no repara el XML.
    try:
        text = content.decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError:
        return []
    encoding = re.search(r"<\?xml\s[^?]*encoding\s*=\s*['\"]([^'\"]+)['\"]", text, re.IGNORECASE)
    if "\x00" in text or (encoding and encoding.group(1).lower() not in ("utf-8", "utf8")):
        return []
    if "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
        return []
    try:
        root = DefusedET.fromstring(text)
    except ET.ParseError:
        return []
    if root.tag != _ATOM + "feed":
        return []
    # YouTube sirve el channelId del feed a veces sin el prefijo "UC"
    # (p. ej. "yMGOTSE..." para "UCyMGOTSE..."); las entradas siempre lo llevan
    # y se verifican de forma exacta una a una mas abajo.
    feed_channel = root.findtext(_YT + "channelId") or ""
    if feed_channel != channel_id and channel_id != "UC" + feed_channel:
        return []
    name = (root.findtext(_ATOM + "title") or "").strip()
    if not name:
        return []
    result = []
    seen = set()
    for entry in root.findall(_ATOM + "entry"):
        vid = entry.findtext(_YT + "videoId") or ""
        title = (entry.findtext(_ATOM + "title") or "").strip()
        published = entry.findtext(_ATOM + "published") or ""
        # Titulos sin ninguna letra ni cifra (p. ej. shorts titulados solo con
        # un emoji) no dicen nada al lector: se descartan, no se maquillan.
        if not _VIDEO.fullmatch(vid) or not title or not _LETTER.search(title) or vid in seen or not _DATE.fullmatch(published):
            continue
        if entry.findtext(_YT + "channelId") != channel_id:
            continue
        try:
            at = datetime.fromisoformat(published.replace("Z", "+00:00"))
        except ValueError:
            continue
        if at.tzinfo is None:
            continue
        seen.add(vid)
        result.append({
            "video_id": vid,
            "title": title[:500],
            "published_at": at.isoformat(),
            "channel_name": name[:200],
            "channel_url": f"https://www.youtube.com/channel/{channel_id}",
            "channel_kind": channel_kind,
        })
    return sorted(result, key=lambda row: datetime.fromisoformat(row["published_at"]), reverse=True)[:6]


def investor_videos(slug: str) -> list[dict[str, str]]:
    channel = CHANNELS.get(slug)
    if channel is None:
        return []
    channel_id, kind = channel
    if not _CHANNEL.fullmatch(channel_id):
        return []
    with _LOCK:
        cached = _CACHE.get(slug)
        if cached is not None and time.monotonic() < cached[0]:
            return [dict(row) for row in cached[1]]
        videos: list[dict[str, str]] = []
        try:
            # Destino fijo validado; sin redirects, cookies, auth ni API key.
            with (
                httpx.Client(timeout=5.0, follow_redirects=False) as client,
                client.stream("GET", "https://www.youtube.com/feeds/videos.xml", params={"channel_id": channel_id}) as response,
            ):
                response.raise_for_status()
                content = bytearray()
                for chunk in response.iter_bytes():
                    content.extend(chunk)
                    if len(content) > MAX_BYTES:
                        break
                videos = parse_feed(bytes(content), channel_id, kind)
        except httpx.HTTPError:
            pass
        _CACHE[slug] = (time.monotonic() + TTL_SECONDS, videos)
        return [dict(row) for row in videos]
