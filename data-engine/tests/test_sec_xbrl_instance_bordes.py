"""Bordes de connectors/sec_xbrl_instance.py: guards del parser de instancias.

Parser puro y sincrono: los tests alimentan bytes XML sinteticos por
io.BytesIO, sin red, sin DB, sin reloj, sin estado global. Aserciones por
igualdad estricta (dataclass frozen DimensionedFact compara por campos).

Vias directas declaradas (el auditor pide acotacion):
- 83 (_unit_allowed con tag sin restriccion): desde la via publica NUNCA se
  alcanza, porque solo se parsean tags de _ALL_TAGS y _ALL_TAGS es subconjunto
  de ALLOWED_UNITS. Se cubre llamando al helper directamente.
- 151-154 (eje como elemento <dimension> hijo): se cubre con un contexto
  ET.fromstring directo; la forma con atributo dimension ya la cubre la union
  por la via publica.

Sin lineas declaradas inalcanzables en este lote.
"""

from __future__ import annotations

import io
import xml.etree.ElementTree as ET
from datetime import date
from decimal import Decimal

from app.services.connectors.sec_xbrl_instance import (
    DimensionedFact,
    _member_pairs,
    _unit_allowed,
    parse_instance_dimensioned_ecso,
    parse_instance_dimensioned_facts,
)

# Instancia sintetica con: unidad EPS con un elemento ajeno dentro del divide
# (215->212), contexto anual con miembro, contexto instantaneo (231),
# contexto con fechas rotas (startDate vacia -> 126, endDate no ISO ->
# 129-130), un hecho no numerico (238-240) y un scale no entero (251-253).
XML = b"""<xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance"
 xmlns:iso4217="http://www.xbrl.org/2003/iso4217"
 xmlns:xbrldi="http://xbrl.org/2006/xbrldi"
 xmlns:us-gaap="http://fasb.org/us-gaap/2024"
 xmlns:dei="http://xbrl.sec.gov/dei/2024">
 <xbrli:unit id="u_shares"><xbrli:measure>xbrli:shares</xbrli:measure></xbrli:unit>
 <xbrli:unit id="u_eps"><xbrli:divide>
  <xbrli:unitNumerator><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unitNumerator>
  <xbrli:separador/>
  <xbrli:unitDenominator><xbrli:measure>xbrli:shares</xbrli:measure></xbrli:unitDenominator>
 </xbrli:divide></xbrli:unit>
 <xbrli:context id="c_dur"><xbrli:entity><xbrli:identifier scheme="x">0001</xbrli:identifier><xbrli:segment><xbrldi:explicitMember dimension="us-gaap:StatementClassOfStockAxis">us-gaap:ClassAMember</xbrldi:explicitMember></xbrli:segment></xbrli:entity><xbrli:period><xbrli:startDate>2025-01-01</xbrli:startDate><xbrli:endDate>2025-12-31</xbrli:endDate></xbrli:period></xbrli:context>
 <xbrli:context id="c_inst"><xbrli:entity><xbrli:identifier scheme="x">0001</xbrli:identifier><xbrli:segment><xbrldi:explicitMember dimension="us-gaap:StatementClassOfStockAxis">us-gaap:CommonStockMember</xbrldi:explicitMember></xbrli:segment></xbrli:entity><xbrli:period><xbrli:instant>2026-01-15</xbrli:instant></xbrli:period></xbrli:context>
 <xbrli:context id="c_bad"><xbrli:entity><xbrli:identifier scheme="x">0001</xbrli:identifier><xbrli:segment><xbrldi:explicitMember dimension="us-gaap:StatementClassOfStockAxis">us-gaap:ClassAMember</xbrldi:explicitMember></xbrli:segment></xbrli:entity><xbrli:period><xbrli:startDate></xbrli:startDate><xbrli:endDate>31/12/2025</xbrli:endDate></xbrli:period></xbrli:context>
 <us-gaap:EarningsPerShareDiluted contextRef="c_dur" unitRef="u_eps">1.23</us-gaap:EarningsPerShareDiluted>
 <us-gaap:EarningsPerShareDiluted contextRef="c_dur" unitRef="u_eps">N/A</us-gaap:EarningsPerShareDiluted>
 <us-gaap:EarningsPerShareDiluted contextRef="c_dur" unitRef="u_eps" scale="abc">1.0</us-gaap:EarningsPerShareDiluted>
 <dei:EntityCommonStockSharesOutstanding contextRef="c_inst" unitRef="u_shares">100</dei:EntityCommonStockSharesOutstanding>
 <us-gaap:WeightedAverageNumberOfDilutedSharesOutstanding contextRef="c_bad" unitRef="u_shares">50</us-gaap:WeightedAverageNumberOfDilutedSharesOutstanding>
</xbrl>"""

EPS_FACT = DimensionedFact(
    tag="EarningsPerShareDiluted",
    value=Decimal("1.23"),
    start=date(2025, 1, 1),
    end=date(2025, 12, 31),
    instant=None,
    members=(("us-gaap:StatementClassOfStockAxis", "ClassAMember"),),
)

ECSO_FACT = DimensionedFact(
    tag="EntityCommonStockSharesOutstanding",
    value=Decimal("100"),
    start=None,
    end=None,
    instant=date(2026, 1, 15),
    members=(("us-gaap:StatementClassOfStockAxis", "CommonStockMember"),),
)


def test_unit_allowed_tag_sin_restriccion_devuelve_true():
    """83: tag fuera de ALLOWED_UNITS -> True (fail open sintetico).

    Inalcanzable desde parse_instance_dimensioned_facts (todo tag parseado
    esta en _ALL_TAGS, subconjunto de ALLOWED_UNITS): via directa.
    """
    assert _unit_allowed("TagSinRestriccion", "u_inventada", {}) is True


def test_member_pairs_eje_como_elemento_hijo_o_ausente():
    """151-154: explicitMember sin atributo dimension: eje del elemento hijo
    <dimension> o cadena vacia si tampoco existe."""
    contexto = ET.fromstring(
        '<context xmlns:xbrldi="http://xbrl.org/2006/xbrldi">'
        "<xbrldi:explicitMember>us-gaap:ClassAMember"
        "<xbrldi:dimension>us-gaap:StatementClassOfStockAxis</xbrldi:dimension>"
        "</xbrldi:explicitMember>"
        "<xbrldi:explicitMember>us-gaap:ClassBMember</xbrldi:explicitMember>"
        "</context>"
    )
    assert _member_pairs(contexto) == (
        ("us-gaap:StatementClassOfStockAxis", "ClassAMember"),
        ("", "ClassBMember"),
    )


def test_parse_instancia_descarta_valores_y_fechas_rotas():
    """238-240 (valor no numerico), 251-253 (scale no entero), 126 (startDate
    vacia), 129-130 (endDate no ISO), 231 (contexto instant), 116
    (duration_days None en el filtro), 215->212 (elemento ajeno en divide).

    Sobrevive solo el EPS anual valido, por igualdad estricta de campos.
    """
    facts = parse_instance_dimensioned_facts(io.BytesIO(XML))
    assert facts == [EPS_FACT]
    # El hecho de fechas rotas se descarta por duracion None, no por error.
    assert EPS_FACT.duration_days == 364


def test_parse_instancia_ecso_devuelve_solo_ecso_con_instante():
    """271->279 (filtro de duracion omitido con min/max None) y 291: el carril
    ECSO devuelve solo hechos dei:ECSO dimensionados con instante."""
    facts = parse_instance_dimensioned_ecso(io.BytesIO(XML))
    assert facts == [ECSO_FACT]
    assert ECSO_FACT.duration_days is None
