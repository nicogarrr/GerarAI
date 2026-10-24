"""Two-lane document parsing: MarkItDown fast lane, Docling structure lane, pypdf fallback.

Carriles (solo ficheros PDF; el resto de extensiones usa el parser nativo):

1. **markitdown** (rapido, sync-safe): Markdown en <1 s via ``markitdown``.
   Sin modelos ML, sin E/S de red. Apto para la ruta sincrona de FastAPI.
2. **docling** (estructura, SOLO worker): layout ML + tablas + provenance por
   pagina (0.3-3 s/pagina en CPU, mas descarga de modelos la primera vez).
3. **pypdf** (fallback clasico): el carril historico, nunca se rompe.

REGLA DE EJECUCION (obligatoria): Docling NUNCA corre en la ruta sincrona de
FastAPI. El conversor pesado solo se construye cuando el worker lo habilita
expresamente con :func:`docling_heavy_context` (el actor Dramatiq
``process_document_structured`` lo activa; ver ``app/workers/dramatiq_app.py``).
En request, un PDF con estructura detectada (tablas/XBRL/escaneado) se sirve
con el carril rapido y queda marcado con un warning "Docling diferido al
worker" (persistido en ``document.metadata_["warnings"]``) para su reproceso
en worker. La propagacion usa un :class:`contextvars.ContextVar` (thread-local
por diseno): el actor Dramatiq corre sync en su propio hilo y ``_run`` ejecuta
``asyncio.run`` en ese mismo hilo, asi que el flag llega intacto; nunca se usa
una variable de entorno para esto porque los workers procesan mensajes en
hilos concurrentes del mismo proceso.

Decision de carril (:func:`decide_lane`, umbrales via ``CAVAAI_DOCLING_*``):

* MarkItDown primero, siempre.
* Si el Markdown rapido trae >= ``CAVAAI_DOCLING_TABLE_MIN_PIPE_LINES`` (def.
  3) lineas con ``|`` (tablas GFM) -> Docling (worker) / diferido (sync).
* Si el documento huele a XBRL (filing iXBRL/XML: :func:`detect_xbrl`) ->
  Docling (worker) / diferido (sync). Los facts estructurados se extraen ADEMAS
  con el parser propio de la casa (stdlib, sync-safe) via
  :func:`extract_xbrl_facts`, que reutiliza el contrato de entrada de
  ``app.services.connectors.sec_xbrl_instance.parse_instance_dimensioned_facts``
  (stream binario -> ``DimensionedFact``) sin modificarlo.
* Si el Markdown rapido trae < ``CAVAAI_DOCLING_SCANNED_MIN_CHARS`` (def. 120)
  caracteres en un PDF -> probable escaneado (necesita OCR) -> Docling.
* Si Docling falla o no esta instalado -> carril rapido si existe, pypdf
  clasico en ultima instancia, con warning trazable ("docling no instalado" /
  "Docling fallo: ..."). Idem MarkItDown ("markitdown no instalado"). Nunca un
  500 opaco ni un ImportError en arranque:
  TODOS los imports de docling/markitdown son perezosos (dentro de las
  funciones) y la ausencia degrada con warnings, no con excepciones.

Provenance por chunk (entregable principal): cada bloque lleva metadata aditiva
``extraction_lane`` (markitdown|docling|pypdf), ``page`` (int | None) y
``table_id`` (solo bloques de tabla Docling, ``#/tables/<n>``). El carril
rapido pagina cuando el backend pdfminer deja separadores ``\x0c`` (caso
comun en PDFs de prosa); sin ellos, page=None honesto. :meth:`DocumentIngestionService._chunk_blocks` ya propaga
``block_metadata`` a cada chunk sin cambios, y ``knowledge_library_service``
ya deriva ``page_number`` de ahi: el shape de chunks NO cambia, solo se anaden
claves.
"""

from __future__ import annotations

import contextvars
import os
import re
import threading
import warnings
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from io import BytesIO
from typing import Any

from app.services.document_ingestion_service import ParsedBlock, ParsedDocument

LANE_MARKITDOWN = "markitdown"
LANE_DOCLING = "docling"
LANE_PYPDF = "pypdf"

# El carril pypdf historico se sigue llamando "pypdf" en parser/block metadata.
_LEGACY_DOCLING_OPT_IN_ENV = "CAVAAI_USE_DOCLING"

_TABLE_PIPE_LINE_RE = re.compile(r"\|")
_TABLE_SEPARATOR_RE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$")

_XBRL_MARKERS = (
    b"<xbrl",
    b"xbrli:",
    b"<ix:",
    b"xmlns:ix",
    b"xbrl.org/",
)
_XBRL_SNIFF_BYTES = 8192


class _LaneUnavailable(Exception):
    """La dependencia opcional del carril no esta instalada."""


class _LaneFailed(Exception):
    """El conversor del carril lanzo (contenido roto, timeout, etc.)."""


def _env_int(name: str, default: int) -> int:
    try:
        return max(0, int(os.getenv(name, str(default))))
    except ValueError:
        return default


def table_min_pipe_lines() -> int:
    """Umbral de escalado a Docling: lineas con '|' en el Markdown rapido."""
    return _env_int("CAVAAI_DOCLING_TABLE_MIN_PIPE_LINES", 3)


def scanned_min_chars() -> int:
    """Bajo este total de caracteres el PDF se considera escaneado (necesita OCR)."""
    return _env_int("CAVAAI_DOCLING_SCANNED_MIN_CHARS", 120)


def xbrl_max_facts() -> int:
    """Tope de facts XBRL serializados en metadata de bloque (cota de tamano)."""
    return _env_int("CAVAAI_XBRL_MAX_FACTS", 200)


def lane_flags() -> dict[str, bool]:
    """Flags efectivos del pipeline (Settings + opt-in legacy).

    Por defecto todo activo si la dependencia esta instalada; la ausencia de la
    dependencia degrada con warnings, nunca rompe. ``CAVAAI_USE_DOCLING=1``
    (legacy) fuerza preferencia por el carril pesado cuando haya estructura.
    """
    from app.core.config import get_settings

    settings = get_settings()
    return {
        "markitdown_enabled": bool(settings.markitdown_enabled),
        "docling_lane_enabled": bool(settings.docling_lane_enabled),
        "docling_async_only": bool(settings.docling_async_only),
        "docling_opt_in": os.getenv(_LEGACY_DOCLING_OPT_IN_ENV) == "1",
    }


_ALLOW_HEAVY: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "cavaai_docling_heavy", default=False
)


def heavy_lane_allowed() -> bool:
    """True solo dentro de :func:`docling_heavy_context` (worker Dramatiq)."""
    return bool(_ALLOW_HEAVY.get())


def docling_max_image_pixels() -> int:
    """Tope de pixeles por imagen decodificada por Pillow en el carril docling.

    Un A4 escaneado a 600 dpi son ~35 M px: el default de 50 M los admite. Pillow
    solo avisa entre 1x y 2x del tope y falla por encima; aqui ambos casos
    fallan (ver :func:`_bounded_image_pixels`). Es contencion de bombas de
    descompresion, NO un parche de los fallos de memoria de Pillow.
    """
    return _env_int("CAVAAI_DOCLING_MAX_IMAGE_PIXELS", 50_000_000)


_PIL_LOCK = threading.Lock()
_PIL_DEPTH = 0
_PIL_SAVED: tuple[Any, Any] | None = None  # (MAX_IMAGE_PIXELS previo, filtro de avisos previo)


@contextmanager
def _bounded_image_pixels() -> Iterator[None]:
    """Acota Pillow mientras haya algun contexto pesado activo en el proceso.

    ``Image.MAX_IMAGE_PIXELS`` y los filtros de ``warnings`` son estado GLOBAL del
    proceso, y el worker corre varios hilos. Por eso es un contador con lock: el
    primero que entra guarda el valor previo y el ultimo que sale lo restaura (un
    save/restore por hilo dejaria el tope puesto para siempre con solapes). Limite
    conocido: mientras dure un contexto pesado, otros hilos del mismo proceso que
    usen Pillow tambien ven el tope.

    Sin Pillow importable no hace nada. Una imagen sobre el tope levanta
    ``DecompressionBombError``/``Warning`` -> el carril lanza ``_LaneFailed`` y el
    orquestador sirve el carril rapido (pypdf en ultima instancia).
    """
    global _PIL_DEPTH, _PIL_SAVED
    try:
        from PIL import Image as _PilImage
    except Exception:  # noqa: BLE001 - Pillow ausente: sin acotar
        yield
        return
    with _PIL_LOCK:
        if _PIL_DEPTH == 0:
            _PIL_SAVED = (_PilImage.MAX_IMAGE_PIXELS, list(warnings.filters))
            _PilImage.MAX_IMAGE_PIXELS = docling_max_image_pixels()
            warnings.filterwarnings("error", category=_PilImage.DecompressionBombWarning)
        _PIL_DEPTH += 1
    try:
        yield
    finally:
        with _PIL_LOCK:
            _PIL_DEPTH -= 1
            if _PIL_DEPTH == 0 and _PIL_SAVED is not None:
                _PilImage.MAX_IMAGE_PIXELS = _PIL_SAVED[0]
                warnings.filters[:] = _PIL_SAVED[1]  # pyright: ignore[reportIndexIssue]
                _PIL_SAVED = None


@contextmanager
def docling_heavy_context() -> Iterator[None]:
    """Habilita el conversor Docling en este hilo/contexto (solo worker).

    Scoped y sin fugas entre mensajes: al salir se restaura el valor previo.
    """
    token = _ALLOW_HEAVY.set(True)
    with _bounded_image_pixels():
        try:
            yield
        finally:
            _ALLOW_HEAVY.reset(token)


def resolve_allow_heavy(explicit: bool | None = None) -> bool:
    """Resuelve si el carril pesado puede correr en este contexto.

    ``explicit`` (tests/llamadas directas) manda; si es None, el contexto del
    worker habilita, salvo que ``docling_async_only`` este desactivado (escape
    hatch para scripts locales puntuales; jamas en serving de produccion).
    """
    if explicit is not None:
        return explicit
    if heavy_lane_allowed():
        return True
    from app.core.config import get_settings

    return not bool(get_settings().docling_async_only)


@dataclass
class LaneDecision:
    lane: str
    reason: str
    table_pipe_lines: int = 0
    xbrl_detected: bool = False
    scanned: bool = False


def count_table_pipe_lines(markdown: str) -> int:
    """Lineas con '|' que parecen tabla (cabecera/separador/filas)."""
    lines = markdown.splitlines()
    pipe_lines = sum(1 for line in lines if _TABLE_PIPE_LINE_RE.search(line))
    if pipe_lines < 3:
        return 0
    if not any(_TABLE_SEPARATOR_RE.match(line) for line in lines):
        # Sin fila separadora GFM puede ser texto con pipes sueltos; se exige
        # ademas densidad minima para no escalar por falsos positivos.
        if pipe_lines < table_min_pipe_lines() * 2:
            return 0
    return pipe_lines


def decide_lane(
    fast_markdown: str | None,
    *,
    xbrl_detected: bool = False,
) -> LaneDecision:
    """Carril pesado o rapido a partir del Markdown del pre-filtro.

    ``fast_markdown=None`` = el pre-filtro no produjo nada (dependencia ausente
    o vacio): no hay senal de estructura, pypdf clasico.
    """
    if xbrl_detected:
        return LaneDecision(
            lane=LANE_DOCLING,
            reason="xbrl-detected: filing con XBRL, extraccion estructurada",
            xbrl_detected=True,
        )
    if not (fast_markdown or "").strip():
        return LaneDecision(lane=LANE_PYPDF, reason="fast-empty: sin pre-filtro, pypdf clasico")
    pipe_lines = count_table_pipe_lines(fast_markdown or "")
    if pipe_lines >= table_min_pipe_lines():
        return LaneDecision(
            lane=LANE_DOCLING,
            reason=f"tables-detected: {pipe_lines} lineas con '|' >= umbral",
            table_pipe_lines=pipe_lines,
        )
    if len((fast_markdown or "").strip()) < scanned_min_chars():
        return LaneDecision(
            lane=LANE_DOCLING,
            reason="likely-scanned: texto rapido bajo el minimo, probable OCR",
            scanned=True,
        )
    return LaneDecision(lane=LANE_MARKITDOWN, reason="plain: sin estructura, carril rapido")


def detect_xbrl(content: bytes, filename: str, content_type: str | None = None) -> bool:
    """Sniff barato (sin parsear) de instancia XBRL o filing iXBRL."""
    head = (content or b"")[:_XBRL_SNIFF_BYTES].lower()
    if any(marker in head for marker in _XBRL_MARKERS):
        return True
    lowered_name = (filename or "").lower()
    if lowered_name.endswith(("_htm.xml", ".xbrl", ".xml")):
        return True
    return "xml" in (content_type or "").lower() and head.lstrip().startswith(b"<")


def extract_xbrl_facts(content: bytes) -> list[dict[str, Any]]:
    """Facts XBRL serializados (JSON-safe) via el parser propio de la casa.

    Reutiliza el contrato de entrada de
    ``sec_xbrl_instance.parse_instance_dimensioned_facts`` (stream binario) sin
    modificarlo; el pipeline de fundamentales puede consumir la misma fuente.
    Best-effort sync-safe (stdlib): ante cualquier fallo devuelve [].
    """
    try:
        from app.services.connectors.sec_xbrl_instance import (
            parse_instance_dimensioned_facts,
        )

        facts = parse_instance_dimensioned_facts(BytesIO(content or b""))
    except Exception:  # noqa: BLE001 - XBRL nunca rompe la ingesta
        return []
    out: list[dict[str, Any]] = []
    for fact in facts[: max(1, xbrl_max_facts())]:
        try:
            out.append(
                {
                    "tag": fact.tag,
                    "value": str(fact.value),
                    "start": fact.start.isoformat() if fact.start else None,
                    "end": fact.end.isoformat() if fact.end else None,
                    "instant": fact.instant.isoformat() if fact.instant else None,
                    "members": [member for _axis, member in fact.members],
                }
            )
        except Exception:  # noqa: BLE001 - un fact roto no tira el resto
            continue
    return out


def convert_fast_markitdown(content: bytes, filename: str, ext: str) -> str:
    """Pre-filtro rapido a Markdown. Import perezoso; ausente -> _LaneUnavailable."""
    try:
        from markitdown import MarkItDown
    except Exception as exc:
        raise _LaneUnavailable(
            f"markitdown no instalado ({type(exc).__name__}); carril pypdf clasico."
        ) from exc
    try:
        converter = MarkItDown()
        method = getattr(converter, "convert_stream", None)
        if callable(method):
            result = method(BytesIO(content), file_extension=ext)
        else:  # pragma: no cover - compat con APIs antiguas
            result = converter.convert_stream(BytesIO(content))
        markdown = getattr(result, "markdown", None)
        if markdown is None:
            markdown = getattr(result, "text_content", "")
        text = str(markdown or "")
    except _LaneUnavailable:
        raise
    except Exception as exc:
        raise _LaneFailed(f"MarkItDown fallo ({type(exc).__name__}: {exc})") from exc
    if not text.strip():
        raise _LaneFailed("MarkItDown produjo texto vacio")
    return text


def _doc_page_count(doc: Any) -> int | None:
    pages = getattr(doc, "pages", None)
    try:
        if isinstance(pages, dict):
            return len(pages)
        if isinstance(pages, (list, tuple)):
            return len(pages)
        if isinstance(pages, int):
            return pages
    except Exception:  # noqa: BLE001 - provenance best-effort
        return None
    return None


def _prov_page(item: Any) -> int | None:
    prov = getattr(item, "prov", None) or []
    try:
        for entry in prov:
            page_no = getattr(entry, "page_no", None)
            if isinstance(page_no, int) and page_no >= 1:
                return page_no
    except Exception:  # noqa: BLE001 - provenance best-effort
        return None
    return None


def _is_table_item(item: Any, index: int) -> bool:  # noqa: ARG001
    label = getattr(item, "label", None)
    label_text = str(getattr(label, "value", label) or "").lower()
    if "table" in label_text:
        return True
    data = getattr(item, "data", None)
    return data is not None and (
        hasattr(data, "num_rows") or hasattr(data, "table_cells") or hasattr(data, "grid")
    )


def _table_inventory(doc: Any) -> list[dict[str, Any]]:
    tables = getattr(doc, "tables", None) or []
    inventory: list[dict[str, Any]] = []
    try:
        items = list(tables)
    except Exception:  # noqa: BLE001 - provenance best-effort
        return inventory
    for index, table in enumerate(items):
        data = getattr(table, "data", None)
        inventory.append(
            {
                "table_id": str(getattr(table, "self_ref", None) or f"#/tables/{index}"),
                "page": _prov_page(table),
                "rows": getattr(data, "num_rows", None),
                "cols": getattr(data, "num_cols", None),
            }
        )
    return inventory


def _table_markdown(item: Any, doc: Any, table_id: str) -> str:
    for attempt in (
        lambda: item.export_to_markdown(doc),
        lambda: item.export_to_markdown(),
    ):
        try:
            text = attempt()
        except Exception:  # noqa: BLE001 - firmas entre versiones de docling-core
            continue
        if isinstance(text, str) and text.strip():
            return text.strip()
    return f"[table {table_id}: export no disponible en esta version de docling]"


def _iter_docling_items(doc: Any) -> list[tuple[Any, int]]:
    iterate: Any = getattr(doc, "iterate_items", None)
    if callable(iterate):
        try:
            return [(item, level) for item, level in iterate()]  # type: ignore[misc]
        except Exception as exc:
            raise _LaneFailed(f"Docling iterate_items fallo ({exc})") from exc
    # Superficie antigua/alternativa: textos y tablas como atributos.
    items: list[tuple[Any, int]] = []
    for text in getattr(doc, "texts", None) or []:
        items.append((text, 0))
    for table in getattr(doc, "tables", None) or []:
        items.append((table, 0))
    if not items:
        raise _LaneFailed("Docling devolvio un documento sin items iterables")
    return items


def convert_heavy_docling(
    content: bytes,
    filename: str,
    ext: str,
    *,
    converter: Any | None = None,
) -> tuple[list[ParsedBlock], dict[str, Any]]:
    """Carril pesado Docling con provenance por pagina. SOLO worker.

    ``converter`` inyectable para tests hermeticos (evita descargar los ~500 MB
    de modelos). Import perezoso de ``docling``; ausente -> _LaneUnavailable
    con mensaje trazable. Cualquier fallo del conversor -> _LaneFailed (el
    orquestador degrada a pypdf).
    """
    if converter is None:
        try:
            from docling.document_converter import DocumentConverter
        except Exception as exc:
            raise _LaneUnavailable(
                f"docling no instalado ({type(exc).__name__}); carril pypdf clasico."
            ) from exc
        converter = DocumentConverter()

    import os as _os
    import tempfile as _tempfile

    suffix = ext if ext.startswith(".") else f".{ext}"
    with _tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as handle:
        handle.write(content)
        temp_path = handle.name
    try:
        try:
            result = converter.convert(temp_path)
        except Exception as exc:
            raise _LaneFailed(f"Docling fallo ({type(exc).__name__}: {exc})") from exc
        doc = getattr(result, "document", None)
        if doc is None:
            raise _LaneFailed("Docling devolvio un resultado sin documento")
        return _blocks_from_docling_document(doc)
    finally:
        try:
            _os.unlink(temp_path)
        except OSError:
            pass


def _blocks_from_docling_document(doc: Any) -> tuple[list[ParsedBlock], dict[str, Any]]:
    items = _iter_docling_items(doc)
    inventory = _table_inventory(doc)
    inventory_by_index = {index: entry for index, entry in enumerate(inventory)}
    blocks: list[ParsedBlock] = []
    table_index = 0
    for item, _level in items:
        page = _prov_page(item)
        if _is_table_item(item, table_index):
            entry = inventory_by_index.get(table_index, {})
            table_id = str(entry.get("table_id") or f"#/tables/{table_index}")
            text = _table_markdown(item, doc, table_id)
            blocks.append(
                ParsedBlock(
                    text=text,
                    metadata={
                        "extraction_lane": LANE_DOCLING,
                        "page": page,
                        "table_id": table_id,
                    },
                )
            )
            table_index += 1
            continue
        text = getattr(item, "text", None)
        if isinstance(text, str) and text.strip():
            blocks.append(
                ParsedBlock(
                    text=text.strip(),
                    metadata={"extraction_lane": LANE_DOCLING, "page": page},
                )
            )
    if not blocks:
        # El documento existe pero sin texto/tablas extraibles: que el
        # orquestador degrade a pypdf en vez de fabricar un vacio.
        raise _LaneFailed("Docling no extrajo bloques de texto ni tablas")
    info = {"page_count": _doc_page_count(doc), "tables": inventory}
    return blocks, info


def _fast_blocks(markdown: str) -> list[ParsedBlock]:
    # Un bloque por parrafo: el chunker los reagrupa hasta max_chars y cada
    # chunk conserva la lista block_metadata con su carril. El backend pdfminer
    # de MarkItDown separa paginas con \x0c: se aprovecha para provenance por
    # pagina tambien en el carril rapido. Sin separadores, page=None (honesto:
    # el backend pdfplumber de tablas no pagina).
    segments = [segment for segment in markdown.split("\x0c") if segment.strip()]
    paged = "\x0c" in markdown
    blocks: list[ParsedBlock] = []
    for index, segment in enumerate(segments):
        page = index + 1 if paged else None
        for paragraph in re.split(r"\n{2,}", segment):
            if paragraph.strip():
                blocks.append(
                    ParsedBlock(
                        text=paragraph.strip(),
                        metadata={"extraction_lane": LANE_MARKITDOWN, "page": page},
                    )
                )
    if not blocks:
        raise _LaneFailed("MarkItDown produjo texto vacio")
    return blocks


def _pypdf_fallback_blocks(content: bytes) -> tuple[list[ParsedBlock], str]:
    """Carril clasico con sello de carril aditivo (shape de bloques intacto)."""
    from app.services.document_ingestion_service import DocumentIngestionService

    parsed = DocumentIngestionService()._parse_pdf(content)
    for block in parsed.blocks:
        block.metadata = {**block.metadata, "extraction_lane": LANE_PYPDF}
    return parsed.blocks, parsed.parser


def parse_pdf_two_lane(
    content: bytes,
    filename: str,
    ext: str = ".pdf",
    *,
    content_type: str | None = None,
    allow_heavy: bool | None = None,
    converter: Any | None = None,
) -> ParsedDocument:
    """Orquestador de carriles para PDF (sync-safe por defecto).

    Nunca importa docling/markitdown a nivel de modulo y nunca construye el
    conversor pesado salvo que :func:`resolve_allow_heavy` lo autorice (worker
    o ``explicit=True``). Devuelve siempre ``ParsedDocument`` con el shape
    historico; la degradacion viaja en ``warnings``.
    """
    from app.services.document_ingestion_service import _compact

    flags = lane_flags()
    warnings: list[str] = []
    xbrl = detect_xbrl(content, filename, content_type)
    xbrl_facts: list[dict[str, Any]] = extract_xbrl_facts(content) if xbrl else []

    fast_markdown: str | None = None
    if flags["markitdown_enabled"]:
        try:
            fast_markdown = convert_fast_markitdown(content, filename, ext)
        except _LaneUnavailable as exc:
            warnings.append(f"{exc} Carril pypdf clasico.")
        except _LaneFailed as exc:
            warnings.append(f"{exc} Carril pypdf clasico.")
    else:
        warnings.append("MARKITDOWN_ENABLED=0: pre-filtro rapido desactivado; carril pypdf clasico.")

    force_heavy = bool(flags["docling_opt_in"]) or xbrl
    decision = decide_lane(fast_markdown, xbrl_detected=xbrl)
    if force_heavy and decision.lane == LANE_MARKITDOWN and fast_markdown:
        decision = LaneDecision(
            lane=LANE_DOCLING,
            reason="opt-in: CAVAAI_USE_DOCLING=1 o XBRL fuerza el carril pesado",
            xbrl_detected=xbrl,
        )

    blocks: list[ParsedBlock] = []
    parser = LANE_PYPDF
    fast_empty = not (fast_markdown or "").strip()
    heavy_attempted = False

    def _attempt_heavy(reason: str) -> bool:
        """Intento pesado con degradacion trazable. True si produjo bloques."""
        nonlocal blocks, parser, heavy_attempted
        heavy_attempted = True
        try:
            heavy_blocks, info = convert_heavy_docling(
                content, filename, ext, converter=converter
            )
        except _LaneUnavailable as exc:
            warnings.append(f"{exc} {reason}.")
            return False
        except _LaneFailed as exc:
            warnings.append(f"{exc} {reason}; carril rapido si existe, pypdf en ultima instancia.")
            return False
        blocks = heavy_blocks
        parser = LANE_DOCLING
        if info.get("tables"):
            warnings.append(
                f"Docling: {len(info['tables'])} tabla(s) en "
                f"{info.get('page_count') or '?'} pagina(s), provenance por pagina."
            )
        return True

    if decision.lane == LANE_DOCLING and flags["docling_lane_enabled"]:
        if resolve_allow_heavy(allow_heavy):
            _attempt_heavy(decision.reason)
        else:
            warnings.append(
                "Docling diferido al worker "
                f"({decision.reason}): ruta sincrona, se sirve el carril rapido. "
                "Reprocesar con el actor process_document_structured."
            )
    elif decision.lane == LANE_DOCLING and not flags["docling_lane_enabled"]:
        warnings.append("DOCLING_LANE_ENABLED=0: estructura detectada pero carril pesado apagado.")

    if not blocks and fast_markdown:
        blocks = _fast_blocks(fast_markdown)
        parser = LANE_MARKITDOWN

    if not blocks and fast_empty and flags["docling_lane_enabled"] and not heavy_attempted:
        # Sin pre-filtro no hay senal de estructura, pero el vacio puede ser un
        # escaneado que solo el OCR rescata: el worker lo intenta, la ruta
        # sincrona degrada con lo ya advertido (dependencia ausente/apagada).
        if resolve_allow_heavy(allow_heavy):
            _attempt_heavy("sin pre-filtro rapido")

    if not blocks:
        try:
            fallback_blocks, _ = _pypdf_fallback_blocks(content)
        except Exception as exc:  # noqa: BLE001 - PDF roto: fail closed con warning
            warnings.append(f"pypdf fallo ({type(exc).__name__}: {exc}); sin texto extraible.")
            fallback_blocks = []
        blocks = fallback_blocks
        parser = LANE_PYPDF
        if not any("pypdf" in warning.lower() for warning in warnings):
            warnings.append("Carril pypdf clasico.")

    if xbrl_facts:
        preview = ", ".join(
            f"{fact['tag']}={fact['value']}" for fact in xbrl_facts[:5]
        )
        blocks.append(
            ParsedBlock(
                text=(
                    f"XBRL facts estructurados ({len(xbrl_facts)}): {preview}"
                    f"{'...' if len(xbrl_facts) > 5 else ''}"
                ),
                metadata={
                    "extraction_lane": parser,
                    "page": None,
                    "xbrl_facts": xbrl_facts,
                    "xbrl_fact_count": len(xbrl_facts),
                },
            )
        )
    elif xbrl:
        warnings.append("XBRL detectado pero sin facts anuales dimensionados extraibles.")

    compacted = [
        ParsedBlock(text=_compact(block.text), metadata=block.metadata)
        for block in blocks
        if block.text.strip()
    ]
    return ParsedDocument(blocks=compacted, parser=parser, warnings=warnings)
