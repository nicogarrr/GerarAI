"""Quita del SARIF los hallazgos suprimidos en fuente (nosemgrep) antes del upload.

GitHub code scanning ignora la propiedad SARIF `suppressions`
(github/codeql-action#1230), asi que un hallazgo con nosemgrep reapareceria
como alerta nueva a cada analisis. Semgrep lo etiqueta con
`suppressions: [{kind: inSource}]` y aqui se elimina del upload: el nosemgrep
motivado queda en el codigo y code scanning solo ve hallazgos activos.

Solo se elimina un result cuando tiene AL MENOS una supresion con
kind == "inSource" y status "accepted" o ausente (ausente = aceptada por
defecto en SARIF). Se conservan: suppressions ausente, suppressions: []
(array vacio NO es supresion), kind "external", y status "rejected" o
"underReview" (alguien reviso la supresion y no la acepto: el hallazgo esta
activo y debe verse).

Uso: python scripts/filter_sarif_suppressions.py SARIF [SALIDA]
Sin SALIDA, reescribe el fichero in situ.
"""

from __future__ import annotations

import json
import sys


def _suppressed_in_source(result: dict) -> bool:
    for suppression in result.get("suppressions") or []:
        if suppression.get("kind") == "inSource" and suppression.get("status", "accepted") == "accepted":
            return True
    return False


def filter_sarif(sarif: dict) -> tuple[dict, int]:
    """Devuelve (sarif filtrado, numero de results eliminados)."""
    removed = 0
    for run in sarif.get("runs") or []:
        results = run.get("results")
        if not results:
            continue
        kept = [r for r in results if not _suppressed_in_source(r)]
        removed += len(results) - len(kept)
        run["results"] = kept
    return sarif, removed


def main(argv: list[str]) -> int:
    if len(argv) not in (2, 3):
        print(__doc__, file=sys.stderr)
        return 2
    src_path = argv[1]
    dst_path = argv[2] if len(argv) == 3 else src_path
    with open(src_path, encoding="utf-8") as fh:
        sarif = json.load(fh)
    sarif, removed = filter_sarif(sarif)
    with open(dst_path, "w", encoding="utf-8") as fh:
        json.dump(sarif, fh, indent=2)
        fh.write("\n")
    print(f"hallazgos suprimidos eliminados del SARIF: {removed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
