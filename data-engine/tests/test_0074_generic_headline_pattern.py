"""0074: «opens in new window» (sin «a») es el texto real de prod (SEC/ZETA, 19-oct-2026)."""

import re
from pathlib import Path

from app.services.news_service import is_generic_headline

SQL = (Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0074_news_generic_titles_v2.py").read_text(encoding="utf-8")
_PAT = r"se\s+abre\s+en\s+una\s+nueva\s+ventana|opens?\s+in\s+(?:a\s+)?new\s+window"


def test_prod_title_without_article_is_generic():
    assert is_generic_headline("Press Release of Q2 2026, PDF file, (opens in new window)")
    assert is_generic_headline("Q2 2026 Press Release, PDF file (opens in a new window)")
    assert not is_generic_headline("Zeta Global reports Q2 2026 results")
    assert not is_generic_headline("Company files annual report PDF with the SEC")


def test_migration_pattern_matches_service_pattern_and_chain():
    assert f'_PAT = r"{_PAT}"' in SQL
    assert re.search(_PAT, "Press Release of Q2 2026, PDF file, (opens in new window)", re.IGNORECASE)
    assert len("0074_news_generic_titles_v2") <= 32
    assert 'down_revision = "0073_news_generic_titles"' in SQL
