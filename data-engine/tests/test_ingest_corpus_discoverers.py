"""Parsing de los discoverers del corpus libre (fixtures HTML inline)."""

import re

from app.services.corpus_ingestion_service import (
    _extract_azvalor_gateway,
    _extract_azvalor_pages,
    _extract_magallanes_pdfs,
)


def test_azvalor_index_extrae_solo_paginas_de_cartas():
    html = '''
    <a href="https://www.azvalor.com/anuncios-y-comunicados/carta-a-inversores-1s2026/">x</a>
    <a href="https://www.azvalor.com/anuncios-y-comunicados/carta-trimestral-4t2022/">x</a>
    <a href="https://www.azvalor.com/anuncios-y-comunicados/otro-comunicado/">x</a>
    '''
    pages = _extract_azvalor_pages(html)
    assert pages == [
        "https://www.azvalor.com/anuncios-y-comunicados/carta-a-inversores-1s2026/",
        "https://www.azvalor.com/anuncios-y-comunicados/carta-trimestral-4t2022/",
    ]


def test_azvalor_gateway_solo_enlace_descarga_carta():
    html = '''
    <a href="https://www.azvalor.com/wp-content/uploads/2025/03/ISO-27001.2022-Azvalor.pdf">x</a>
    <a href="https://www.azvalor.com/azvalor-carta-a-inversores-2s2025/">Descargar carta en PDF</a>
    '''
    assert _extract_azvalor_gateway(html) == "https://www.azvalor.com/azvalor-carta-a-inversores-2s2025/"
    antiguo = '<a href="https://www.azvalor.com/wp-content/uploads/2024/05/Azvalor-Carta-Trimestral-4T2022.pdf">x</a>'
    assert _extract_azvalor_gateway(antiguo) == (
        "https://www.azvalor.com/wp-content/uploads/2024/05/Azvalor-Carta-Trimestral-4T2022.pdf"
    )
    assert _extract_azvalor_gateway("<p>sin enlace</p>") is None



def test_magallanes_solo_cartas_pdf_sin_anchor():
    html = '''
    <a href="https://magallanesvalue.com/wp-content/uploads/MAGALLANES-CARTA-1T26.pdf#new_tab">x</a>
    <a href="https://magallanesvalue.com/wp-content/uploads/MAGALLANES-LETTER-1Q26.pdf#new_tab">x</a>
    <a href="https://magallanesvalue.com/wp-content/uploads/HR-Iberian-30.06.2026.pdf#new_tab">x</a>
    '''
    assert _extract_magallanes_pdfs(html) == [
        "https://magallanesvalue.com/wp-content/uploads/MAGALLANES-CARTA-1T26.pdf",
        "https://magallanesvalue.com/wp-content/uploads/MAGALLANES-LETTER-1Q26.pdf",
    ]



def test_buffett_manifest_completo_y_coherente():
    from datetime import date

    from app.services.corpus_ingestion_service import BUFFETT_LETTERS, _buffett_sources

    years = [year for year, _, _ in BUFFETT_LETTERS]
    assert years == list(range(1977, 2025))
    for year, path, published in BUFFETT_LETTERS:
        assert re.fullmatch(r"[a-z0-9]+\.(?:html|pdf)", path), path
        assert str(year) in path, (year, path)
        assert published is None or (
            isinstance(published, date) and published.year == year + 1
        ), (year, published)

    sources = _buffett_sources()
    assert len(sources) == 48
    for source, (year, path, published) in zip(sources, BUFFETT_LETTERS, strict=True):
        assert source["url"] == f"https://www.berkshirehathaway.com/letters/{path}"
        assert source["author"] == "Warren E. Buffett (Berkshire Hathaway)"
        assert source["document_type"] == "fund_letter"
        assert source["published_on"] is published
        assert source["title"].endswith(str(year))
