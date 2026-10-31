import hashlib
import os
import re
import struct
import zipfile
import zlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import redact_secrets
from app.core.tenancy import tenant_filters
from app.models import Document, DocumentChunk
from app.services.company_resolver import resolve_company
from app.services.document_store import DocumentStore
from app.services.document_visibility import is_immutable_archive_url
from app.services.evidence_contract import build_ingestion_evidence
from app.services.public_fetch import fetch_public_url

MAX_DOCUMENT_BYTES = 15 * 1024 * 1024
# Document.source_url es String(1000): la entrada de la ruta ya va acotada,
# pero la URL final de ingest-url puede crecer por redirects; este tope es
# la ultima linea antes del INSERT (Postgres rompe con 500 si se pasa).
MAX_SOURCE_URL_CHARS = 1000
SUPPORTED_EXTENSIONS = {".txt", ".md", ".html", ".htm", ".pdf", ".docx", ".xlsx", ".csv", ".tsv"}

# DOCX/XLSX son ZIP: el limite de 15 MB aplica al fichero comprimido, asi que
# un documento muy comprimible (zip bomb) podia inflarse a gigabytes dentro de
# python-docx/openpyxl. Se revisan los tamanos declarados en el directorio
# central y se comprueba el flujo DEFLATE real con salida acotada antes de
# pasarlo a python-docx/openpyxl. El directorio central no es de confianza.
MAX_OOXML_UNCOMPRESSED_BYTES = 200 * 1024 * 1024
MAX_OOXML_ENTRIES = 10_000
MAX_OOXML_ENTRY_RATIO = 200
OOXML_RATIO_MIN_ENTRY_BYTES = 1024 * 1024
# El tamaño ZIP no limita una hoja dispersa: dos celdas pueden declarar
# millones de filas/columnas. Presupuesto de recorrido, no de celdas pobladas.
MAX_XLSX_SHEETS = 100
MAX_XLSX_ROWS = 50_000
MAX_XLSX_COLUMNS = 512
MAX_XLSX_CELLS = 1_000_000


def _guard_ooxml_zip(content: bytes) -> None:
    """Rechaza DOCX/XLSX cuyo contenido descomprimido es desproporcionado."""
    try:
        with zipfile.ZipFile(BytesIO(content)) as archive:
            entries = archive.infolist()
    except zipfile.BadZipFile as exc:
        raise ValueError("El documento no es un DOCX/XLSX valido (ZIP corrupto)") from exc
    if len(entries) > MAX_OOXML_ENTRIES:
        raise ValueError("El documento tiene demasiadas entradas internas para ingerirlo")
    total = 0
    for entry in entries:
        total += entry.file_size
        if total > MAX_OOXML_UNCOMPRESSED_BYTES:
            raise ValueError("El documento descomprimido supera el limite de ingesta")
        if (
            entry.file_size >= OOXML_RATIO_MIN_ENTRY_BYTES
            and entry.file_size > MAX_OOXML_ENTRY_RATIO * max(entry.compress_size, 1)
        ):
            raise ValueError("El documento tiene una compresion anomala (posible zip bomb)")


    # ZipExtFile limita su salida a file_size (dato no fiable del directorio).
    # Validar el DEFLATE bruto evita que un tamano falsificado oculte expansion.
    actual_total = 0
    for entry in entries:
        if entry.flag_bits & 1:
            raise ValueError("El documento ZIP cifrado no esta admitido")
        if entry.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
            raise ValueError("El metodo de compresion del documento no esta admitido")
        offset = entry.header_offset
        if offset < 0 or offset + 30 > len(content):
            raise ValueError("El documento tiene una cabecera ZIP corrupta")
        header = struct.unpack_from("<4s5H3I2H", content, offset)
        if header[0] != b"PK\x03\x04" or header[3] != entry.compress_type:
            raise ValueError("El documento tiene una cabecera ZIP inconsistente")
        start = offset + 30 + header[-2] + header[-1]
        end = start + entry.compress_size
        if end > len(content):
            raise ValueError("El documento tiene datos ZIP truncados")
        inflater = zlib.decompressobj(-zlib.MAX_WBITS) if entry.compress_type == zipfile.ZIP_DEFLATED else None
        size = 0
        crc = 0
        try:
            for pos in range(start, end, 64 * 1024):
                chunk = content[pos:min(pos + 64 * 1024, end)]
                while chunk:
                    remaining = MAX_OOXML_UNCOMPRESSED_BYTES - actual_total
                    # Maximo 64 KiB de salida por iteracion, aunque el ZIP mienta.
                    output = inflater.decompress(chunk, min(64 * 1024, remaining + 1)) if inflater else chunk
                    size += len(output)
                    actual_total += len(output)
                    crc = zlib.crc32(output, crc)
                    if actual_total > MAX_OOXML_UNCOMPRESSED_BYTES:
                        raise ValueError("El documento descomprimido supera el limite real de ingesta")
                    chunk = inflater.unconsumed_tail if inflater else b""
            if inflater and (not inflater.eof or inflater.unused_data):
                raise ValueError("El documento tiene un flujo ZIP incompleto o inconsistente")
        except zlib.error as exc:
            raise ValueError("El documento contiene un flujo ZIP corrupto") from exc
        if size != entry.file_size or crc != entry.CRC:
            raise ValueError("El documento tiene tamanos o CRC ZIP inconsistentes")


# Nombre publico de la guarda OOXML: cualquier servicio que abra un DOCX/XLSX
# subido por el usuario (p. ej. la importacion de transacciones) debe aplicarla
# antes de parsear; el nombre con "_" era privado solo por historia del modulo.
guard_ooxml_zip = _guard_ooxml_zip


@dataclass
class ParsedBlock:
    text: str
    metadata: dict = field(default_factory=dict)


@dataclass
class ParsedDocument:
    blocks: list[ParsedBlock]
    parser: str
    warnings: list[str] = field(default_factory=list)


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []

    # Inline markup is not a paragraph boundary: SEC headings commonly split
    # Item / 1A / Risk Factors across spans. Block elements are boundaries.
    _BLOCK_TAGS = {"p", "div", "br", "tr", "td", "th", "li", "h1", "h2", "h3", "h4", "h5", "h6", "section", "table"}

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag.lower() in self._BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in self._BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        self._parts.append(re.sub(r"\s+", " ", data))

    def text(self) -> str:
        return "\n".join(" ".join(line.split()) for line in "".join(self._parts).splitlines())


def _compact(text: str) -> str:
    return re.sub(r"\n{3,}", "\n\n", text.replace("\r\n", "\n").replace("\r", "\n")).strip()


def _extension(filename: str, content_type: str | None = None) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix:
        return suffix
    content_type = (content_type or "").lower()
    if "pdf" in content_type:
        return ".pdf"
    if "spreadsheet" in content_type or "excel" in content_type:
        return ".xlsx"
    if "word" in content_type:
        return ".docx"
    if "html" in content_type:
        return ".html"
    return ".txt"


class DocumentIngestionService:
    def ingest_bytes(
        self,
        db: Session,
        *,
        ticker: str,
        title: str,
        content: bytes,
        filename: str,
        source_type: str,
        source_url: str | None = None,
        content_type: str | None = None,
        published_at: datetime | None = None,
        filing_metadata: dict | None = None,
    ) -> dict:
        if not content:
            raise ValueError("Document is empty")
        if source_url is not None and len(source_url) > MAX_SOURCE_URL_CHARS:
            raise ValueError("source_url exceeds 1000 characters")
        if len(content) > MAX_DOCUMENT_BYTES:
            raise ValueError("Document exceeds 15MB local ingestion limit")

        company = resolve_company(db, ticker)
        if not company:
            raise ValueError(f"Company {ticker.upper()} not found")

        checksum = hashlib.sha256(content).hexdigest()
        # F252: la re-ingesta diaria del mismo filing de la SEC deriva unos
        # pocos bytes y el checksum no la capturaba (cada dia, otra fila).
        # La identidad por URL solo se aplica a URLs de archivo inmutable:
        # una URL cualquiera puede servir contenido que cambia (feeds,
        # paginas vivas) y ante esa ambiguedad no se descarta nada; ahi el
        # checksum sigue siendo el unico criterio.
        duplicate = None
        duplicate_reason = None
        if is_immutable_archive_url(source_url):
            duplicate = db.scalar(
                select(Document).where(
                    Document.company_id == company.id,
                    Document.source_url == source_url,
                ).limit(1)
            )
            if duplicate is not None:
                duplicate_reason = "archive_url"
        if duplicate is None:
            duplicate = db.scalar(
                select(Document).where(Document.company_id == company.id, Document.checksum == checksum)
            )
            if duplicate is not None:
                duplicate_reason = "checksum"
        if duplicate:
            warning = (
                "Document from the same SEC archive URL already exists for this company; byte drift ignored."
                if duplicate_reason == "archive_url"
                else "Document with same checksum already exists for this company."
            )
            chunk_count = db.scalar(
                select(DocumentChunk.id)
                .where(
                    DocumentChunk.document_id == duplicate.id,
                    *tenant_filters(db, DocumentChunk),
                )
                .limit(1)
            )
            return {
                "status": "duplicate",
                "ticker": company.ticker,
                "document_id": duplicate.id,
                "chunks": 0 if chunk_count is None else len(duplicate.chunks),
                "checksum": checksum,
                "parser": duplicate.metadata_.get("parser", "unknown"),
                "storage_uri": duplicate.storage_uri,
                "warnings": [warning],
            }

        ext = _extension(filename, content_type)
        if ext not in SUPPORTED_EXTENSIONS:
            raise ValueError(f"Unsupported document extension: {ext}")

        parsed = self._parse(content, filename, ext, content_type)
        text = "\n\n".join(block.text for block in parsed.blocks if block.text.strip())
        if len(text.strip()) < 20:
            raise ValueError("Document parser produced too little text")

        storage_uri = DocumentStore().put_bytes(
            company.ticker,
            source_type or "manual",
            f"{checksum[:12]}-{filename}",
            content,
            tenant_id=db.info.get("tenant_id"),
            content_type=content_type or "application/octet-stream",
        )

        document = Document(
            company_id=company.id,
            title=title,
            source_type=source_type,
            source_url=source_url,
            storage_uri=storage_uri,
            published_at=published_at or datetime.now(UTC),
            checksum=checksum,
            metadata_={
                **{key: value for key, value in (filing_metadata or {}).items()
                   if key in {"form", "report_date", "period_of_report", "accession_number", "parent_form", "fiscal_quarter", "items"}},
                "parser": parsed.parser,
                "filename": filename,
                "content_type": content_type,
                "extension": ext,
                "raw_size_bytes": len(content),
                "block_count": len(parsed.blocks),
                "warnings": parsed.warnings,
                "docling_opt_in": os.getenv("CAVAAI_USE_DOCLING") == "1",
                # Tipo documental Jev (earnings/filing/macro/opinion): 1 llamada
                # best-effort (~$0.042/MTok in). Sin TYPESAFE_API_KEY o ante
                # error, la clave `jev_doc_type` simplemente no se guarda.
                **self._jev_doc_type_meta(text),
            },
        )
        db.add(document)
        db.flush()

        chunks = self._chunk_blocks(parsed.blocks, checksum, parsed.parser, filename, source_url)
        evidence = build_ingestion_evidence(
            tenant_id=db.info.get("tenant_id"), document_id=f"document:{document.id}",
            checksum=checksum, source_type=source_type, chunks=chunks, url=source_url,
            # Do not turn the existing fetched-at fallback into a publication date.
            published_on=published_at.date() if published_at else None,
        )
        document.metadata_ = {**document.metadata_, "evidence_contract": evidence}
        for index, chunk in enumerate(chunks):
            chunk["metadata"] = {
                **chunk["metadata"],
                "evidence_source_id": evidence.get("source_id"),
                "evidence_chunk_id": evidence.get("chunks", [{}] * len(chunks))[index].get("chunk_id"),
            }
            db.add(
                DocumentChunk(
                    document_id=document.id,
                    chunk_index=index,
                    text=chunk["text"],
                    token_count=len(chunk["text"].split()),
                    metadata_=chunk["metadata"],
                )
            )

        db.commit()
        db.refresh(document)

        filing_analysis = {"status": "not_applicable"}
        if db.info.get("tenant_id") is not None:
            try:
                from app.services.filing_intelligence import analyze_document, official_document

                if official_document(document):
                    filing_analysis = analyze_document(db, document)
                    db.commit()
            except Exception as exc:
                db.rollback()
                # Ingestion has already committed. A failed optional analysis
                # must not disguise a successfully persisted source as failure.
                filing_analysis = {"status": "failed", "error": type(exc).__name__}

        kpi_extraction = {"status": "not_queued"}
        if (
            os.getenv("CAVAAI_ENABLE_AUTO_KPI_EXTRACTION", "1") == "1"
            and get_settings().llm_enabled
            and db.info.get("tenant_id") is not None
            and db.info.get("user_id")
        ):
            from app.workers.dramatiq_app import enqueue_document_kpis

            kpi_extraction = enqueue_document_kpis(db, document)

        if os.getenv("CAVAAI_ENABLE_VECTOR_INGEST") == "1":
            try:
                from app.services.rag import RAGIndex

                rag_result = RAGIndex().ingest_document(db, document)
            except Exception as exc:
                rag_result = {"chunks_indexed": 0, "error": redact_secrets(str(exc))}
        else:
            rag_result = {"chunks_indexed": 0, "skipped": "Set CAVAAI_ENABLE_VECTOR_INGEST=1 to index Qdrant."}

        if os.getenv("CAVAAI_ENABLE_AUTO_RESEARCH", "1") == "1":
            try:
                from app.services.claim_intelligence_service import (
                    ClaimIntelligenceService,
                )

                intelligence_result = ClaimIntelligenceService().scan_document(
                    db, document, auto_apply=True
                )
            except Exception as exc:
                intelligence_result = {
                    "status": "failed",
                    "error": redact_secrets(str(exc)),
                    "document_id": document.id,
                }
        else:
            intelligence_result = {
                "status": "disabled",
                "document_id": document.id,
            }

        return {
            "status": "ingested",
            "ticker": company.ticker,
            "document_id": document.id,
            "chunks": len(chunks),
            "checksum": checksum,
            "parser": parsed.parser,
            "storage_uri": storage_uri,
            "kpi_extraction": kpi_extraction,
            "warnings": parsed.warnings,
            "rag": rag_result,
            "intelligence": intelligence_result,
            "filing_analysis": filing_analysis,
        }

    def ingest_url(
        self,
        db: Session,
        *,
        ticker: str,
        title: str,
        url: str,
        source_type: str,
    ) -> dict:
        content, content_type, final_url = fetch_public_url(
            url, max_bytes=MAX_DOCUMENT_BYTES, timeout=20
        )
        final_parsed_url = urlparse(final_url)
        filename = Path(final_parsed_url.path).name or f"{final_parsed_url.netloc}.html"
        return self.ingest_bytes(
            db,
            ticker=ticker,
            title=title,
            content=content,
            filename=filename,
            source_type=source_type,
            source_url=final_url,
            content_type=content_type,
        )

    @staticmethod
    def _jev_doc_type_meta(text: str) -> dict:
        """Clasifica el tipo documental con Jev (1 llamada best-effort).

        Coste ~$0.042/MTok in. Fallback: sin TYPESAFE_API_KEY o ante error
        devuelve {} y el documento se ingiere sin `jev_doc_type`.
        """
        try:
            from app.services.jev_triage_service import (
                classify_doc_type_sync,
                jev_metadata,
            )

            meta = jev_metadata(classify_doc_type_sync(text))
        except Exception:  # noqa: BLE001 — Jev nunca rompe la ingesta
            return {}
        return {"jev_doc_type": meta} if meta is not None else {}

    def _parse(self, content: bytes, filename: str, ext: str, content_type: str | None) -> ParsedDocument:
        if ext == ".pdf":
            # Pipeline en dos carriles (MarkItDown rapido / Docling estructura
            # solo-worker / pypdf clasico). Sync-safe por defecto: el carril
            # pesado solo corre dentro del worker (ver docling_pipeline.py).
            from app.services.docling_pipeline import parse_pdf_two_lane

            return parse_pdf_two_lane(content, filename, ext, content_type=content_type)
        return self._parse_native(content, ext)

    def _parse_native(self, content: bytes, ext: str) -> ParsedDocument:
        if ext in {".txt", ".md", ".csv", ".tsv"}:
            return self._parse_text(content, ext)
        if ext in {".html", ".htm"}:
            return self._parse_html(content)
        if ext == ".pdf":
            return self._parse_pdf(content)
        if ext == ".docx":
            _guard_ooxml_zip(content)
            return self._parse_docx(content)
        if ext == ".xlsx":
            _guard_ooxml_zip(content)
            return self._parse_xlsx(content)
        return self._parse_text(content, ext)

    def _parse_text(self, content: bytes, ext: str) -> ParsedDocument:
        text = content.decode("utf-8", errors="replace")
        return ParsedDocument(
            blocks=[ParsedBlock(text=_compact(text), metadata={"format": ext.lstrip(".")})],
            parser="native_text",
        )

    def _parse_html(self, content: bytes) -> ParsedDocument:
        parser = _HTMLTextExtractor()
        parser.feed(content.decode("utf-8", errors="replace"))
        return ParsedDocument(
            blocks=[ParsedBlock(text=_compact(parser.text()), metadata={"format": "html"})],
            parser="native_html",
        )

    def _parse_pdf(self, content: bytes) -> ParsedDocument:
        from pypdf import PdfReader

        reader = PdfReader(BytesIO(content))
        blocks = []
        for page_index, page in enumerate(reader.pages):
            text = _compact(page.extract_text() or "")
            if text:
                blocks.append(ParsedBlock(text=text, metadata={"page": page_index + 1}))
        return ParsedDocument(blocks=blocks, parser="pypdf")

    def _parse_docx(self, content: bytes) -> ParsedDocument:
        from docx import Document as DocxDocument

        document = DocxDocument(BytesIO(content))
        blocks = []
        from docx.table import Table
        from docx.text.paragraph import Paragraph

        def contents(parent):
            element = parent._element.body if hasattr(parent._element, "body") else parent._tc
            for child in element.iterchildren():
                if child.tag.endswith("}p"):
                    yield Paragraph(child, parent)
                elif child.tag.endswith("}tbl"):
                    yield Table(child, parent)

        def table_text(table):
            rows = []
            for row in table.rows:
                values = []
                seen = set()
                for cell in row.cells:
                    # Las celdas fusionadas aparecen repetidas en row.cells.
                    if cell._tc in seen:
                        continue
                    seen.add(cell._tc)
                    parts = [table_text(item) if isinstance(item, Table) else item.text
                             for item in contents(cell)]
                    values.append(_compact(" ".join(parts)))
                if any(values):
                    rows.append(" | ".join(values))
            return "\n".join(rows)

        for index, item in enumerate(contents(document)):
            is_table = isinstance(item, Table)
            text = table_text(item) if is_table else _compact(item.text)
            if text:
                kind = "table" if is_table else "paragraph"
                blocks.append(ParsedBlock(text=text, metadata={kind: index + 1}))
        return ParsedDocument(blocks=blocks, parser="python_docx")

    def _parse_xlsx(self, content: bytes) -> ParsedDocument:
        # Comprobar coordenadas XML ANTES de iter_rows: con dimension ausente
        # openpyxl puede expandir una fila enorme antes de devolverla.
        # defusedxml: el XLSX lo sube el usuario; sus XML internos no pueden
        # declarar entidades (billion laughs) - se rechazan sin expandir.
        from defusedxml.ElementTree import iterparse
        from openpyxl import load_workbook
        from openpyxl.utils.cell import coordinate_to_tuple

        total_area = 0
        with zipfile.ZipFile(BytesIO(content)) as archive:
            sheets = [name for name in archive.namelist()
                      if re.fullmatch(r"xl/worksheets/[^/]+\.xml", name)]
            if len(sheets) > MAX_XLSX_SHEETS:
                raise ValueError("El XLSX tiene demasiadas hojas para ingerirlo")
            for name in sheets:
                height = width = 0
                with archive.open(name) as stream:
                    for _, element in iterparse(stream, events=("end",)):
                        tag = element.tag.rsplit("}", 1)[-1]
                        coordinates = []
                        if tag == "dimension" and element.get("ref"):
                            coordinates = element.get("ref").split(":")
                        elif tag == "c" and element.get("r"):
                            coordinates = [element.get("r")]
                        elif tag == "row" and element.get("r"):
                            height = max(height, int(element.get("r")))
                        for coordinate in coordinates:
                            row, column = coordinate_to_tuple(coordinate)
                            height, width = max(height, row), max(width, column)
                        if (height > MAX_XLSX_ROWS or width > MAX_XLSX_COLUMNS
                                or total_area + height * width > MAX_XLSX_CELLS):
                            raise ValueError("Las dimensiones del XLSX superan el limite de ingesta")
                        element.clear()
                total_area += height * width
        workbook = load_workbook(BytesIO(content), read_only=True, data_only=True)
        blocks = []
        cells = 0
        try:
            if len(workbook.worksheets) > MAX_XLSX_SHEETS:
                raise ValueError("El XLSX tiene demasiadas hojas para ingerirlo")
            for sheet in workbook.worksheets:
                height, width = sheet.max_row or 0, sheet.max_column or 0
                if (height > MAX_XLSX_ROWS or width > MAX_XLSX_COLUMNS
                        or height * width > MAX_XLSX_CELLS - cells):
                    raise ValueError("Las dimensiones del XLSX superan el limite de ingesta")
                rows = []
                # También se cuenta el recorrido real: dimensiones ausentes o
                # incorrectas no pueden saltarse el presupuesto del documento.
                for index, row in enumerate(sheet.iter_rows(values_only=True), start=1):
                    cells += len(row)
                    if (index > MAX_XLSX_ROWS or len(row) > MAX_XLSX_COLUMNS
                            or cells > MAX_XLSX_CELLS):
                        raise ValueError("El XLSX supera el limite de celdas de ingesta")
                    values = [str(value) for value in row if value is not None]
                    if values:
                        rows.append(" | ".join(values))
                if rows:
                    blocks.append(ParsedBlock(text="\n".join(rows), metadata={"sheet": sheet.title}))
        finally:
            workbook.close()
        return ParsedDocument(blocks=blocks, parser="openpyxl")

    def _chunk_blocks(
        self,
        blocks: list[ParsedBlock],
        checksum: str,
        parser: str,
        filename: str,
        source_url: str | None,
        max_chars: int = 2500,
    ) -> list[dict]:
        chunks: list[dict] = []
        current_text: list[str] = []
        current_meta: list[dict] = []

        def flush() -> None:
            if not current_text:
                return
            text = _compact("\n\n".join(current_text))
            if not text:
                current_text.clear()
                current_meta.clear()
                return
            chunks.append(
                {
                    "text": text,
                    "metadata": {
                        "checksum": checksum,
                        "parser": parser,
                        "filename": filename,
                        "source_url": source_url,
                        "block_metadata": list(current_meta),
                        "chunk_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                    },
                }
            )
            current_text.clear()
            current_meta.clear()

        for block in blocks:
            text = _compact(block.text)
            if not text:
                continue
            if len(text) > max_chars:
                flush()
                # Keep each short line intact, especially section headings.
                # Split only oversized lines and retain paragraph boundaries.
                lines = []
                for line in text.splitlines():
                    while len(line) > max_chars:
                        cut = line.rfind(" ", 0, max_chars + 1)
                        if cut <= 0:
                            cut = max_chars
                        lines.append(line[:cut])
                        line = line[cut:].lstrip(" ")
                    lines.append(line)
                piece: list[str] = []
                for line in lines:
                    if piece and len("\n".join([*piece, line])) > max_chars:
                        current_text.append("\n".join(piece))
                        current_meta.append(block.metadata)
                        flush()
                        piece = []
                    piece.append(line)
                if piece:
                    current_text.append("\n".join(piece))
                    current_meta.append(block.metadata)
                continue
            if sum(len(item) + 2 for item in current_text) + len(text) > max_chars:
                flush()
            current_text.append(text)
            current_meta.append(block.metadata)
        flush()
        return chunks
