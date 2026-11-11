"""A coding note also referenced by holdings is not globally unique."""
from pathlib import Path
from xml.etree import ElementTree as ET

from app.services.connectors.form4 import parse_form4_xml


def test_shared_coding_and_holding_note_stays_unknown():
    fixture=Path('tests/fixtures/form4/meta_0000950103-26-016314.xml')
    root=ET.fromstring(fixture.read_bytes())
    holding=ET.SubElement(root.find('nonDerivativeTable'),'nonDerivativeHolding')
    title=ET.SubElement(holding,'securityTitle')
    ET.SubElement(title,'value').text='Class A Common Stock'
    ET.SubElement(title,'footnoteId',{'id':'F1'})
    assert parse_form4_xml(ET.tostring(root))['transactions'][0]['alignment_10b5_1'] is None
