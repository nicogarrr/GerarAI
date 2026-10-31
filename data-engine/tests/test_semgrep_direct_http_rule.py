"""Guardian de la regla bloqueante gerarai-direct-http-client (.semgrep/gerarai.yml).

La regla prohibe clientes HTTP directos (httpx/requests/urllib) en data-engine/app/
salvo lista blanca revisada: las URLs que vienen del usuario o de datos externos
deben pasar por app.services.public_fetch (anti-SSRF). Un conector nuevo con
httpx directo que no se anada a la lista rompe el job Semgrep del CI.

Invariantes (sin depender de semgrep en el entorno de tests):
1. La regla existe, es ERROR y su mensaje indica la via correcta (public_fetch).
2. Todo modulo con una llamada HTTP directa esta en la lista blanca.
3. La lista blanca no tiene entradas muertas (ficheros que ya no existen).
"""

from __future__ import annotations

import re
from pathlib import Path

# El test vive en data-engine/tests/, asi que la raiz del repo es parents[2].
ROOT = Path(__file__).resolve().parents[2]
RULES_PATH = ROOT / ".semgrep" / "gerarai.yml"

# Llamadas directas equivalentes a los pattern-either de la regla:
# httpx.$M(...), requests.$M(...), urllib.request.urlopen(...), urlopen(...)
_DIRECT_CALL_RE = re.compile(
    r"(?:httpx|requests)\.[A-Za-z_]\w*\s*\(|urllib\.request\.urlopen\s*\(|^\s*(?:await\s+)?urlopen\s*\(",
    re.M,
)


def _rule_block(rule_id: str) -> str:
    text = RULES_PATH.read_text(encoding="utf-8")
    start = text.index(f"- id: {rule_id}")
    nxt = text.find("\n- id: ", start)
    return text[start:] if nxt == -1 else text[start:nxt]


def _exclude_entries(block: str) -> list[str]:
    exclude_section = block.split("exclude:", 1)[1]
    entries = []
    for line in exclude_section.splitlines()[1:]:
        m = re.match(r"^\s{4}- (\S+)\s*$", line)
        if not m:
            break
        entries.append(m.group(1))
    return entries


def test_rule_is_blocking_and_message_points_to_public_fetch():
    block = _rule_block("gerarai-direct-http-client")
    assert "severity: ERROR" in block
    assert "public_fetch" in block


def test_every_direct_http_call_is_allowlisted():
    block = _rule_block("gerarai-direct-http-client")
    allowed = {e.lstrip("/") for e in _exclude_entries(block)}
    offenders = []
    for path in sorted((ROOT / "data-engine" / "app").rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        if rel in allowed:
            continue
        code_lines = [
            ln for ln in path.read_text(encoding="utf-8").splitlines() if not ln.strip().startswith("#")
        ]
        if _DIRECT_CALL_RE.search("\n".join(code_lines)):
            offenders.append(rel)
    assert offenders == [], (
        "Modulos con cliente HTTP directo fuera de la lista blanca de "
        ".semgrep/gerarai.yml: usa app.services.public_fetch o anade el "
        f"modulo a la lista con su motivo: {offenders}"
    )


def test_allowlist_has_no_dead_entries():
    block = _rule_block("gerarai-direct-http-client")
    dead = [e for e in _exclude_entries(block) if not (ROOT / e.lstrip("/")).exists()]
    assert dead == [], f"Entradas muertas en la lista blanca de gerarai-direct-http-client: {dead}"
