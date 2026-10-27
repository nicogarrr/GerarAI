"""Parser iXBRL de paquetes ESEF del emisor (carril IE: filings.xbrl.org no
indexa Irlanda) y build de snapshots desde paquetes reviewed."""

import asyncio
import io
import sys
import zipfile
from pathlib import Path

from app.services.connectors.esef_ixbrl import parse_entity_name, parse_ixbrl_facts

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from build_esef_snapshots import build_package_payloads  # noqa: E402

DOC = """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"
      xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"
      xmlns:xbrli="http://www.xbrl.org/2003/instance"
      xmlns:xbrldi="http://xbrl.org/2006/xbrldi"
      xmlns:iso4217="http://www.xbrl.org/2003/iso4217"
      xmlns:ifrs-full="https://xbrl.ifrs.org/taxonomy/2024-03-27/ifrs-full"
      xmlns:ixt4="http://www.xbrl.org/inlineXBRL/transformation/2020-02-12">
<head/><body>
<ix:header><ix:resources>
<xbrli:context id="c-1"><xbrli:entity><xbrli:identifier scheme="http://standards.iso.org/iso/17442">LEITEST00000000000001</xbrli:identifier></xbrli:entity>
<xbrli:period><xbrli:startDate>2025-01-01</xbrli:startDate><xbrli:endDate>2025-12-31</xbrli:endDate></xbrli:period></xbrli:context>
<xbrli:context id="c-2"><xbrli:entity><xbrli:identifier scheme="http://standards.iso.org/iso/17442">LEITEST00000000000001</xbrli:identifier>
<xbrli:segment><xbrldi:explicitMember dimension="ifrs-full:SegmentsAxis">x:MemberA</xbrldi:explicitMember></xbrli:segment></xbrli:entity>
<xbrli:period><xbrli:startDate>2025-01-01</xbrli:startDate><xbrli:endDate>2025-12-31</xbrli:endDate></xbrli:period></xbrli:context>
<xbrli:context id="c-3"><xbrli:entity><xbrli:identifier scheme="http://standards.iso.org/iso/17442">LEITEST00000000000001</xbrli:identifier></xbrli:entity>
<xbrli:period><xbrli:instant>2025-12-31</xbrli:instant></xbrli:period></xbrli:context>
<xbrli:unit id="u-1"><xbrli:measure>iso4217:EUR</xbrli:measure></xbrli:unit>
<xbrli:unit id="u-2"><xbrli:divide><xbrli:unitNumerator><xbrli:measure>iso4217:EUR</xbrli:measure></xbrli:unitNumerator><xbrli:unitDenominator><xbrli:measure>xbrli:shares</xbrli:measure></xbrli:unitDenominator></xbrli:divide></xbrli:unit>
</ix:resources></ix:header>
<p><ix:nonFraction name="ifrs-full:Revenue" format="ixt4:num-dot-decimal" contextRef="c-1" unitRef="u-1" decimals="-5" scale="6">6,757.6</ix:nonFraction></p>
<p><ix:nonFraction name="ifrs-full:Revenue" format="ixt4:num-dot-decimal" contextRef="c-2" unitRef="u-1" decimals="-5" scale="6">1,000.0</ix:nonFraction></p>
<p><ix:nonFraction name="ifrs-full:FinanceCosts" format="ixt4:num-dot-decimal" sign="-" contextRef="c-1" unitRef="u-1" decimals="0" scale="3">12.5</ix:nonFraction></p>
<p><ix:nonFraction name="ifrs-full:BasicEarningsLossPerShare" format="ixt4:num-dot-decimal" contextRef="c-1" unitRef="u-2" decimals="3">4.002</ix:nonFraction></p>
<p><ix:nonFraction name="ifrs-full:Assets" format="ixt4:num-dot-decimal" contextRef="c-3" unitRef="u-1" decimals="-6" scale="6">10,669</ix:nonFraction></p>
<p><ix:nonFraction name="ifrs-full:DividendsPaid" format="ixt4:fixed-zero" contextRef="c-1" unitRef="u-1" decimals="0">-</ix:nonFraction></p>
<p><ix:nonFraction name="ifrs-full:ProfitLoss" contextRef="c-1" unitRef="u-1" decimals="0">no-es-un-numero</ix:nonFraction></p>
<ix:hidden><ix:nonFraction name="ifrs-full:Equity" format="ixt4:num-dot-decimal" contextRef="c-3" unitRef="u-1" decimals="-6" scale="6">5,952</ix:nonFraction></ix:hidden>
<p><ix:nonNumeric name="ifrs-full:NameOfReportingEntityOrOtherMeansOfIdentification" contextRef="c-1" continuationRef="k1">Kerry Group</ix:nonNumeric></p>
<ix:continuation id="k1"> plc</ix:continuation>
</body></html>
"""


def test_parse_facts_same_layout_as_xbrl_json():
    out = parse_ixbrl_facts(io.BytesIO(DOC.encode()))
    facts = out["facts"]
    assert out["entity_lei"] == "LEITEST00000000000001"

    rev = facts["ifrs-full:Revenue"]["iso4217:EUR"]
    consolidated = [e for e in rev if not e["dims"]]
    assert len(consolidated) == 1
    assert consolidated[0]["val"] == "6757600000.0"  # 6,757.6 con scale=6
    assert consolidated[0]["start"] == "2025-01-01"
    assert consolidated[0]["end"] == "2025-12-31"
    assert consolidated[0]["decimals"] == "-5"
    assert consolidated[0]["lei"] == "LEITEST00000000000001"
    member = [e for e in rev if e["dims"]]
    assert member[0]["dims"] == ["ifrs-full:SegmentsAxis"]  # nunca se mezcla

    # sign="-" niega tras la transformacion
    cost = facts["ifrs-full:FinanceCosts"]["iso4217:EUR"][0]
    assert cost["val"] == "-12500.0"

    # unidad divide -> "iso4217:EUR/xbrli:shares" (convenio filings.xbrl.org)
    eps = facts["ifrs-full:BasicEarningsLossPerShare"]
    assert list(eps) == ["iso4217:EUR/xbrli:shares"]
    assert eps["iso4217:EUR/xbrli:shares"][0]["val"] == "4.002"

    # instante (balance)
    assets = facts["ifrs-full:Assets"]["iso4217:EUR"][0]
    assert assets["instant"] == "2025-12-31" and "start" not in assets

    # fixed-zero -> 0 declarado
    assert facts["ifrs-full:DividendsPaid"]["iso4217:EUR"][0]["val"] == "0"

    # valor ilegible: descartado y contado, nunca inventado
    assert "ifrs-full:ProfitLoss" not in facts
    assert out["dropped"] == 1

    # hechos de la seccion oculta tambien son hechos declarados
    assert facts["ifrs-full:Equity"]["iso4217:EUR"][0]["val"] == "5952000000"


def test_parse_entity_name_follows_continuations():
    assert parse_entity_name(io.BytesIO(DOC.encode())) == "Kerry Group plc"


def _zip_with_xhtml(xhtml: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("pkg/reports/report.xhtml", xhtml)
    return buf.getvalue()


def test_build_package_payloads_lei_mismatch_discards(monkeypatch):
    """Un paquete cuyo LEI declarado no es el reviewed se descarta entero:
    nunca se asigna a ojo."""
    import app.services.esef_package_sources as sources

    doc_wrong_lei = DOC.replace("LEITEST00000000000001", "OTROLEI0000000000000")
    monkeypatch.setattr(
        sources, "REVIEWED_PACKAGES",
        (sources.EsefPackageSource("635400TLVVBNXLFHWC59", "2025-12-31", "https://x/y.zip"),),
    )
    import build_esef_snapshots as builder
    monkeypatch.setattr(builder, "REVIEWED_PACKAGES", sources.REVIEWED_PACKAGES)

    async def fake_fetch(url):
        return _zip_with_xhtml(doc_wrong_lei)

    payloads = asyncio.run(build_package_payloads("2026-10-19", fetch=fake_fetch))
    assert payloads == {}


def test_build_package_payloads_happy_path(monkeypatch):
    import build_esef_snapshots as builder

    import app.services.esef_package_sources as sources

    pkgs = (
        sources.EsefPackageSource("635400TLVVBNXLFHWC59", "2025-12-31", "https://x/2025.zip"),
        sources.EsefPackageSource("635400TLVVBNXLFHWC59", "2024-12-31", "https://x/2024.zip"),
    )
    monkeypatch.setattr(builder, "REVIEWED_PACKAGES", pkgs)
    monkeypatch.setattr(sources, "REVIEWED_PACKAGES", pkgs)
    doc = DOC.replace("LEITEST00000000000001", "635400TLVVBNXLFHWC59")

    async def fake_fetch(url):
        return _zip_with_xhtml(doc.replace("2025-12-31", "2024-12-31")
                                  .replace("2025-01-01", "2024-01-01")
                               if "2024" in url else doc)

    payloads = asyncio.run(build_package_payloads("2026-10-19", fetch=fake_fetch))
    p = payloads["635400TLVVBNXLFHWC59"]
    assert p["ticker"] == "KRYAY"
    assert p["entity_name"] == "Kerry Group Public Limited Company"
    assert p["period_end"] == "2025-12-31"
    assert p["periods"] == ["2025-12-31", "2024-12-31"]
    assert len(p["sha256"]) == 64  # sha256 real del zip
    assert p["package_urls"]["2024-12-31"] == "https://x/2024.zip"
    rev = p["facts"]["ifrs-full:Revenue"]["iso4217:EUR"]
    assert {e["end"] for e in rev if not e["dims"]} == {"2025-12-31"}
    assert len(p["presentation_archive"]) == 2
    assert p["requires_presentation_review"] is True
    assert p["coverage"]["older_only_fact_keys_excluded"] > 0


def test_package_presentations_keep_represented_and_original_scopes(monkeypatch):
    import build_esef_snapshots as builder

    from app.services.esef_package_sources import EsefPackageSource

    lei = '635400TLVVBNXLFHWC59'
    # Deliberately unsorted input; synthetic values with real Kerry perimeter
    # example. These are not a substitute for issuer filings or live DB checks.
    monkeypatch.setattr(builder, 'REVIEWED_PACKAGES', (
        EsefPackageSource(lei, '2024-12-31', 'https://fixture/2024.zip'),
        EsefPackageSource(lei, '2023-12-31', 'https://fixture/2023.zip'),
    ))
    original = DOC.replace('LEITEST00000000000001', lei).replace('2025', '2023').replace('6,757.6', '8,020.3')
    latest = original.replace('8,020.3', '6,974.9')
    # A concept only in the older report must remain in archive, not be silently
    # promoted into the selected presentation as if scope were comparable.
    latest = latest.replace('ifrs-full:Equity', 'ifrs-full:OtherEquity')

    async def fetch(url):
        return _zip_with_xhtml(original if '2023' in url else latest)

    p = asyncio.run(builder.build_package_payloads('2026-10-27', fetch=fetch))[lei]
    rev = lambda facts: next(e['val'] for e in facts['ifrs-full:Revenue']['iso4217:EUR'] if not e['dims'])
    assert rev(p['facts']) == '6974900000.0'
    assert [rev(a['facts']) for a in p['presentation_archive']] == ['8020300000.0', '6974900000.0']
    assert 'ifrs-full:Equity' not in p['facts']
    assert 'ifrs-full:Equity' in p['presentation_archive'][0]['facts']
    assert p['selected_presentation']['source_url'] == 'https://fixture/2024.zip'
    assert all(len(a['sha256']) == 64 for a in p['presentation_archive'])
    assert p['coverage']['comparability'] == 'not_asserted_across_presentations'
    assert p['coverage']['older_only_fact_keys_excluded'] == 1
    assert p['requires_presentation_review'] is True


def test_partial_package_build_cannot_reenable_history_replacement(monkeypatch):
    import build_esef_snapshots as builder

    from app.services.esef_package_sources import EsefPackageSource

    lei = '635400TLVVBNXLFHWC59'
    monkeypatch.setattr(builder, 'REVIEWED_PACKAGES', (
        EsefPackageSource(lei, '2023-12-31', 'https://fixture/2023.zip'),
        EsefPackageSource(lei, '2024-12-31', 'https://fixture/2024.zip'),
    ))
    valid = DOC.replace('LEITEST00000000000001', lei)
    for rejected_old in ('missing_report', 'wrong_lei'):
        async def fetch(url):
            if '2024' in url:
                return _zip_with_xhtml(valid)
            if rejected_old == 'wrong_lei':
                return _zip_with_xhtml(DOC.replace('LEITEST00000000000001', 'WRONGLEI'))
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, 'w') as zf:
                zf.writestr('pkg/readme.txt', 'no report')
            return buf.getvalue()

        p = asyncio.run(builder.build_package_payloads('2026-10-27', fetch=fetch))[lei]
        assert len(p['presentation_archive']) == 1
        assert p['requires_presentation_review'] is True


def test_typed_dimensions_never_look_consolidated():
    # Synthetic fixture, not evidence of affected live issuer data.
    from lxml import etree

    for axis in (' dimension="ifrs-full:BusinessAxis"', ''):
        for container in ('segment', 'scenario'):
            xml = DOC.replace(
                '<xbrli:segment><xbrldi:explicitMember dimension="ifrs-full:SegmentsAxis">x:MemberA</xbrldi:explicitMember></xbrli:segment>',
                f'<xbrli:{container}><xbrldi:typedMember{axis}>'
                '<ifrs-full:Business>Example segment</ifrs-full:Business>'
                f'</xbrldi:typedMember></xbrli:{container}>',
            )
            # scenario is valid outside entity; scope parsing must work there.
            if container == 'scenario':
                root = etree.fromstring(xml.encode())
                ns = '{http://www.xbrl.org/2003/instance}'
                ctx = root.find('.//' + ns + 'context[@id="c-2"]')
                scenario = ctx.find('.//' + ns + 'scenario')
                scenario.getparent().remove(scenario)
                ctx.append(scenario)
                xml = etree.tostring(root).decode()
            parsed = parse_ixbrl_facts(io.BytesIO(xml.encode()))
            revenue = parsed['facts']['ifrs-full:Revenue']['iso4217:EUR']
            assert [e['val'] for e in revenue if not e['dims']] == ['6757600000.0']
            typed = next(e for e in revenue if e['val'] == '1000000000.0')
            assert typed['dims'] == [
                'ifrs-full:BusinessAxis' if axis else '__unknown_dimension__'
            ]
            assert parsed['dropped'] == 1  # unchanged invalid numeric fixture
