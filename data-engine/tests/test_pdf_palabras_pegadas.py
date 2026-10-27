"""Un PDF sin espacios reales (MarkItDown pega las palabras) va al carril pypdf."""

from app.services import docling_pipeline as dp
from app.services.document_ingestion_service import ParsedBlock

GLUED = ("Bewaretheinvestmentactivitythatproducesapplause; thegreatmovesareusuallygreetedbyyawns. " * 30) + (
    "The rest of the letter reads fine and has normal words. " * 20
)
NORMAL = (
    "Beware the investment activity that produces applause; the great moves are usually greeted by yawns. "
    * 40
)


def test_ratio_de_palabras_pegadas():
    assert dp.glued_words_ratio(GLUED) > 0.02
    assert dp.glued_words_ratio(NORMAL) == 0.0
    # Texto corto: sin senal suficiente, no se descarta.
    assert dp.glued_words_ratio("Supercalifragilisticexpialidocious") == 0.0


def test_markitdown_pegado_cae_a_pypdf(monkeypatch):
    monkeypatch.setattr(dp, "convert_fast_markitdown", lambda *a, **k: GLUED)
    good = ParsedBlock(text=NORMAL, metadata={"page": 1})
    monkeypatch.setattr(dp, "_pypdf_fallback_blocks", lambda content: ([good], NORMAL))
    monkeypatch.setattr(dp, "resolve_allow_heavy", lambda *a, **k: False)
    parsed = dp.parse_pdf_two_lane(b"%PDF-1.4 fake", "brk2008.pdf")
    text = " ".join(block.text for block in parsed.blocks)
    assert "investment activity" in text
    assert "Bewaretheinvestment" not in text
    assert any("pego palabras" in w for w in parsed.warnings)


def test_markitdown_normal_se_mantiene(monkeypatch):
    monkeypatch.setattr(dp, "convert_fast_markitdown", lambda *a, **k: NORMAL)
    monkeypatch.setattr(dp, "resolve_allow_heavy", lambda *a, **k: False)
    parsed = dp.parse_pdf_two_lane(b"%PDF-1.4 fake", "ok.pdf")
    assert parsed.blocks
    assert not any("pego palabras" in w for w in parsed.warnings)
