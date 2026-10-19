"""0073: patrón de titular genérico y garantías de la expresión SQL.

Sin Postgres local en este entorno no se ejecuta el UPDATE; se valida el
patrón contra los casos reales y la estructura de la sentencia (los tres
puntos de la objeción del auditor, 19-oct-2026).
"""

import re
from pathlib import Path

SQL = (Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0073_news_generic_titles.py").read_text(encoding="utf-8")
_PAT = r"se\s+abre\s+en\s+una\s+nueva\s+ventana|opens?\s+in\s+a\s+new\s+window"


def test_pattern_matches_only_viewer_link_text():
    pat = re.compile(_PAT, re.IGNORECASE)
    # Caso real de prod (ZETA): texto de enlace del visor de la SEC.
    assert pat.search("Comunicado de prensa del Q2 2026, archivo PDF, (se abre en una nueva ventana)")
    assert pat.search("Q2 2026 Press Release, PDF file (opens in a new window)")
    # Titulares reales con «PDF» o «archivo» no casan (objeción del auditor).
    assert not pat.search("Zeta Global reports Q2 2026 results")
    assert not pat.search("Apple publica el PDF de su memoria anual 2026")
    assert not pat.search("Company files annual report PDF with the SEC")


def test_migration_uses_the_same_tight_pattern():
    assert f'_PAT = r"{_PAT}"' in SQL
    assert "archivo" not in _PAT


def test_upgrade_sql_keeps_short_summaries_whole():
    """Objeción 1: el corte en palabra solo aplica cuando el resumen supera
    180 caracteres; un resumen corto se conserva entero."""
    assert "WHEN length(btrim(summary)) <= 180" in SQL
    assert "THEN btrim(summary)" in SQL
    assert "WHEN btrim(summary) = ''" in SQL, "resumen vacío mantiene el título actual"
    assert "regexp_replace(left(btrim(summary), 180)" in SQL


def test_upgrade_sql_preserves_rehydrate_marker_and_overwritten_values():
    """Objeciones 2 y 3: title_before_headline_rehydrate se conserva (el
    downgrade de 0071 lo necesita) y los valores sobrescritos quedan
    preservados con downgrade propio."""
    assert "- 'title_before_headline_rehydrate'" not in SQL
    assert "title_before_generic_headline_fix" in SQL
    assert "generic_source_headline_removed" in SQL
