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
    # Procedencia del URL: "href_ir_leido" (enlace leido en la pagina IR) o
    # "url_dominio_oficial_por_busqueda" (hallado por busqueda, NO enlazado en la pagina IR leida;
    # verificado por descarga directa: dominio oficial, emisor, periodo y fecha en el documento).
    origin: str = "href_ir_leido"
    # Formato del documento: "pdf" (por defecto) o "html" (transcripcion publicada como pagina web
    # del propio emisor; se lee con el mismo hijo acotado, sin ejecutar JS).
    format: str = "pdf"
    # Donde se leyo call_date: "documento" (en la propia transcripcion) o el URL del comunicado/pagina
    # oficial que anuncia la llamada. Nunca se afirma "leida en el documento" si no lo es.
    call_date_source: str = "documento"
    # Marcadores EXACTOS (texto literal) que delimitan el cuerpo de la llamada dentro del texto
    # visible de una pagina HTML. Ambos o ninguno. start debe aparecer UNA vez.
    body_start: str | None = None
    body_end: str | None = None
    # Contexto exigido tras body_end (debe aparecer a <=300 caracteres): evita cortar en una
    # aparicion legitima del marcador dentro de la llamada; si no coincide, se abstiene.
    body_end_context: str | None = None
    # Completitud del documento: "no_evaluada" (por defecto), "comentarios_preparados_sin_qa"
    # (el documento NO incluye preguntas y respuestas aunque el emisor lo titule "full transcript").
    completeness: str = "no_evaluada"

    def __post_init__(self) -> None:
        if self.completeness not in ("no_evaluada", "comentarios_preparados_sin_qa", "completa_con_qa"):
            raise ValueError("completitud desconocida")
        if self.body_end_context is not None and self.body_end is None:
            raise ValueError("body_end_context exige body_end")
        if (self.body_start is None) != (self.body_end is None):
            raise ValueError("body_start y body_end van juntos")
        if self.body_start is not None and self.format != "html":
            raise ValueError("marcadores de cuerpo solo para activos html")
        if self.format not in ("pdf", "html"):
            raise ValueError("formato de activo desconocido")
        if self.origin not in ("href_ir_leido", "url_dominio_oficial_por_busqueda"):
            raise ValueError("origen de activo desconocido")
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
        "KKR",
        OFFICIAL_TRANSCRIPT_PDF,
        "https://ir.kkr.com/events-presentations",
        _CHECKED,
        (
            VerifiedAsset(
                "https://ir.kkr.com/media/document/f00cf12c-3dfa-4eda-80fc-c25f5552e5b2/assets/KKR_Q226_Earnings_Transcript.pdf?disposition=inline",
                "KKR Q2'26 Earnings Transcript",
                "Q2 2026",
                "2026-07-30",
                origin="url_dominio_oficial_por_busqueda",
            ),
        ),
        "URL hallada por busqueda en ir.kkr.com; NO la enlazan las paginas IR leidas (inicio y "
        "events-presentations, que solo enlaza el transcript del Investor Day 2024). Descargada: "
        "PDF 21 pags, sha256 ab2dd1a9e43c..., cabecera 'KKR & Co. Inc. Second Quarter 2026 "
        "Earnings Conference Call July 30, 2026' (InComm Conferencing); fecha coincide con la "
        "llamada anunciada en la pagina IR.",
    ),
    SourceEntry(
        "CB",
        OFFICIAL_TRANSCRIPT_PDF,
        "https://investors.chubb.com/News--Events/news-presentations/events/event-details/2026/3Q-2026-Chubb-Earnings-Conference-Call/default.aspx",
        _CHECKED,
        (
            VerifiedAsset(
                "https://s201.q4cdn.com/471466897/files/content_files/Chubb-3Q26-Transcript-October-21-2026.pdf",
                "Transcript (opens in new window)",
                "Q3 2026",
                "2026-10-21",
            ),
        ),
        "Enlace leido en la pagina IR del evento; PDF 17 pags, sha256 3ebdb6b3dda8..., 'Formatted "
        "Report' de FactSet CallStreet alojado en el q4cdn del IR, cabecera 'Chubb Ltd. (CB) Q3 "
        "2026 Earnings Call 21-Oct-2026'.",
    ),
    SourceEntry(
        "RXRX",
        OFFICIAL_TRANSCRIPT_PDF,
        "https://ir.recursion.com/news-events/presentations/",
        _CHECKED,
        (
            VerifiedAsset(
                "https://www.recursion.com/news/full-transcript-of-recursions-second-quarter-2026-earnings-call",
                "Full Transcript of Recursion's Second Quarter 2026 Earnings Call",
                "Q2 2026",
                "2026-08-05",
                origin="url_dominio_oficial_por_busqueda",
                format="html",
                call_date_source="https://ir.recursion.com/news-releases/news-release-details/recursion-reports-second-quarter-financial-results-genentech/",
                body_start="Below, the full transcript from the Earnings Call.",
                body_end="Decoding biology to radically improve lives.\u00ae",
                body_end_context="Get In Touch",
                completeness="comentarios_preparados_sin_qa",
            ),
        ),
        "Pagina HTML del propio emisor (recursion.com/news, publicada 'August 10, 2026'); el texto "
        "dice 'On August 5, 2026, Recursion reported ... In a related Earnings Call ...' (5-ago son los "
        "resultados); la fecha/hora de la llamada (5-ago-2026 8:00 am ET) se leyo en el comunicado oficial "
        "del IR (call_date_source), NO en esta pagina. La pagina IR leida (presentations) NO la enlaza; URL hallada por busqueda. "
        "HTML 63930 bytes, sha256 2415b3a0..., ~5400 palabras. Transcripcion escrita por el emisor: "
        "no se verifica palabra por palabra contra el audio. Lectura manual del auditor: SOLO comentarios "
        "preparados, sin preguntas y respuestas de analistas (termina 'happy to take your questions'), "
        "aunque la pagina se titule 'Full Transcript'.",
    ),
    SourceEntry(
        "CPT",
        WEBCAST_ONLY,
        "https://investors.camdenliving.com/investors/news-events-presentations/events-and-presentations/default.aspx",
        _CHECKED,
        note="Releida 2026-10-22 con navegador publico (events-and-presentations y detalle 2Q26): enlaza webcasts (Chorus Call) y 0 enlaces a transcripcion. No prueba que no exista transcripcion en otra seccion.",
    ),
    SourceEntry(
        "ABCL",
        WEBCAST_ONLY,
        "https://investors.abcellera.com/events/default.aspx",
        _CHECKED,
        note="Releida 2026-10-22 con navegador publico (events): enlaza webcasts (Q4 events, Q2 2026 incluido) y 0 enlaces a transcripcion. No prueba que no exista en otra seccion.",
    ),
    SourceEntry(
        "NAUT",
        WEBCAST_ONLY,
        "https://investors.nautilus.bio/news-events/events",
        _CHECKED,
        note="Releida 2026-10-22 con navegador publico (events y detalle Q2 2026): enlaza webcasts (media-server) y 0 enlaces a transcripcion. No prueba que no exista en otra seccion.",
    ),
    SourceEntry(
        "POOL",
        NOT_LISTED_ON_IR_PAGE,
        "https://ir.poolcorp.com/",
        _CHECKED,
        note="Leida en navegador publico el 2026-10-22 (inicio): 0 enlaces con 'transcript'. No prueba que no exista en otra seccion.",
    ),
    SourceEntry(
        "HIMS",
        WEBCAST_ONLY,
        "https://investors.hims.com/events-and-presentations/default.aspx",
        _CHECKED,
        note="Releida 2026-10-22 con navegador publico (events-and-presentations y detalle Q2 2026): enlaza webcasts (Q4 events) y 0 enlaces a transcripcion. No prueba que no exista en otra seccion.",
    ),
    SourceEntry(
        "UNH",
        OFFICIAL_TRANSCRIPT_PDF,
        "https://www.unitedhealthgroup.com/investors/financial-reports.html",
        _CHECKED,
        (
            VerifiedAsset(
                "https://www.unitedhealthgroup.com/content/dam/UHG/PDF/investors/2026/unh-q3-2026-remarks.pdf",
                "Third Quarter 2026 Results Teleconference Prepared Remarks",
                "Q3 2026",
                "2026-10-13",
                origin="href_ir_leido",
                completeness="comentarios_preparados_sin_qa",
            ),
            VerifiedAsset(
                "https://www.unitedhealthgroup.com/content/dam/UHG/PDF/investors/2026/unh-q2-2026-remarks.pdf",
                "Second Quarter 2026 Results Teleconference Prepared Remarks",
                "Q2 2026",
                "2026-07-16",
                origin="url_dominio_oficial_por_busqueda",
                completeness="comentarios_preparados_sin_qa",
            ),
        ),
        "COMENTARIOS PREPARADOS (no transcripcion con preguntas y respuestas). Q3 (13-oct-2026): href "
        "/content/dam/UHG/PDF/investors/2026/unh-q3-2026-remarks.pdf presente en el HTML de "
        "financial-reports leido por curl el 2026-10-22. Q2 (16-jul-2026): historico, hallado por "
        "busqueda en el dominio del emisor y YA NO enlazado en esa pagina. Ambos documentos anuncian "
        "una sesion de preguntas y respuestas posterior que NO esta incluida (Q3 solo trae el cierre \"Post Q&A\" de la direccion). Extractor (v4): hablantes reconocidos por nombre solo en linea (formato nombre_solo_comentarios_preparados), cargo NO indicado en el documento; candidatos solo propuestos, sin revisar."
    ),
    SourceEntry(
        "AAPL",
        NOT_LISTED_ON_IR_PAGE,
        "https://investor.apple.com/investor-relations/default.aspx",
        _CHECKED,
        note="Leida en navegador publico el 2026-10-22 (inicio): 0 enlaces con 'transcript'. No prueba que no exista en otra seccion.",
    ),
    SourceEntry(
        "IBRX",
        NOT_LISTED_ON_IR_PAGE,
        "https://ir.immunitybio.com/company/events-and-presentations",
        _CHECKED,
        note="Leida en navegador publico el 2026-10-22 (events-and-presentations y comunicado de resultados): 0 enlaces con 'transcript'. No prueba que no exista en otra seccion.",
    ),
    SourceEntry(
        "CGEO.L",
        NOT_LISTED_ON_IR_PAGE,
        "https://georgiacapital.ge/investor-relations/financial-results",
        _CHECKED,
        note="Leida en navegador publico el 2026-10-22 (financial-results y noticia 2Q26/1H26): 0 enlaces con 'transcript'. No prueba que no exista en otra seccion.",
    ),
    SourceEntry(
        "ASTS",
        WEBCAST_ONLY,
        "https://investors.ast-science.com/events",
        _CHECKED,
        note="Releida 2026-10-22 22:04 en navegador publico: /events enlaza webcasts (Chorus Call, YouTube) y 0 menciones de 'transcript'; la URL anterior /eventsPastEvents devuelve 404. No prueba que no exista una transcripcion en otra seccion.",
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
        note="Releida 2026-10-22 22:02 en navegador publico: las dos etiquetas 'Transcript' (June Quarter 2026 y March Quarter 2026) son <a> SIN atributo href en el DOM (Press Releases si lo tiene); no hay URL resoluble, no se promueve a fuente.",
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
