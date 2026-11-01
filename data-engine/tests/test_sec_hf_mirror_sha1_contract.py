"""Contrato de proveniencia del mirror HF: sha1 verifica que cada fichero
servido casa con el digest declarado en el manifest del dataset ya publicado
(detecta subidas parciales o corrupcion). Todo uso lleva
``usedforsecurity=False`` explicito: no es frontera criptografica, porque el
manifest lo publica el mismo operador que sirve el contenido.

Migrar el contrato a otro digest (p.ej. sha256) exige actualizar escritor
(sec_hf_mirror_sync.py), lector (sec_edgar.py) y este test a la vez, y
republicar el dataset: queda abierto como mejora futura.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WRITER = ROOT / "data-engine" / "scripts" / "sec_hf_mirror_sync.py"
READER = ROOT / "data-engine" / "app" / "services" / "connectors" / "sec_edgar.py"


def _sha1_calls(path: Path) -> list[str]:
    return re.findall(r"hashlib\.sha1\([^)]*\)", path.read_text(encoding="utf-8"))


def test_every_sha1_call_is_marked_not_for_security():
    for path in (WRITER, READER):
        calls = _sha1_calls(path)
        assert calls, f"{path.name}: el contrato sha1 del mirror ha desaparecido"
        for call in calls:
            assert "usedforsecurity=False" in call, f"{path.name}: {call} sin usedforsecurity=False"


def test_no_plain_hashlib_sha1_without_marker_in_mirror_contract():
    for path in (WRITER, READER):
        bare = [c for c in _sha1_calls(path) if "usedforsecurity=False" not in c]
        assert bare == []
