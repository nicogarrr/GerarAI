"""El memo (Python) y el panel (TS) traducen los drivers del marco igual."""

import re
from pathlib import Path

import pytest

from app.services.company_framework import FRAMEWORKS
from app.services.framework_terms_es import FRAMEWORK_TERMS_ES, framework_term_es
from app.services.memo_text_es import term_es

TS_MAP = Path(__file__).resolve().parents[2] / "lib" / "research" / "framework-terms.ts"


def _ts_terms() -> dict[str, str]:
    src = TS_MAP.read_text(encoding="utf-8")
    body = src[src.index("FRAMEWORK_TERMS") :]
    body = body[body.index("{") + 1 : body.index("\n};")]
    pairs = re.findall(r"(?:'([^']+)'|([A-Za-z_&][\w&]*))\s*:\s*'((?:[^'\\]|\\.)*)'", body)
    return {(a or b): v.replace("\\'", "'") for a, b, v in pairs}


@pytest.mark.skipif(not TS_MAP.exists(), reason="sin el front en este checkout")
def test_mapa_python_igual_al_de_la_ui():
    assert _ts_terms() == FRAMEWORK_TERMS_ES


def test_drivers_de_los_marcos_tienen_etiqueta_es():
    sin_etiqueta = {
        key
        for framework in FRAMEWORKS.values()
        for key in (*framework.revenue_drivers, *framework.required_fact_metrics)
        if framework_term_es(key) is None
        and term_es(key) == key.replace("_", " ")
        and not re.search(r"[×÷]", key)
    }
    assert sin_etiqueta == set()
