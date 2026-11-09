"""Ingesta de documentos: parsers nativos, limites XLSX y el troceador.

Sin red y sin disco: DOCX/XLSX se generan al vuelo con python-docx/openpyxl
(datos sinteticos) y el PDF con pypdf. El dispatch PDF al pipeline de dos
carriles va doblado (docling_pipeline se mide en su propio modulo). El
troceador (_chunk_blocks) se prueba por llamada directa con bloques sinteticos.

NO prueba (declarado): el pipeline docling real (doblado en el dispatch); un
PDF real con texto extraible (pypdf no escribe texto: la rama del bloque con
texto de _parse_pdf, linea 543, queda no cubierta); las segundas comprobaciones
de presupuesto XLSX tras load_workbook (627 y 632: openpyxl normaliza o descarta
en silencio cualquier incoherencia que las alcanzaria, defensivas); 668-670 del
troceador (defensivas: current_text nunca puede compactar a vacio por el filtro
previo de bloques); ni la rama 712->715 (piece nunca queda vacia al final del
bucle: toda linea se re-anade tras cada flush).
"""

from __future__ import annotations

import zipfile
from io import BytesIO

import pytest
from docx import Document as DocxDocument
from openpyxl import Workbook
from pypdf import PdfWriter

import app.services.document_ingestion_service as dis
from app.services.document_ingestion_service import DocumentIngestionService, ParsedBlock

SERVICIO = DocumentIngestionService()


def _xlsx_bytes(libro) -> bytes:
    buffer = BytesIO()
    libro.save(buffer)
    return buffer.getvalue()


def test_parse_pdf_despacha_al_pipeline_de_dos_carriles(monkeypatch):
    """El PDF nunca lo parsea el carril nativo desde ingest: va al pipeline de
    dos carriles (aqui doblado) con su content_type."""
    import app.services.docling_pipeline as docling

    llamadas = []
    centinela = dis.ParsedDocument(blocks=[], parser="doble-docling")

    def _doble(content, filename, ext, *, content_type=None):
        llamadas.append((filename, ext, content_type))
        return centinela

    monkeypatch.setattr(docling, "parse_pdf_two_lane", _doble)
    resultado = SERVICIO._parse(b"%PDF-falso", "informe.pdf", ".pdf",
                                content_type="application/pdf")
    assert resultado is centinela
    assert llamadas == [("informe.pdf", ".pdf", "application/pdf")]


def test_parse_nativo_html():
    resultado = SERVICIO._parse_native(
        b"<html><body><p>Primer parrafo</p><p>Segundo parrafo</p></body></html>",
        ".html")
    assert resultado.parser == "native_html"
    (bloque,) = resultado.blocks
    assert "Primer parrafo" in bloque.text
    assert "Segundo parrafo" in bloque.text
    assert bloque.metadata == {"format": "html"}


def test_parse_nativo_pdf_con_pypdf():
    """PDF real de una pagina en blanco (generado con pypdf): sin bloques."""
    buffer = BytesIO()
    escritor = PdfWriter()
    escritor.add_blank_page(width=612, height=792)
    escritor.write(buffer)
    resultado = SERVICIO._parse_native(buffer.getvalue(), ".pdf")
    assert resultado.parser == "pypdf"
    assert resultado.blocks == []


def test_parse_nativo_extension_desconocida_cae_a_texto():
    resultado = SERVICIO._parse_native(b"texto plano sin formato conocido", ".bin")
    assert resultado.parser == "native_text"


def test_parse_docx_parrafos_tablas_celdas_fusionadas_y_anidadas():
    """DOCX real (python-docx): parrafo vacio que se salta, tabla con celdas
    fusionadas (deduplicadas) y tabla anidada dentro de una celda."""
    documento = DocxDocument()
    documento.add_paragraph("")  # parrafo vacio: no genera bloque
    documento.add_paragraph("Parrafo inicial del documento")
    tabla = documento.add_table(rows=3, cols=2)
    tabla.cell(0, 0).merge(tabla.cell(0, 1))  # fusionada: aparece dos veces
    tabla.cell(0, 0).text = "Cabecera fusionada"
    tabla.cell(1, 0).text = "Valor uno"
    anidada = tabla.cell(1, 1).add_table(rows=1, cols=1)
    anidada.cell(0, 0).text = "Dato anidado"
    # la fila 2 queda vacia: no aporta linea al texto de la tabla
    buffer = BytesIO()
    documento.save(buffer)

    resultado = SERVICIO._parse_native(buffer.getvalue(), ".docx")
    assert resultado.parser == "python_docx"
    textos = [bloque.text for bloque in resultado.blocks]
    assert any("Parrafo inicial del documento" in texto for texto in textos)
    tabla_texto = next(texto for texto in textos if "Cabecera fusionada" in texto)
    assert tabla_texto.count("Cabecera fusionada") == 1  # fusionada solo una vez
    assert "Valor uno" in tabla_texto
    assert "Dato anidado" in tabla_texto
    assert tabla_texto.count("\n") == 1  # dos filas con valores, la vacia no cuenta


def test_xlsx_demasiadas_hojas_rechazado(monkeypatch):
    """El presupuesto de hojas corta antes de parsear (constante bajada con
    monkeypatch para no construir 101 hojas)."""
    monkeypatch.setattr(dis, "MAX_XLSX_SHEETS", 2)
    libro = Workbook()
    libro.create_sheet("dos")
    libro.create_sheet("tres")
    with pytest.raises(ValueError, match="demasiadas hojas"):
        SERVICIO._parse_native(_xlsx_bytes(libro), ".xlsx")


def test_xlsx_dimension_desproporcionada_rechazada(monkeypatch):
    """La dimension declarada en el XML supera el presupuesto de filas (constante
    bajada con monkeypatch)."""
    monkeypatch.setattr(dis, "MAX_XLSX_ROWS", 5)
    libro = Workbook()
    hoja = libro.active
    for i in range(10):
        hoja.cell(row=i + 1, column=1, value=f"fila {i}")
    with pytest.raises(ValueError, match="dimensiones del XLSX"):
        SERVICIO._parse_native(_xlsx_bytes(libro), ".xlsx")



def test_xlsx_recorrido_real_supera_el_presupuesto(monkeypatch):
    """Sin atributos r ni dimension, el XML no declara altura: el presupuesto lo
    hace cumplir el recorrido real de iter_rows. Incluye una fila vacia (se
    salta sin aportar valores). XLSX minimo escrito a mano (sintetico)."""
    monkeypatch.setattr(dis, "MAX_XLSX_ROWS", 3)
    fila_datos = '<row><c t="inlineStr"><is><t>x</t></is></c></row>'
    hoja_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f"<sheetData>{fila_datos}<row></row>{fila_datos}{fila_datos}</sheetData>"
        "</worksheet>"
    )
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml",
                    '<?xml version="1.0" encoding="UTF-8"?>'
                    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                    '<Default Extension="xml" ContentType="application/xml"/>'
                    '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                    '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                    "</Types>")
        zf.writestr("_rels/.rels",
                    '<?xml version="1.0" encoding="UTF-8"?>'
                    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
                    "</Relationships>")
        zf.writestr("xl/workbook.xml",
                    '<?xml version="1.0" encoding="UTF-8"?>'
                    '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                    '<sheets><sheet name="H1" sheetId="1" r:id="rId1"/></sheets></workbook>')
        zf.writestr("xl/_rels/workbook.xml.rels",
                    '<?xml version="1.0" encoding="UTF-8"?>'
                    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
                    "</Relationships>")
        zf.writestr("xl/worksheets/sheet1.xml", hoja_xml)
    with pytest.raises(ValueError, match="limite de celdas|supera el limite"):
        SERVICIO._parse_native(buffer.getvalue(), ".xlsx")


def test_xlsx_hoja_sin_valores_no_emite_bloque():
    """Una hoja vacia no aporta bloque; la que tiene valores, si."""
    libro = Workbook()
    libro.active.title = "vacia"
    hoja2 = libro.create_sheet("con_datos")
    hoja2["A1"] = "dato relevante"
    resultado = SERVICIO._parse_native(_xlsx_bytes(libro), ".xlsx")
    assert resultado.parser == "openpyxl"
    assert len(resultado.blocks) == 1
    assert resultado.blocks[0].metadata == {"sheet": "con_datos"}
    assert "dato relevante" in resultado.blocks[0].text


def test_chunker_linea_larga_sin_espacios_y_respeto_de_parraros():
    """Una linea que no cabe se corta por el ultimo espacio; sin espacios, por
    el maximo. Cada trozo respeta el tope y el corte no pierde caracteres."""
    bloques = [ParsedBlock(text="cabecera", metadata={"page": 1}),
               ParsedBlock(text="palabra " * 30 + "x" * 120, metadata={"page": 2})]
    chunks = SERVICIO._chunk_blocks(bloques, "sum", "native_text", "f.txt", None,
                                    max_chars=100)
    assert len(chunks) >= 3  # cabecera sola + la linea larga en varios trozos
    assert chunks[0]["text"] == "cabecera"
    # Primer bloque ya demasiado largo: flush sin pendientes (no emite vacio).
    solos = SERVICIO._chunk_blocks([ParsedBlock(text="y" * 250, metadata={})],
                                   "sum", "native_text", "f.txt", None,
                                   max_chars=100)
    assert all(chunk["text"] for chunk in solos)
    for chunk in chunks:
        for linea in chunk["text"].splitlines():
            assert len(linea) <= 100
    unido = " ".join(c["text"] for c in chunks).replace(" ", "")
    assert "x" * 120 in unido  # el token sin espacios no pierde letras


def test_chunker_flush_al_superar_el_maximo_con_bloques_pequenos():
    """Bloques pequenos se juntan hasta el tope; al superarlo se cierra el
    chunk y se abre otro."""
    bloques = [ParsedBlock(text="a" * 30, metadata={"page": 1}),
               ParsedBlock(text="b" * 30, metadata={"page": 2}),
               ParsedBlock(text="c" * 30, metadata={"page": 3})]
    chunks = SERVICIO._chunk_blocks(bloques, "sum", "native_text", "f.txt", None,
                                    max_chars=70)
    assert [chunk["text"] for chunk in chunks] == ["a" * 30 + "\n\n" + "b" * 30,
                                                   "c" * 30]
    assert chunks[0]["metadata"]["block_metadata"] == [{"page": 1}, {"page": 2}]


def test_chunker_bloque_vacio_se_salta():
    bloques = [ParsedBlock(text="   \n  ", metadata={}),
               ParsedBlock(text="contenido real", metadata={"page": 1})]
    chunks = SERVICIO._chunk_blocks(bloques, "sum", "native_text", "f.txt", None)
    assert [chunk["text"] for chunk in chunks] == ["contenido real"]
