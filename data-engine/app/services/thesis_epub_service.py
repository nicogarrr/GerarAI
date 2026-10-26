"""Conversión de tesis de inversión a EPUB con EbookLib.

EbookLib (AGPL-3.0, literalmente la licencia de GerarAI) construye el EPUB
100 % en Python: sin pandoc, sin binario externo y sin `subprocess`. Este
módulo solo usa la API pública de EbookLib (`EpubBook`, `EpubHtml`,
`EpubItem`, `EpubNcx`, `EpubNav`, `Link`, `write_epub`); `lxml`/`six` ya
estaban en el venv como dependencias transitivas.

Contrato público (lo usa `GET /api/thesis/{ticker}/epub`):
    data = ThesisEpubData(ticker="SAN", ...)
    payload: bytes = build_thesis_epub(data)

Decisiones documentadas:
- Sin imágenes embebidas: el pipeline actual no las produce
  (`ThesisEpubData` no tiene campos de imagen, la ruta no pasa
  sparklines/charts y `ThesisVersion`/`ThesisSection` no guardan
  binarios). Si el pipeline las añade, el punto de anclaje es
  `epub.EpubImage` junto a cada `EpubHtml`.
- Identificador estable `cavaai-thesis-{TICKER}-v{versión}` para que el
  e-reader no duplique al re-descargar. `dcterms:modified` lo escribe
  EbookLib con la hora actual (estándar EPUB); la estabilidad
  garantizada es la del identificador, no byte a byte.
- Todo el texto de usuario se escapa y solo se generan etiquetas propias,
  así que el XHTML que recibe EbookLib/lxml siempre es válido (el Kindle
  rechaza en silencio los EPUB con HTML roto).
"""

from __future__ import annotations

import html
import re
import unicodedata
from dataclasses import dataclass, field
from io import BytesIO

from ebooklib import epub

from app.services.memo_text_es import RATING_ES, STATUS_ES, date_es, label_es

# Identidad DC estable: NO sigue la marca (rebrand CavaAI -> GerarAI).
# Cambiarla duplicaria las tesis ya descargadas en los lectores epub.
EPUB_UID_TEMPLATE = "cavaai-thesis-{ticker}-v{version}"

EPUB_MIMETYPE = "application/epub+zip"

DISCLAIMER_ES = (
    "Aviso importante: este documento tiene fines exclusivamente informativos y "
    "educativos. No es asesoramiento de inversión, ni una recomendación de compra "
    "o venta de ningún valor. Toda decisión de inversión conlleva riesgo, incluido "
    "el posible pérdida del capital. Verifica siempre la información con fuentes "
    "primarias antes de actuar."
)

KINDLE_HELP_ES = (
    "Enviar a Kindle: descarga el archivo .epub y envíalo como adjunto desde tu "
    "correo verificado a tu dirección @kindle.com (o súbelo en kindle.amazon.com "
    "con «Enviar a Kindle»). También puedes copiarlo por USB a la carpeta "
    "«documents» de tu Kindle."
)


@dataclass
class EpubSection:
    """Una sección de la tesis (título + cuerpo en texto/markdown ligero)."""

    title: str
    body: str = ""


@dataclass
class ThesisEpubData:
    """Datos mínimos necesarios para renderizar el EPUB de una tesis."""

    ticker: str
    company_name: str = ""
    version: int = 1
    rating: str = "watch"
    status: str = "draft"
    generated_on: str = ""
    executive_summary: str = ""
    sections: list[EpubSection] = field(default_factory=list)
    citations: list[str] = field(default_factory=list)


def slugify(value: str, fallback: str = "seccion") -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", normalized.lower()).strip("-")
    return slug[:48] or fallback


_TABLE_SEP_CELL_RE = re.compile(r"^:?-{1,}:?$")


def _split_table_row(line: str) -> list[str]:
    """Divide una fila de tabla pipe en celdas (sin los pipes de borde)."""
    text = line.strip()
    if text.startswith("|"):
        text = text[1:]
    if text.endswith("|"):
        text = text[:-1]
    return [cell.strip() for cell in text.split("|")]


def _is_table_separator(line: str) -> bool:
    """Detecta la fila `|---|---|` (o `---|---`) de una tabla markdown."""
    cells = _split_table_row(line)
    if not cells or any(cell == "" for cell in cells):
        return False
    return all(_TABLE_SEP_CELL_RE.match(cell) for cell in cells)


def _table_html(header: list[str], rows: list[list[str]]) -> str:
    """Renderiza cabecera + filas como `<table>` XHTML válido."""
    head = "".join(f"<th>{_inline(cell)}</th>" for cell in header)
    body = "".join(
        "<tr>" + "".join(f"<td>{_inline(cell)}</td>" for cell in row) + "</tr>" for row in rows
    )
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def markdown_lite_to_html(body: str) -> str:
    """Convierte texto con markdown ligero a HTML escapado y seguro.

    Soporta encabezados (#, ##, ###), listas (-, *, 1.), tablas pipe
    (`| a | b |` + fila `|---|---|`) y párrafos. Todo el texto se escapa;
    solo se generan etiquetas propias, así que EbookLib/lxml siempre
    recibe XHTML válido.
    """
    if body is None:
        body = ""
    if not isinstance(body, str):
        raise TypeError(f"body must be str, got {type(body).__name__}")
    lines = body.replace("\r\n", "\n").split("\n")
    blocks: list[str] = []
    paragraph: list[str] = []
    list_items: list[str] = []
    list_ordered = False

    def flush_paragraph() -> None:
        if paragraph:
            blocks.append(f"<p>{_inline(' '.join(paragraph))}</p>")
            paragraph.clear()

    def flush_list() -> None:
        if list_items:
            tag = "ol" if list_ordered else "ul"
            blocks.append(f"<{tag}>" + "".join(f"<li>{item}</li>" for item in list_items) + f"</{tag}>")
            list_items.clear()

    index = 0
    total = len(lines)
    while index < total:
        raw = lines[index]
        line = raw.strip()
        if not line:
            flush_paragraph()
            flush_list()
            index += 1
            continue
        following = lines[index + 1] if index + 1 < total else ""
        if (
            "|" in line
            and _is_table_separator(following)
            and (line.lstrip().startswith("|") or "|" in following)
        ):
            flush_paragraph()
            flush_list()
            header = _split_table_row(line)
            index += 2
            rows: list[list[str]] = []
            while index < total and lines[index].strip() and "|" in lines[index]:
                rows.append(_split_table_row(lines[index].strip()))
                index += 1
            width = len(header)
            normalized = [row + [""] * (width - len(row)) if len(row) < width else row for row in rows]
            blocks.append(_table_html(header, normalized))
            continue
        heading = re.match(r"^(#{1,3})\s+(.*)$", line)
        ordered = re.match(r"^\d+[.)]\s+(.*)$", line)
        bullet = re.match(r"^[-*]\s+(.*)$", line)
        if heading:
            flush_paragraph()
            flush_list()
            level = len(heading.group(1)) + 1  # # -> h2 dentro del capítulo (h1 es el título)
            blocks.append(f"<h{min(level, 4)}>{_inline(heading.group(2))}</h{min(level, 4)}>")
        elif ordered or bullet:
            flush_paragraph()
            is_ordered = ordered is not None
            if list_items and is_ordered != list_ordered:
                flush_list()
            list_ordered = is_ordered
            list_items.append(_inline((ordered or bullet).group(1)))  # type: ignore[union-attr]
        else:
            flush_list()
            paragraph.append(line)
        index += 1
    flush_paragraph()
    flush_list()
    return "\n".join(blocks) if blocks else "<p></p>"


def _inline(text: str) -> str:
    """Escapa HTML y aplica **negrita** inline."""
    escaped = html.escape(text, quote=True)
    return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)


def _as_text(value: object, *, name: str, default: str | None = None) -> str:
    """Valida un campo de texto del EPUB con error honesto.

    `None` se sustituye por `default` (dato ausente, no dato roto); otro
    tipo no-str es un error de programación y se eleva como `TypeError`
    en vez de corromper el EPUB en silencio.
    """
    if value is None and default is not None:
        return default
    if not isinstance(value, str):
        raise TypeError(f"ThesisEpubData.{name} must be str, got {type(value).__name__}")
    return value


_STYLE_CSS = (
    "body{font-family:Georgia,serif;line-height:1.6;margin:5%;color:#111}"
    "h1{font-size:1.5em;border-bottom:1px solid #999;padding-bottom:.3em}"
    "h2{font-size:1.25em}h3,h4{font-size:1.1em}"
    "table{border-collapse:collapse;width:100%;margin:1em 0}"
    "th,td{border:1px solid #999;padding:.3em .5em;text-align:left;font-size:.9em}"
    "th{background:#f0f0f0}"
    ".meta{color:#555;font-size:.9em}.disclaimer{background:#fff8e1;border:1px solid #e0c36a;padding:1em}"
    "ul,ol{margin-left:1.2em}"
)


def build_thesis_epub(data: ThesisEpubData) -> bytes:
    """Construye un .epub válido con EbookLib a partir de los datos de la tesis.

    Contrato intacto: recibe `ThesisEpubData` y devuelve `bytes` listos para
    servir como `application/epub+zip`. Metadatos: título, autor `GerarAI`,
    idioma `es`, identificador estable `cavaai-thesis-{TICKER}-v{versión}` (historico pre-rebrand, no cambia con la marca) y
    fecha de generación. El TOC se construye desde las secciones reales.
    """
    if not isinstance(data, ThesisEpubData):
        raise TypeError(f"data must be ThesisEpubData, got {type(data).__name__}")
    ticker = (_as_text(data.ticker, name="ticker", default="UNKNOWN") or "UNKNOWN").upper()
    company_name = _as_text(data.company_name, name="company_name", default="")
    if not isinstance(data.version, int):
        raise TypeError(f"ThesisEpubData.version must be int, got {type(data.version).__name__}")
    rating = _as_text(data.rating, name="rating", default="watch") or "watch"
    status = _as_text(data.status, name="status", default="draft") or "draft"
    generated = _as_text(data.generated_on, name="generated_on", default="")
    if not isinstance(data.sections, (list, tuple)):
        raise TypeError(f"ThesisEpubData.sections must be a list, got {type(data.sections).__name__}")
    if data.citations is None:
        citations: list[str] = []
    elif not isinstance(data.citations, (list, tuple)):
        raise TypeError(f"ThesisEpubData.citations must be a list, got {type(data.citations).__name__}")
    else:
        citations = [_as_text(cite, name="citations[]") for cite in data.citations]

    uid = EPUB_UID_TEMPLATE.format(ticker=ticker, version=data.version)
    title = f"Tesis de inversión: {ticker}"
    if company_name:
        title += f" — {company_name}"

    book = epub.EpubBook()
    book.set_identifier(uid)
    book.set_title(title)
    book.set_language("es")
    book.add_author("GerarAI")
    if generated:
        book.add_metadata("DC", "date", generated)

    css = epub.EpubItem(uid="css", file_name="style.css", media_type="text/css", content=_STYLE_CSS)
    chapters: list[epub.EpubHtml] = []
    toc: list[epub.Link] = []

    def _add_chapter(uid_: str, file_name: str, heading: str, inner_html: str) -> None:
        chapter = epub.EpubHtml(uid=uid_, title=heading, file_name=file_name, lang="es")
        chapter.content = f"<h1>{html.escape(heading, quote=True)}</h1>\n{inner_html}"
        chapter.add_item(css)
        book.add_item(chapter)
        chapters.append(chapter)
        toc.append(epub.Link(file_name, heading, uid_))

    # Mismo vocabulario que el memo y la ficha: enums traducidos (nunca el
    # valor crudo en ingles) y fecha en espanol; el metadato DC conserva ISO.
    rating_label = label_es(RATING_ES, rating)
    status_label = label_es(STATUS_ES, status)
    meta_html = (
        f'<p class="meta">Versión {data.version} · rating: {html.escape(rating_label)} · '
        f"estado: {html.escape(status_label)}"
        + (f" · generada el {html.escape(date_es(generated))}" if generated else "")
        + "</p>"
    )
    if status != "published":
        # Paridad con el memo: una versión no publicada declara su estado, no
        # se presenta como veredicto.
        meta_html += (
            '<div class="disclaimer"><p>Estado: versión en estado '
            f"«{html.escape(status_label)}», no publicada ni aprobada. Es una lectura de "
            "seguimiento, no un veredicto ni una recomendación.</p></div>"
        )
    _add_chapter("portada", "portada.xhtml", title, meta_html)

    summary = _as_text(data.executive_summary, name="executive_summary", default="")
    _add_chapter(
        "resumen",
        "resumen.xhtml",
        "Resumen ejecutivo",
        markdown_lite_to_html(summary or "Sin resumen ejecutivo disponible."),
    )

    used_slugs: set[str] = set()
    for position, section in enumerate(data.sections, start=1):
        if not isinstance(section, EpubSection):
            raise TypeError(f"sections[{position}] must be EpubSection, got {type(section).__name__}")
        section_title = _as_text(section.title, name=f"sections[{position}].title", default="")
        section_body = _as_text(section.body, name=f"sections[{position}].body", default="")
        heading = section_title or f"Sección {position}"
        slug = slugify(section_title, fallback=f"seccion-{position}")
        if slug in used_slugs:
            slug = f"{slug}-{position}"
        used_slugs.add(slug)
        _add_chapter(
            f"sec{position}",
            f"seccion-{position:02d}-{slug}.xhtml",
            heading,
            markdown_lite_to_html(section_body),
        )

    if citations:
        cites_html = "<ol>" + "".join(f"<li>{_inline(cite)}</li>" for cite in citations) + "</ol>"
    else:
        cites_html = "<p>Sin citas registradas para esta tesis.</p>"
    _add_chapter("citas", "citas.xhtml", "Citas y evidencia", cites_html)

    _add_chapter(
        "aviso",
        "aviso.xhtml",
        "Aviso legal",
        f'<div class="disclaimer"><p>{html.escape(DISCLAIMER_ES)}</p></div>',
    )

    book.add_item(css)
    book.toc = tuple(toc)
    book.spine = ["nav", *chapters]
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())

    buffer = BytesIO()
    if not epub.write_epub(buffer, book):
        raise RuntimeError(f"no se pudo generar el EPUB de {ticker} v{data.version}")
    return buffer.getvalue()


def _nav_label(filename: str, data: ThesisEpubData, index: int) -> str:
    if filename == "portada.xhtml":
        return "Portada"
    if filename == "resumen.xhtml":
        return "Resumen ejecutivo"
    if filename == "citas.xhtml":
        return "Citas y evidencia"
    if filename == "aviso.xhtml":
        return "Aviso legal"
    section_index = index - 2  # tras portada + resumen
    if 0 <= section_index < len(data.sections):
        return data.sections[section_index].title or f"Sección {section_index + 1}"
    return filename
