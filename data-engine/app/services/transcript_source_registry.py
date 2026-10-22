"""Registro estatico y honesto de fuentes oficiales de transcripciones por ticker.

- Solo describe DONDE mirar y que se comprobo; no descarga ni guarda texto.
- `status` es lo OBSERVADO en `checked_on`; "sin_comprobar" no significa que no exista.
- webcast/presentacion NO es transcripcion. Un tercero (stockanalysis, fool,
  seekingalpha...) nunca cuenta como fuente oficial ni se usa para citas.
- Una URL solo es "oficial" si coincide con host y prefijo de ruta del registro
  para ese ticker (los CDN tipo q4cdn son compartidos entre empresas).
- No sustituye a la cartera real del usuario: no lista que empresas tiene.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

OFFICIAL_TRANSCRIPT_PDF = "transcripcion_oficial_pdf"
WEBCAST_ONLY = "solo_webcast"
PAGE_MENTIONS_TRANSCRIPT = "pagina_ir_menciona_transcripcion"
UNCHECKED = "sin_comprobar"
STATUSES = frozenset({OFFICIAL_TRANSCRIPT_PDF, WEBCAST_ONLY, PAGE_MENTIONS_TRANSCRIPT, UNCHECKED})


@dataclass(frozen=True)
class SourceEntry:
    ticker: str
    status: str
    ir_page: str
    checked_on: str
    # (host, prefijo de ruta) donde se aceptan PDFs oficiales de este ticker
    pdf_prefixes: tuple[tuple[str, str], ...] = ()
    example_pdf: str | None = None
    note: str = ""

    def __post_init__(self) -> None:
        if self.status not in STATUSES:
            raise ValueError(f"estado desconocido: {self.status}")
        if self.status == OFFICIAL_TRANSCRIPT_PDF and not (self.pdf_prefixes and self.example_pdf):
            raise ValueError("transcripcion_oficial_pdf exige prefijo y ejemplo")


_CHECKED = "2026-10-22"

_ENTRIES = (
    SourceEntry(
        "META",
        OFFICIAL_TRANSCRIPT_PDF,
        "https://investor.atmeta.com/investor-events/event-details/2026/Q1-2026-Earnings-Call/default.aspx",
        _CHECKED,
        (("s21.q4cdn.com", "/399680738/"),),
        "https://s21.q4cdn.com/399680738/files/doc_financials/2026/q1/META-Q1-2026-Earnings-Call-Transcript.pdf",
        "PDF leido y extraido en pruebas previas.",
    ),
    SourceEntry(
        "BN",
        OFFICIAL_TRANSCRIPT_PDF,
        "https://bn.brookfield.com/events/bn-q2-2026-conference-call-webcast",
        _CHECKED,
        (("bn.brookfield.com", "/sites/brookfield-bn-v2/files/"),),
        "https://bn.brookfield.com/sites/brookfield-bn-v2/files/Brookfield-BN-IR-V2/2026/Q2/BN%20Q2-2026-transcript.pdf",
        "PDF leido y extraido en pruebas previas.",
    ),
    SourceEntry(
        "UBER",
        OFFICIAL_TRANSCRIPT_PDF,
        "https://investor.uber.com/news-events/events-and-presentations/event-details/2026/Uber-Q2-2026-Earnings-Conference-Call/default.aspx",
        _CHECKED,
        (("s23.q4cdn.com", "/407969754/"),),
        "https://s23.q4cdn.com/407969754/files/doc_events/2026/Aug/05/Uber-Q2-26-Earnings-Call-Transcript.pdf",
        "PDF 200 application/pdf; cabecera 'Corrected Transcript 05-Aug-2026 Uber Q2 2026 Earnings Call'. La pagina IR lista el PDF; URL del PDF hallada por busqueda, no por enlace extraido.",
    ),
    SourceEntry(
        "ASTS",
        WEBCAST_ONLY,
        "https://investors.ast-science.com/eventsPastEvents",
        _CHECKED,
        note="Sin enlaces a transcripcion en la pagina; webcast/presentacion no son transcripcion.",
    ),
    SourceEntry(
        "RKLB",
        WEBCAST_ONLY,
        "https://investors.rocketlabcorp.com/events/event-details/second-quarter-2026-financial-results-update-and-conference-call",
        _CHECKED,
        note="Webcast en la pagina; no vi transcripcion oficial ahi (no se descarta que exista en otra seccion).",
    ),
    SourceEntry(
        "BABA",
        PAGE_MENTIONS_TRANSCRIPT,
        "https://www.alibabagroup.com/ir-financial-reports-quarterly-results",
        _CHECKED,
        note="La pagina muestra etiquetas 'Transcript'; URL del documento sin extraer ni verificar.",
    ),
    SourceEntry(
        "ONDS",
        UNCHECKED,
        "https://ir.ondas.com/ir-calendar/detail/4834/second-quarter-2026-earnings-conference-call",
        _CHECKED,
        note="Sin transcripcion visible en la pagina del evento; solo terceros en busqueda.",
    ),
    SourceEntry(
        "KRKNF",
        UNCHECKED,
        "https://www.krakenrobotics.com/investors/financial-reports/",
        _CHECKED,
        note="Cotiza tambien en TSX como PNG; sin transcripcion vista en la pagina.",
    ),
    SourceEntry(
        "HYMC",
        UNCHECKED,
        "https://hycroftmining.com/investors/financials-and-reports/",
        _CHECKED,
        note="Sin transcripcion vista en la pagina.",
    ),
)

_BY_TICKER = {e.ticker: e for e in _ENTRIES}


def get_entry(ticker: str) -> SourceEntry | None:
    return _BY_TICKER.get(ticker.strip().upper())


def all_entries() -> tuple[SourceEntry, ...]:
    return _ENTRIES


def is_official_transcript_url(ticker: str, url: str) -> bool:
    """True solo si la URL es https y cae en un host+prefijo registrado para el ticker.
    No prueba que el documento sea la transcripcion correcta (eso lo hace check_source)."""
    entry = get_entry(ticker)
    if entry is None or entry.status != OFFICIAL_TRANSCRIPT_PDF:
        return False
    parsed = urlparse(url)
    if parsed.scheme != "https":
        return False
    host = (parsed.hostname or "").lower()
    return any(host == h and parsed.path.startswith(p) for h, p in entry.pdf_prefixes)
