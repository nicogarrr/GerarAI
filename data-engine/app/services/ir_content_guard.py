"""Guardas de páginas IR antes de almacenar o pagar extracción."""
from __future__ import annotations

import hashlib
import re
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urlsplit


class _Visible(HTMLParser):
    def __init__(self):
        super().__init__()
        self.skip = 0
        self.parts = []
        self.heading = []
        self.in_heading = False

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript", "template"}:
            self.skip += 1
        if tag in {"title", "h1"}:
            self.in_heading = True

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript", "template"} and self.skip:
            self.skip -= 1
        if tag in {"title", "h1"}:
            self.in_heading = False

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)
            if self.in_heading:
                self.heading.append(data)


def visible_html(text):
    parser = _Visible()
    parser.feed(text)
    return " ".join(parser.parts), " ".join(parser.heading)


def soft_404(url, text, *, html=False):
    path = urlsplit(url or "").path.lower().rstrip("/")
    if re.search(r"/(?:page-not-found|not-found|404)(?:\.html?)?$", path):
        return True
    visible, heading = visible_html(text) if html else (text, text[:500])
    marker = r"\b(?:page (?:not found|does not exist)|404(?: error| not found)|p[aá]gina no encontrada)\b"
    return heading.strip() == "404" or bool(re.search(marker, heading, re.I)) or (
        len(visible.strip()) < 1500 and bool(re.search(marker, visible, re.I))
    )


def normalized_digest(content, *, html=False):
    text = content.decode("utf-8", errors="replace") if isinstance(content, bytes) else content
    if html:
        text, _ = visible_html(text)
    # Solo ruido técnico etiquetado. Nunca quitar fechas/cifras del negocio.
    text = re.sub(r"\b(?:nonce|csrf(?:_token)?|request[_ -]?id|session[_ -]?id)\s*[:=]\s*[\w+/=.-]+", "", text, flags=re.I)
    text = re.sub(r"\b(?:generated at|last (?:page )?rendered|server time)\s*[:=]?\s*\d{4}-\d\d-\d\d[T ][\d:.+-]+Z?", "", text, flags=re.I)
    return hashlib.sha256(" ".join(unescape(text).split()).encode()).hexdigest()
