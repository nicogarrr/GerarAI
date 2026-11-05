"""El memo (Python) y el panel (TS) traducen los drivers del marco igual."""

import json
import re
from pathlib import Path

import pytest

from app.services.company_framework import FRAMEWORKS
from app.services.framework_terms_es import FRAMEWORK_TERMS_ES, framework_term_es
from app.services.memo_text_es import term_es

TS_MAP = Path(__file__).resolve().parents[2] / "lib" / "research" / "framework-terms.ts"


def _ts_terms() -> dict[str, str]:
    src = TS_MAP.read_text(encoding="utf-8")
    body = src[src.index("export const FRAMEWORK_TERMS:") :]
    body = body[body.index("{") + 1 : body.index("\n};")]
    pairs = re.findall(r"(?:'([^']+)'|([A-Za-z_&][\w&]*))\s*:\s*'((?:[^'\\]|\\.)*)'", body)
    terms = {(a or b): v.replace("\\'", "'") for a, b, v in pairs}
    mapping = src.split("const FRAMEWORK_TERMS_I18N:", 1)[1].split("\n};", 1)[0]
    catalog = json.loads((TS_MAP.parents[1] / "i18n/messages/es/researchShared.json").read_text())
    for key, path in re.findall(r"(\w+): 'researchShared\.([^']+)'", mapping):
        if key == "unassigned":
            continue  # existing UI-only label, not a backend framework driver
        value = catalog
        for segment in path.split("."):
            value = value[segment]
        terms[key] = value
    return terms


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
