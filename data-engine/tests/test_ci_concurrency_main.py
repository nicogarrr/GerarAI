"""Concurrencia de CI en `main`: como mucho un run en curso y uno pendiente.

27-oct-2026: con un merge por minuto, el grupo por SHA lanzaba un run completo de
CI por cada commit de `main` y ninguno se descartaba. A las 11:20 había 14 runs de
`main` en cola desde las 10:18 y los checks de las PRs esperaban detrás, así que
`main` no podía «estar en verde» y la cola de merges se paraba.

Con el grupo por ref y `cancel-in-progress: false`, GitHub deja terminar el run en
curso y sustituye el pendiente por el del commit más nuevo: nunca se mata un run a
medias (la razón original del grupo por SHA) y el último commit de `main` siempre
llega a tener su run completo.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

CI = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "ci.yml"


def _concurrency() -> dict[str, Any]:
    data = yaml.safe_load(CI.read_text(encoding="utf-8"))
    return data["concurrency"]


def test_el_grupo_de_main_es_por_ref_no_por_commit():
    group = str(_concurrency()["group"])
    assert "github.sha" not in group, (
        "agrupar main por SHA acumula un run completo por cada merge (cola de CI atascada)"
    )
    assert "github.ref" in group
    assert "github.workflow" in group


def test_no_se_cancela_un_run_de_main_a_medias():
    # Solo las PRs cancelan el run viejo; en main el run en curso termina siempre
    # y solo se descarta el que aún estaba pendiente.
    assert _concurrency()["cancel-in-progress"] == "${{ github.event_name == 'pull_request' }}"


WORKFLOWS = CI.parent


def _pushes_to_main(data: dict[str, Any]) -> bool:
    on = data.get("on", data.get(True))  # PyYAML lee `on:` como True
    if isinstance(on, dict) and "push" in on:
        push = on["push"] or {}
        branches = push.get("branches") if isinstance(push, dict) else None
        return branches is None or "main" in branches
    return isinstance(on, (list, str)) and "push" in on


def test_ningun_workflow_de_main_cancela_un_run_en_curso():
    """27-oct-2026: en la rafaga de merges ningun run de main llegaba a terminar.

    Un workflow que corre en push a main con `cancel-in-progress: true` mata el
    run en curso con cada merge nuevo y el commit se queda sin resultado
    (gitleaks e ingest-evals lo hacian). En main solo puede descartarse el run
    PENDIENTE; el que esta corriendo termina siempre.
    """
    offenders = []
    for path in sorted(WORKFLOWS.glob("*.yml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        conc = data.get("concurrency")
        if not isinstance(conc, dict) or not _pushes_to_main(data):
            continue
        cancel = conc.get("cancel-in-progress", False)
        if cancel is True or (isinstance(cancel, str) and "pull_request" not in cancel):
            offenders.append(f"{path.name}: cancel-in-progress={cancel!r}")
    assert not offenders, offenders
