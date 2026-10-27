"""El entorno aislado del crossover RAGAS se puede instalar y ejecutar.

La version anterior de `evals/rag/requirements-ragas.txt` era insatisfacible
(langchain==0.2.16 exige langsmith<0.2 y langchain-core==1.3.3 exige
langsmith>=0.3.45) y el runner importaba `SingleTurnSample` de un modulo que
ragas 0.4 ya no exporta. Estos tests no instalan nada (el CI no tiene red para
eso): fijan las invariantes que hacian fallar la instalacion o el import, para
que no vuelvan con el siguiente bump de dependabot.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQ = ROOT / "evals" / "rag" / "requirements-ragas.txt"
RUNNER = ROOT / "scripts" / "run_rag_evals.py"
ONE_COMMAND = ROOT / "scripts" / "ragas_crossover.sh"


def _pins() -> dict[str, str]:
    pins: dict[str, str] = {}
    for raw in REQ.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)==([0-9][A-Za-z0-9.]*)", line)
        assert match, f"cada linea debe ser un pin exacto nombre==version: {raw!r}"
        pins[match.group(1).lower().replace("_", "-")] = match.group(2)
    return pins


def _version(text: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", text)[:3])


def test_todo_va_fijado_con_version_exacta():
    pins = _pins()
    for name in ("ragas", "langchain-community", "langchain-core", "langchain", "rapidfuzz"):
        assert name in pins, f"falta el pin de {name}"


def test_langchain_y_langchain_core_comparten_major():
    """langchain 0.2 con langchain-core 1.x es lo que hacia la lista insatisfacible."""
    pins = _pins()
    assert _version(pins["langchain"])[0] == _version(pins["langchain-core"])[0]


def test_langchain_community_aun_trae_chat_models_vertexai():
    """ragas/llms/base.py importa langchain_community.chat_models.vertexai.

    langchain-community 0.4.2 elimino ese modulo; 0.4.0 y 0.4.1 lo traen y
    funcionan con langchain-core 1.x (instalado y ejecutado el 2026-10-27).
    """
    version = _version(_pins()["langchain-community"])
    assert (0, 4, 0) <= version <= (0, 4, 1)


def test_rapidfuzz_presente_para_las_metricas_no_llm():
    """NonLLMStringSimilarity lanza ImportError sin rapidfuzz y ragas no lo declara."""
    assert "rapidfuzz" in _pins()


def test_el_runner_importa_single_turn_sample_de_dataset_schema():
    source = RUNNER.read_text(encoding="utf-8")
    assert "from ragas.dataset_schema import SingleTurnSample" in source


def test_hay_un_solo_comando_documentado_y_ejecutable():
    assert ONE_COMMAND.exists()
    script = ONE_COMMAND.read_text(encoding="utf-8")
    assert "requirements-ragas.txt" in script
    assert "--ragas-crossover" in script
    assert "RAGAS_DO_NOT_TRACK" in script  # el runner bloquea la red: sin telemetria
    assert "bash scripts/ragas_crossover.sh" in REQ.read_text(encoding="utf-8")
    readme = (ROOT / "evals" / "rag" / "README.md").read_text(encoding="utf-8")
    assert "bash scripts/ragas_crossover.sh" in readme
