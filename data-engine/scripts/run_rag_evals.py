"""Stage C1: ejecuta el golden set del RAG contra hard gates y metricas RAGAS.

Uso:
    python data-engine/scripts/run_rag_evals.py                 # real: Qdrant + embedder
    python data-engine/scripts/run_rag_evals.py --dry-run       # stub lexical, no gateable
    python data-engine/scripts/run_rag_evals.py --json out.json
    python data-engine/scripts/run_rag_evals.py --ragas-crossover

Determinista y hermetico: sin red (guardian de socket que solo permite loopback)
y sin proveedor de LLM. El juez de las metricas es lexical, no un LLM, porque
este repo declara "no LLM judging LLM" y porque un juez LLM da un numero distinto
en cada corrida, que es lo que hace una puerta imposible de gatear.

Refuse-to-skip: en modo real, si el embedder, Qdrant o la ingesta no funcionan,
el runner sale con 1. No se degrada a un stub en silencio (mismo criterio que
"RAG activation tests skipped: Qdrant service not reachable" en ci.yml). El modo
--dry-run si usa un stub, y sus numeros se imprimen marcados NO GATEABLES.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from evals.rag.rag_gates import (  # noqa: E402
    GATES,
    NEGATIVE_CONTROL_CATEGORY,
    applies,
    is_abstention,
    parse_citations,
)
from evals.rag.rag_harness import (  # noqa: E402
    HarnessUnavailable,
    NetworkGuard,
    build_lexicon,
    build_retriever,
    compose_answer,
)
from evals.rag.rag_metrics import (  # noqa: E402
    answer_relevancy,
    context_precision,
    context_recall,
    faithfulness,
    mean,
)

CORPUS_PATH = ROOT / "evals" / "rag" / "rag_corpus_v1.json"
GOLDEN_PATH = ROOT / "evals" / "rag" / "rag_golden_v1.json"

# Umbrales de las 4 metricas gateables + las 2 de seguridad.
#
# Los cuatro primeros son los del encargo (faithfulness 0.75, answer_relevancy
# 0.70, context_precision 0.70, context_recall 0.70). `abstention_accuracy` y
# `source_hit_rate` no los fija el encargo y aqui van a 1.00 y 0.90: la
# abstention se mide sobre 16 casos, asi que un solo fallo es 0.94 y tiene que
# tumbar la puerta, y la cita de fuentes es la garantia de que el usuario puede
# volver al original.
THRESHOLDS = {
    "faithfulness": 0.75,
    "answer_relevancy": 0.70,
    "context_precision": 0.70,
    "context_recall": 0.70,
    "abstention_accuracy": 1.00,
    "source_hit_rate": 0.90,
}

# Ultimo valor observado en el pipeline real (Qdrant + all-MiniLM-L6-v2, 17
# documentos, 55 casos) el 2026-10-01. NO es un umbral: el runner lo imprime
# como delta para que una regresion se vea aunque no tumbe la puerta. Una
# puerta que nunca puede fallar no vigila nada, y esto es lo que convierte
# "faithfulness 0.75" en un numero con recorrido.
OBSERVED_BASELINE = {
    "faithfulness": 1.000,
    "answer_relevancy": 0.760,
    "context_precision": 0.866,
    "context_recall": 1.000,
    "abstention_accuracy": 1.000,
    "source_hit_rate": 1.000,
}

GATEABLE_METRICS = (
    "faithfulness",
    "answer_relevancy",
    "context_precision",
    "context_recall",
    "abstention_accuracy",
    "source_hit_rate",
)


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def measure(case: dict, artifact: dict, corpus: dict) -> dict:
    """Metricas de UN caso. Devuelve {} para los controles negativos.

    Las cuatro metricas de RAGAS solo se miden en los casos que DEBEN responder:
    faithfulness y answer_relevancy no tienen sentido sobre una abstention, y
    context_precision / context_recall se evaluarian contra un reference vacio
    (expected_sources = []), lo que daria un 1.0 artificial a un RAG que se
    abstiene en todo. La abstention se mide aparte, en su propia metrica.
    """
    if case["category"] == NEGATIVE_CONTROL_CATEGORY:
        return {}
    if case["must_refuse"]:
        return {
            "abstention_accuracy": 1.0 if is_abstention(artifact["answer"]) else 0.0,
        }
    retrieved_texts = [hit.get("text") or "" for hit in artifact["retrieved"]]
    reference_texts = [
        corpus["documents_by_id"][source]["content"] for source in case["expected_sources"]
    ]
    context = "\n".join(retrieved_texts)
    answer_prose_text = "\n".join(
        line for line in artifact["answer"].splitlines() if not line.startswith("Fuentes:")
    )
    cited = parse_citations(artifact["answer"]) or []
    return {
        "faithfulness": faithfulness(answer_prose_text, context)["score"],
        "answer_relevancy": answer_relevancy(case["question"], artifact["answer"])["score"],
        "context_precision": context_precision(retrieved_texts, reference_texts)["score"],
        "context_recall": context_recall(retrieved_texts, reference_texts)["score"],
        "source_hit_rate": 1.0 if set(cited) & set(case["expected_sources"]) else 0.0,
    }


def run(dry_run: bool, verbose: bool) -> dict:
    corpus_raw = load_json(CORPUS_PATH)
    golden = load_json(GOLDEN_PATH)
    documents = corpus_raw["documents"]
    corpus = {
        "id": corpus_raw.get("corpus_id", "rag_corpus_v1"),
        "origin": corpus_raw.get("corpus_origin", "?"),
        "documents": documents,
        "documents_by_id": {doc["id"]: doc for doc in documents},
    }
    corpus_ids = sorted(corpus["documents_by_id"])
    lexicon = build_lexicon([doc["content"] for doc in documents])

    guard = NetworkGuard(allow_model_download=allow_model_download()).install()
    try:
        retriever = build_retriever(documents, dry_run, guard)
    except HarnessUnavailable as exc:
        print(f"ABSTENCION: el pipeline real no puede correr: {exc}", file=sys.stderr)
        print(
            "No se puede medir el RAG de verdad, y un numero medido contra un stub "
            "no es un numero del RAG. Arregla el embedder o Qdrant; el runner no se "
            "salta. Con --dry-run corre un stub lexical, pero sus numeros NO son gateables.",
            file=sys.stderr,
        )
        return {"exit_code": 1, "mode": "real", "error": str(exc)}

    try:
        return _execute(golden, corpus, corpus_ids, retriever, lexicon, dry_run, verbose)
    finally:
        guard.restore()
        retriever.close()


def allow_model_download() -> bool:
    """Descargar all-MiniLM-L6-v2 es el unico uso de red permitido, y es opt-in.

    Sin esta variable el guardian bloquea tambien huggingface.co y el runner
    falla con un mensaje claro en vez de bajarse un modelo de 90 MB sin que nadie
    lo haya pedido. En CI hay que ponerla a 1 la primera vez (el modelo no esta
    en la cache del runner).
    """
    return os.getenv("RAG_EVALS_ALLOW_MODEL_DOWNLOAD") == "1"


def _execute(
    golden: dict,
    corpus: dict,
    corpus_ids: list[str],
    retriever: object,
    lexicon: object,
    dry_run: bool,
    verbose: bool,
) -> dict:
    cases = golden["cases"]
    executed: dict[str, int] = dict.fromkeys(GATES, 0)
    measurements: dict[str, list[float]] = {name: [] for name in GATEABLE_METRICS}
    failures: list[str] = []
    per_case: list[dict] = []
    samples: list[dict] = []
    counts = dict.fromkeys(GATEABLE_METRICS, 0)

    for case in cases:
        artifact = case.get("artifact")
        if artifact is None:
            retrieved = retriever.search(case["question"])
            artifact = {
                "answer": compose_answer(case["question"], retrieved, lexicon),
                "retrieved": retrieved,
            }
        observed = dict(case)
        observed["artifact"] = artifact
        observed["corpus_ids"] = corpus_ids

        case_failures: list[str] = []
        for gate_name, gate in GATES.items():
            if not applies(case, gate_name):
                continue
            result = gate(observed)
            executed[gate_name] += 1
            expected_failure = case.get("expect_gate_failure")
            if expected_failure == gate_name:
                if result["passed"]:
                    case_failures.append(f"{gate_name} debia FALLAR y paso")
            elif not result["passed"]:
                case_failures.append(f"{gate_name} fallo: {'; '.join(result['details'])}")

        metrics = measure(case, artifact, corpus)
        for name, value in metrics.items():
            measurements[name].append(value)
            counts[name] += 1
        if case["category"] != NEGATIVE_CONTROL_CATEGORY and not case["must_refuse"]:
            # Las MISMAS muestras que se acaban de medir, para que el crossover
            # con ragas compare sobre este pipeline y no sobre una segunda
            # corrida que podria tener otro estado de Qdrant.
            samples.append(
                {
                    "id": case["id"],
                    "retrieved_contexts": [hit.get("text") or "" for hit in artifact["retrieved"]],
                    "reference_contexts": [
                        corpus["documents_by_id"][source]["content"]
                        for source in case["expected_sources"]
                    ],
                }
            )

        failures.extend(f"{case['id']}: {message}" for message in case_failures)
        per_case.append(
            {
                "id": case["id"],
                "category": case["category"],
                "retrieved": [hit["doc_id"] for hit in artifact["retrieved"]],
                "answer": artifact["answer"],
                "metrics": metrics,
                "gate_failures": case_failures,
            }
        )
        status = "FAIL" if case_failures else "ok"
        if verbose or case_failures:
            print(f"[{status}] {case['id']} ({case['category']})")

    measured = [c for c in cases if c["category"] != NEGATIVE_CONTROL_CATEGORY]
    refuse = [c for c in measured if c["must_refuse"]]
    summary = {name: mean(values) for name, values in measurements.items()}

    print()
    print(f"dataset={golden['dataset']} casos={len(cases)} "
          f"(medidos {len(measured)}, controles negativos {len(cases) - len(measured)})")
    print(f"corpus={corpus['id']} documentos={len(corpus['documents'])} "
          f"origen={corpus['origin']}")
    print(f"modo={'dry_run' if dry_run else 'real'} "
          f"recuperador={getattr(retriever, 'name', '?')} "
          f"chunks_indexados={getattr(retriever, 'chunks_indexed', 'n/d')}")
    print(f"gateable={'no (stub determinista)' if dry_run else 'si'}")
    print()
    print("METRICAS GATEABLES (RAGAS con juez determinista; sin LLM, sin red)")
    for name in GATEABLE_METRICS:
        value = summary.get(name, 0.0)
        threshold = THRESHOLDS[name]
        ok = value >= threshold
        baseline = OBSERVED_BASELINE[name]
        delta = value - baseline
        trend = "sin cambio" if abs(delta) < 0.0005 else f"{delta:+.3f} vs baseline"
        print(f"  {name:<20} {value:.3f}  >= {threshold:.2f}  {'OK' if ok else 'FAIL'}"
              f"   ({counts[name]} casos, {trend})")
        if not ok:
            failures.append(f"metrica {name}={value:.3f} por debajo del umbral {threshold:.2f}")
    print()
    print(f"  casos que DEBEN negarse: {len(refuse)}; "
          f"el resto ({len(measured) - len(refuse)}) exige respuesta y fuentes")
    print()
    print("PUERTAS: cobertura por puerta")
    for gate_name, count in executed.items():
        marker = "  <-- NUNCA SE EJECUTO" if count == 0 else ""
        print(f"  {gate_name:<28} {count}{marker}")
    never_ran = [name for name, count in executed.items() if count == 0]
    if never_ran:
        failures.append(
            "gates que nunca se ejecutaron sobre ningun caso: " + ", ".join(sorted(never_ran))
        )

    if failures:
        print(f"\n{len(failures)} FALLOS:")
        for failure in failures:
            print(f"  - {failure}")
        return {
            "exit_code": 1,
            "mode": "dry_run" if dry_run else "real",
            "metrics": summary,
            "counts": counts,
            "gate_coverage": executed,
            "cases": per_case,
            "samples": samples,
            "failures": failures,
        }

    print("\nTodos los gates en verde y las 6 metricas por encima de su umbral.")
    return {
        "exit_code": 0,
        "mode": "dry_run" if dry_run else "real",
        "metrics": summary,
        "counts": counts,
        "gate_coverage": executed,
        "cases": per_case,
        "samples": samples,
        "failures": [],
    }


def ragas_crossover(report: dict) -> int:
    """Compara las dos metricas no-LLM de RAGAS con las deterministas del repo.

    RAGAS define faithfulness y answer_relevancy con un juez LLM, que aqui esta
    prohibido; las dos metricas de recuperacion si las define RAGAS con una
    distancia entre strings, y son las que este crossover cuantifica. La
    diferencia que salga no es un fallo: es el precio de sustituir el juez LLM
    por un juez lexical, y por eso se mide y se documenta en vez de suponerlo.
    """
    try:
        import asyncio

        # ragas >= 0.2 publica SingleTurnSample en `dataset_schema`; `ragas.dataset`
        # es otro modulo desde 0.4 y ya no lo exporta.
        try:
            from ragas.dataset_schema import SingleTurnSample
        except ImportError:  # ragas antiguo
            from ragas.dataset import SingleTurnSample  # type: ignore[no-redef]
        from ragas.metrics import NonLLMContextPrecisionWithReference, NonLLMContextRecall
    except Exception as exc:
        print(
            "\nCROSSOVER RAGAS: no ejecutable. "
            f"{type(exc).__name__}: {exc}\n"
            "Ejecutalo en su venv aislado con un solo comando, desde data-engine/: "
            "bash scripts/ragas_crossover.sh (ver evals/rag/requirements-ragas.txt).",
            file=sys.stderr,
        )
        return 0

    samples = [
        (sample["retrieved_contexts"], sample["reference_contexts"])
        for sample in report.get("samples", [])
    ]
    if not samples:
        print("\nCROSSOVER RAGAS: sin muestras. Corre el runner con --json primero.")
        return 0

    async def score() -> tuple[list[float], list[float]]:
        precision = NonLLMContextPrecisionWithReference()
        recall = NonLLMContextRecall()
        precisions, recalls = [], []
        for retrieved, reference in samples:
            precisions.append(await precision.single_turn_ascore(
                SingleTurnSample(retrieved_contexts=retrieved, reference_contexts=reference)
            ))
            recalls.append(await recall.single_turn_ascore(
                SingleTurnSample(retrieved_contexts=retrieved, reference_contexts=reference)
            ))
        return precisions, recalls

    precisions, recalls = asyncio.run(score())
    print("\nCROSSOVER RAGAS (ragas real, NonLLMStringSimilarity, sin juez LLM)")
    for name, values, ours in (
        ("context_precision", precisions, report["metrics"]["context_precision"]),
        ("context_recall", recalls, report["metrics"]["context_recall"]),
    ):
        theirs = mean(values)
        print(
            f"  {name:<20} ragas={theirs:.3f}  evals/rag={ours:.3f}  "
            f"delta={ours - theirs:+.3f}  (n={len(values)})"
        )
    print(
        "  Los 4 numeros gateables no dependen de ragas: se calculan con "
        "evals/rag/rag_metrics.py para que la puerta no dependa de una libreria."
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Golden set RAG: gates + metricas RAGAS")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="recuperador stub determinista: rapido, pero sus numeros NO son gateables",
    )
    parser.add_argument("--json", help="volcar el informe completo a este fichero")
    parser.add_argument("--verbose", action="store_true", help="una linea por caso")
    parser.add_argument(
        "--ragas-crossover",
        action="store_true",
        help="comparar las metricas no-LLM de RAGAS con las de este repo",
    )
    args = parser.parse_args()

    report = run(dry_run=args.dry_run, verbose=args.verbose)
    if report.get("error"):
        return 1
    if args.json:
        Path(args.json).write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    if args.ragas_crossover:
        ragas_crossover(report)
    return int(report["exit_code"])


if __name__ == "__main__":
    sys.exit(main())
