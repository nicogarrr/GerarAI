"""Cuerpo HTML con provenance. Texto SINTETICO; los marcadores reales vienen del registro."""
from datetime import date

import pytest

from app.services.commitment_body_provenance import extract_body
from app.services.commitment_primary_pipeline import PrimarySourceError, RegisteredDocument
from app.services.transcript_source_registry import VerifiedAsset, get_entry

REAL = get_entry("RXRX").assets[0]
BODYTXT = " ".join(f"w{i}" for i in range(300))


def _doc(text: str, asset=REAL):
    return RegisteredDocument(asset=object(), url=asset.url, bytes_sha256="a" * 64, byte_size=1,
                              text=text, text_sha256="b" * 64, extractor="x", fetched_on=date(2026, 10, 22))


def _asset_doc(text, asset=REAL):
    return _doc(text, asset), asset


def _page(menu="MENU"):
    return f"{menu}\n{REAL.body_start}\nNajat: {BODYTXT}\n\n{REAL.body_end}\nGet In Touch footer"


def test_body_extracted_with_hash_independent_of_chrome():
    a, b = extract_body(*_asset_doc(_page("MENU A"))), extract_body(*_asset_doc(_page("OTRO MENU")))
    assert a.body_sha256 == b.body_sha256 and a.words >= 300  # menu cambia, cuerpo no
    assert a.text.startswith("Najat:") and "footer" not in a.text


def test_body_change_changes_body_hash():
    changed = _page().replace("w10 ", "w10X ")
    assert extract_body(*_asset_doc(changed)).body_sha256 != extract_body(*_asset_doc(_page())).body_sha256


def test_missing_or_ambiguous_markers_abstain():
    with pytest.raises(PrimarySourceError):
        extract_body(*_asset_doc("sin marcadores " + BODYTXT))
    with pytest.raises(PrimarySourceError):
        extract_body(*_asset_doc(_page() + "\n" + REAL.body_start))  # inicio duplicado
    with pytest.raises(PrimarySourceError):
        extract_body(*_asset_doc(_page().replace(REAL.body_end, "")))  # fin ausente


def test_asset_without_markers_has_no_body_and_markers_only_for_html():
    pdf = VerifiedAsset("https://x.invalid/a.pdf", "t", "Q1 2026")
    with pytest.raises(PrimarySourceError):
        extract_body(*_asset_doc(_page(), asset=pdf))
    with pytest.raises(ValueError):
        VerifiedAsset("https://x.invalid/a.pdf", "t", "Q1", body_start="a", body_end="b")
    with pytest.raises(ValueError):
        VerifiedAsset("https://x.invalid/a", "t", "Q1", format="html", body_start="a")


def test_qa_hints_are_informational():
    b = extract_body(*_asset_doc(_page().replace("Najat:", "Operator: hola\nNajat:")))
    assert "Operator:" in b.qa_hints
