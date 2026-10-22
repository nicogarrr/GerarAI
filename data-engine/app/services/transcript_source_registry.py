"""Registro estatico y honesto de fuentes oficiales de transcripciones por ticker.

- Solo describe DONDE mirar y que se comprobo; no descarga ni guarda texto.
- `status` es lo OBSERVADO en `checked_on` (lectura del piloto, no auditor independiente);
  una ausencia no prueba que el documento no exista.
- webcast/presentacion NO es transcripcion. Un tercero (stockanalysis, fool,
  seekingalpha...) nunca cuenta como fuente oficial ni se usa para citas.
- Una URL solo es "oficial" si es EXACTAMENTE un activo registrado (URL completa, tipo
  transcripcion, etiqueta, periodo) leido como enlace en la pagina IR. Host o prefijo no
  bastan: los CDN (q4cdn) alojan tambien presentaciones y notas de prensa.
- No sustituye a la cartera real del usuario: no lista que empresas tiene.
- Aun no esta conectado a transcript_source_service (DEFAULT_HOSTS sin ampliar): antes
  de usarlo para descargar hay que integrar el fetch con URL estricta y limite SSRF.
"""

from __future__ import annotations

from dataclasses import dataclass

OFFICIAL_TRANSCRIPT_PDF = "transcripcion_oficial_pdf"
WEBCAST_ONLY = "solo_webcast"
PAGE_MENTIONS_TRANSCRIPT = "pagina_ir_menciona_transcripcion"
NOT_LISTED_ON_IR_PAGE = "no_listada_en_pagina_ir"
UNCHECKED = "sin_comprobar"
STATUSES = frozenset(
    {OFFICIAL_TRANSCRIPT_PDF, WEBCAST_ONLY, PAGE_MENTIONS_TRANSCRIPT, NOT_LISTED_ON_IR_PAGE, UNCHECKED}
)


@dataclass(frozen=True)
class VerifiedAsset:
    """Enlace leido (href) en la pagina IR, con la etiqueta que mostraba."""

    url: str
    label: str  # texto del enlace en la pagina IR
    period: str  # p.ej. 'Q2 2026'
    call_date: str | None = None  # AAAA-MM-DD solo si se leyo en el documento
    kind: str = "transcript"

    def __post_init__(self) -> None:
        if self.kind != "transcript":
            raise ValueError("solo se registran activos de tipo transcript")
        if not self.url.startswith("https://"):
            raise ValueError("el activo debe ser https")


@dataclass(frozen=True)
class SourceEntry:
    ticker: str
    status: str
    ir_page: str
    checked_on: str
    assets: tuple[VerifiedAsset, ...] = ()
    note: str = ""

    def __post_init__(self) -> None:
        if self.status not in STATUSES:
            raise ValueError(f"estado desconocido: {self.status}")
        if self.status == OFFICIAL_TRANSCRIPT_PDF and not self.assets:
            raise ValueError("transcripcion_oficial_pdf exige al menos un activo verificado")
        if self.status != OFFICIAL_TRANSCRIPT_PDF and self.assets:
            raise ValueError("solo transcripcion_oficial_pdf puede llevar activos")


_CHECKED = "2026-10-22"

_ENTRIES = (
    SourceEntry(
        "META",
        OFFICIAL_TRANSCRIPT_PDF,
        "https://investor.atmeta.com/investor-events/event-details/2026/Q1-2026-Earnings-Call/default.aspx",
        _CHECKED,
        (
            VerifiedAsset(
                "https://s21.q4cdn.com/399680738/files/doc_financials/2026/q1/META-Q1-2026-Earnings-Call-Transcript.pdf",
                "Earnings Call Transcript (pdf)",
                "Q1 2026",
            ),
            VerifiedAsset(
                "https://s21.q4cdn.com/399680738/files/doc_financials/2026/q1/META-Q1-2026-Follow-Up-Call-Transcript.pdf",
                "Follow Up Call Transcript (pdf)",
                "Q1 2026",
            ),
        ),
        "Enlaces leidos en la pagina IR; el primero se extrajo en pruebas previas.",
    ),
    SourceEntry(
        "BN",
        OFFICIAL_TRANSCRIPT_PDF,
        "https://bn.brookfield.com/events/bn-q2-2026-conference-call-webcast",
        _CHECKED,
        (
            VerifiedAsset(
                "https://bn.brookfield.com/sites/brookfield-bn-v2/files/Brookfield-BN-IR-V2/2026/Q2/BN%20Q2-2026-transcript.pdf",
                "Transcript",
                "Q2 2026",
                "2026-08-13",
            ),
        ),
        "Enlace leido en la pagina IR; PDF 20 pags, cabecera 'AUGUST 13, 2026, at 10:00 a.m. (ET)' leida en el documento.",
    ),
    SourceEntry(
        "UBER",
        OFFICIAL_TRANSCRIPT_PDF,
        "https://investor.uber.com/news-events/events-and-presentations/event-details/2026/Uber-Q2-2026-Earnings-Conference-Call/default.aspx",
        _CHECKED,
        (
            VerifiedAsset(
                "https://s23.q4cdn.com/407969754/files/doc_events/2026/Aug/05/Uber-Q2-26-Earnings-Call-Transcript.pdf",
                "Transcript (opens in new window)",
                "Q2 2026",
                "2026-08-05",
            ),
        ),
        "PDF 200 application/pdf; cabecera 'Corrected Transcript 05-Aug-2026'. La misma pagina enlaza 'Prepared Remarks' (otro PDF, NO es la transcripcion).",
    ),
    SourceEntry(
        "ASTS",
        NOT_LISTED_ON_IR_PAGE,
        "https://investors.ast-science.com/eventsPastEvents",
        _CHECKED,
        note="La pagina de eventos pasados no menciona transcripcion (0 apariciones); hay webcast/presentacion, que no son transcripcion. No prueba que no exista.",
    ),
    SourceEntry(
        "RKLB",
        WEBCAST_ONLY,
        "https://investors.rocketlabcorp.com/events/event-details/second-quarter-2026-financial-results-update-and-conference-call",
        _CHECKED,
        note="Webcast en la pagina; sin transcripcion oficial ahi (no se descarta que exista en otra seccion).",
    ),
    SourceEntry(
        "BABA",
        PAGE_MENTIONS_TRANSCRIPT,
        "https://www.alibabagroup.com/ir-financial-reports-quarterly-results",
        _CHECKED,
        note="La pagina muestra dos etiquetas 'Transcript' sin href legible; URL del documento sin verificar.",
    ),
    SourceEntry(
        "ONDS",
        WEBCAST_ONLY,
        "https://ir.ondas.com/ir-calendar/detail/4834/second-quarter-2026-earnings-conference-call",
        _CHECKED,
        note="La pagina del evento enlaza webcast/audio y presentacion PDF, sin transcripcion. No prueba que no exista.",
    ),
    SourceEntry(
        "KRKNF",
        NOT_LISTED_ON_IR_PAGE,
        "https://www.krakenrobotics.com/investors/financial-reports/",
        _CHECKED,
        note="Cotiza tambien en TSX como PNG. La pagina lista estados, MD&A y presentacion; 0 menciones de transcripcion.",
    ),
    SourceEntry(
        "HYMC",
        NOT_LISTED_ON_IR_PAGE,
        "https://hycroftmining.com/investors/financials-and-reports/",
        _CHECKED,
        note="La pagina de informes lista 10-K/10-Q; 0 menciones de transcripcion. No prueba que no exista.",
    ),
)

_BY_TICKER = {e.ticker: e for e in _ENTRIES}


def get_entry(ticker: str) -> SourceEntry | None:
    return _BY_TICKER.get(ticker.strip().upper())


def all_entries() -> tuple[SourceEntry, ...]:
    return _ENTRIES


def is_official_transcript_url(ticker: str, url: str) -> bool:
    """True solo si `url` es EXACTAMENTE un activo transcript registrado para el ticker.
    Sin normalizar ni comparar por prefijo, host o dominio. No prueba que el documento
    sea la transcripcion correcta (eso lo hace check_source, un gate tecnico, no verificacion)."""
    entry = get_entry(ticker)
    if entry is None:
        return False
    return any(a.url == url for a in entry.assets)
