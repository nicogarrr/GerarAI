"""Bordes de sec_fact_anchor: contextos sin fin o con fecha invalida, valores
guion/basura, period_bounds con quarter_start explicito, salidas tempranas de
source_link y el fallback de ejercicios de 52/53 semanas.
"""

from __future__ import annotations

from datetime import date

from app.services.sec_fact_anchor import contexts, find_anchor, period_bounds, source_link

DOC = "https://www.sec.gov/Archives/edgar/data/1/doc.htm"

HTML_BASE = """
<xbrli:context id="c-1"><xbrli:entity><xbrli:identifier>1</xbrli:identifier></xbrli:entity>
<xbrli:period><xbrli:startDate>2026-07-01</xbrli:startDate><xbrli:endDate>2026-09-30</xbrli:endDate></xbrli:period>
</xbrli:context>
"""

HTML_52W = """
<xbrli:context id="c-a"><xbrli:entity><xbrli:identifier>1</xbrli:identifier></xbrli:entity>
<xbrli:period><xbrli:startDate>2025-06-29</xbrli:startDate><xbrli:endDate>2026-06-27</xbrli:endDate></xbrli:period>
</xbrli:context>
<xbrli:context id="c-dim"><xbrli:entity><xbrli:identifier>1</xbrli:identifier>
<xbrli:segment><xbrldi:explicitMember dimension="d:A">x:M</xbrldi:explicitMember></xbrli:segment></xbrli:entity>
<xbrli:period><xbrli:startDate>2025-06-29</xbrli:startDate><xbrli:endDate>2026-06-27</xbrli:endDate></xbrli:period>
</xbrli:context>
<xbrli:context id="c-b"><xbrli:entity><xbrli:identifier>1</xbrli:identifier></xbrli:entity>
<xbrli:period><xbrli:startDate>2025-06-30</xbrli:startDate><xbrli:endDate>2026-06-27</xbrli:endDate></xbrli:period>
</xbrli:context>
<td><ix:nonFraction unitRef="usd" contextRef="c-b" name="us-gaap:Revenues" id="f-52" scale="0"
 format="ixt:num-dot-decimal">1000</ix:nonFraction></td>
"""

# 354 días: fuera de la tolerancia de ±10 alrededor de 365 (53 semanas son 371).
HTML_52W_FUERA = """
<xbrli:context id="c-fuera"><xbrli:entity><xbrli:identifier>1</xbrli:identifier></xbrli:entity>
<xbrli:period><xbrli:startDate>2025-07-08</xbrli:startDate><xbrli:endDate>2026-06-27</xbrli:endDate></xbrli:period>
</xbrli:context>
<td><ix:nonFraction unitRef="usd" contextRef="c-fuera" name="us-gaap:Revenues" id="f-fuera" scale="0"
 format="ixt:num-dot-decimal">1000</ix:nonFraction></td>
"""


def test_contexts_sin_fecha_de_fin_se_saltan():
    html = (
        HTML_BASE
        + """
<xbrli:context id="c-sin-fin"><xbrli:entity><xbrli:identifier>1</xbrli:identifier></xbrli:entity>
<xbrli:period></xbrli:period>
</xbrli:context>
"""
    )
    assert set(contexts(html)) == {"c-1"}


def test_contexts_con_fecha_invalida_se_saltan():
    html = (
        HTML_BASE
        + """
<xbrli:context id="c-mala"><xbrli:entity><xbrli:identifier>1</xbrli:identifier></xbrli:entity>
<xbrli:period><xbrli:endDate>2026-13-99</xbrli:endDate></xbrli:period>
</xbrli:context>
"""
    )
    assert set(contexts(html)) == {"c-1"}


def test_find_anchor_sin_contextos_candidatos_devuelve_none():
    assert (
        find_anchor(
            HTML_BASE,
            concepts=("us-gaap:Revenues",),
            end=date(2026, 12, 31),
            start=date(2026, 10, 1),
            value=1000,
            doc_url=DOC,
        )
        is None
    )


def test_find_anchor_valor_basura_se_salta():
    html = (
        HTML_BASE
        + """
<td><ix:nonFraction unitRef="usd" contextRef="c-1" name="us-gaap:Revenues" id="f-basura"
 format="ixt:num-dot-decimal">N/D</ix:nonFraction></td>
"""
    )
    assert (
        find_anchor(
            html,
            concepts=("us-gaap:Revenues",),
            end=date(2026, 9, 30),
            start=date(2026, 7, 1),
            value=1000,
            doc_url=DOC,
        )
        is None
    )


def test_find_anchor_guion_largo_vale_cero():
    html = (
        HTML_BASE
        + """
<td><ix:nonFraction unitRef="usd" contextRef="c-1" name="us-gaap:Revenues" id="f-cero"
 format="ixt:num-dot-decimal">—</ix:nonFraction></td>
"""
    )
    anchor = find_anchor(
        html,
        concepts=("us-gaap:Revenues",),
        end=date(2026, 9, 30),
        start=date(2026, 7, 1),
        value=0,
        doc_url=DOC,
    )
    assert anchor is not None
    assert anchor.element_id == "f-cero"
    assert anchor.value == 0


def test_period_bounds_con_quarter_start_explicito():
    assert period_bounds("2026-09-30:Q3", quarter_start=date(2026, 7, 5)) == (
        date(2026, 7, 5),
        date(2026, 9, 30),
    )


def test_source_link_sin_html_o_metrica_desconocida_no_ancla():
    sin_html = source_link(metric="revenue", period="2026-09-30:Q3", value=1, doc_url=DOC, html=None)
    assert sin_html["calc_type"] == "reported" and sin_html["anchor"] is None
    sin_concepto = source_link(
        metric="metrica_que_no_existe", period="2026-09-30:Q3", value=1, doc_url=DOC, html=HTML_BASE
    )
    assert sin_concepto["anchor"] is None


def test_source_link_periodo_invalido_no_ancla():
    link = source_link(metric="revenue", period="2026-13-99:FY", value=1, doc_url=DOC, html=HTML_BASE)
    assert link["anchor"] is None


def test_source_link_valor_distinto_no_ancla():
    html = (
        HTML_BASE
        + """
<td><ix:nonFraction unitRef="usd" contextRef="c-1" name="us-gaap:Revenues" id="f-q"
 format="ixt:num-dot-decimal">1000</ix:nonFraction></td>
"""
    )
    link = source_link(metric="revenue", period="2026-09-30:Q3", value=999999, doc_url=DOC, html=html)
    assert link["anchor"] is None


def test_source_link_fallback_52_semanas():
    link = source_link(metric="revenue", period="2026-06-27:FY", value=1000, doc_url=DOC, html=HTML_52W)
    assert link["anchor"] == "f-52"
    assert link["concept"] == "us-gaap:Revenues"
    assert link["url"] == DOC + "#f-52"


def test_source_link_fallback_fuera_de_tolerancia_no_ancla():
    # 354 días no entra en la ventana de 52-53 semanas (365 ± 10).
    link = source_link(metric="revenue", period="2026-06-27:FY", value=1000, doc_url=DOC, html=HTML_52W_FUERA)
    assert link["anchor"] is None


def test_source_link_fallback_52_semanas_sin_duracion_valida():
    link = source_link(metric="revenue", period="2026-06-27:FY", value=1000, doc_url=DOC, html=HTML_BASE)
    assert link["anchor"] is None
