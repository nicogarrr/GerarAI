"""Contratos de entrada y parser Markdown de EPUB, sin servicios externos."""

import io
import zipfile

import pytest

from app.services import thesis_epub_service as svc


@pytest.mark.parametrize(
    "field,value,message",
    [
        ("version", "1", "version must be int"),
        ("sections", {}, "sections must be a list"),
        ("sections", ["bad"], r"sections\[1\] must be EpubSection"),
        ("citations", "bad", "citations must be a list"),
        ("citations", [3], r"citations\[\] must be str"),
        ("ticker", 4, "ticker must be str"),
    ],
)
def test_entradas_invalidas_fallan_explicitas(field, value, message):
    data = svc.ThesisEpubData(ticker="TEST")
    setattr(data, field, value)
    with pytest.raises(TypeError, match=message):
        svc.build_thesis_epub(data)


def test_nulos_titulos_vacios_y_slugs_duplicados():
    data = svc.ThesisEpubData(
        ticker=None,
        company_name=None,
        citations=None,
        executive_summary=None,
        sections=[
            svc.EpubSection("", None),
            svc.EpubSection("Riesgos", "a"),
            svc.EpubSection("Riesgos", "b"),
        ],
    )
    with zipfile.ZipFile(io.BytesIO(svc.build_thesis_epub(data))) as archive:
        names = archive.namelist()
        assert "EPUB/seccion-01-seccion-1.xhtml" in names
        assert "EPUB/seccion-02-riesgos.xhtml" in names
        assert "EPUB/seccion-03-riesgos-3.xhtml" in names
        summary = archive.read("EPUB/resumen.xhtml").decode()
        assert "Sin resumen ejecutivo disponible." in summary
        assert "Sin citas registradas" in archive.read("EPUB/citas.xhtml").decode()
        assert "UNKNOWN" in archive.read("EPUB/portada.xhtml").decode()


def test_escritor_fallido_no_devuelve_bytes_vacios(monkeypatch):
    monkeypatch.setattr(svc.epub, "write_epub", lambda buffer, book: False)
    with pytest.raises(RuntimeError, match="no se pudo generar el EPUB de TEST v1"):
        svc.build_thesis_epub(svc.ThesisEpubData(ticker="TEST"))


def test_markdown_listas_cambio_tipo_y_tabla_rellena():
    body = "# Titulo\n\n- uno\n* dos\n1. tres\n2) cuatro\ntexto\n\nA|B\n---|---\nx|y\nz|\n"
    assert svc.markdown_lite_to_html(body) == (
        "<h2>Titulo</h2>\n<ul><li>uno</li><li>dos</li></ul>\n"
        "<ol><li>tres</li><li>cuatro</li></ol>\n<p>texto</p>\n"
        "<table><thead><tr><th>A</th><th>B</th></tr></thead><tbody>"
        "<tr><td>x</td><td>y</td></tr><tr><td>z</td><td></td></tr></tbody></table>"
    )
    assert svc.markdown_lite_to_html(None) == "<p></p>"
    assert svc._is_table_separator("|---||") is False
    assert svc._split_table_row("a|b") == ["a", "b"]


@pytest.mark.parametrize(
    "filename,index,title",
    [
        ("portada.xhtml", 0, "Portada"),
        ("resumen.xhtml", 1, "Resumen ejecutivo"),
        ("citas.xhtml", 4, "Citas y evidencia"),
        ("aviso.xhtml", 5, "Aviso legal"),
        ("one.xhtml", 2, "Título"),
        ("two.xhtml", 3, "Sección 2"),
        ("unknown.xhtml", 10, "unknown.xhtml"),
        ("negative.xhtml", 0, "negative.xhtml"),
    ],
)
def test_etiquetas_navegacion(filename, index, title):
    data = svc.ThesisEpubData(ticker="TEST", sections=[svc.EpubSection("Título"), svc.EpubSection("")])
    assert svc._nav_label(filename, data, index) == title
