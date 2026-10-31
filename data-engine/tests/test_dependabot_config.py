"""Guardian de .github/dependabot.yml (regla registry dependabot-missing-cooldown).

Cada ecosistema con updates automaticos lleva `cooldown`: una release nueva
"hierve" unos dias antes de la PR, para que un paquete comprometido no entre
al dia cero. Las actualizaciones de seguridad no esperan. Si se quita el
cooldown, el job semgrep-registry vuelve a abrir la alerta.
"""

from __future__ import annotations

import re
from pathlib import Path

# El test vive en data-engine/tests/, asi que la raiz del repo es parents[2].
DEPENDABOT_YML = Path(__file__).resolve().parents[2] / ".github" / "dependabot.yml"


def _update_blocks() -> list[str]:
    text = DEPENDABOT_YML.read_text(encoding="utf-8")
    return re.split(r"\n  - package-ecosystem: ", text)[1:]


def test_every_ecosystem_has_cooldown():
    blocks = _update_blocks()
    assert len(blocks) >= 3, "se esperaban al menos npm, uv y github-actions"
    missing = [
        block.splitlines()[0].strip()
        for block in blocks
        if not re.search(r"^\s{4}cooldown:\s*$", block, re.M)
    ]
    assert missing == [], f"ecosistemas sin cooldown en dependabot.yml: {missing}"


def test_cooldown_has_positive_default_days():
    for block in _update_blocks():
        m = re.search(r"default-days:\s*(\d+)", block)
        assert m and int(m.group(1)) >= 1, "cooldown.default-days debe ser >= 1"
