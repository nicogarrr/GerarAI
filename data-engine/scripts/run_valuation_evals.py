"""C2: ejecuta el dataset congelado de los 8 motores de valoración contra sus gates.

Uso: python data-engine/scripts/run_valuation_evals.py [--json]

Mismo contrato que ``scripts/run_offline_evals.py``:
- cada caso declara en ``applies_to`` que puertas ejercita (opt-out explicito);
- ``expect_gate_failure`` marca los controles negativos: esa puerta TIENE que
  fallar, las demas tienen que pasar;
- imprime cobertura por puerta y por motor, y falla si alguna puerta nunca se
  ejecuto (una puerta que no corre no es una puerta que pasa);
- exit 1 con la lista de fallos.

Determinista: sin red, sin LLM, sobre una base SQLite temporal que se borra al
salir. Los facts se siembran con el mismo patron que
``tests/test_valuation_engines_refined.py`` (``_make_company`` / ``_add_facts`` /
``_add_traceable_wacc`` / ``_add_price``), aqui contra la sesion propia del
runner para no depender del fixture de pytest.

A diferencia del dataset de tesis, el artefacto aqui es la SALIDA DEL MOTOR: el
runner resuelve la empresa, construye el contexto y llama a ``value()``. Los
numeros contra los que comparan las puertas son la forma cerrada declarada en el
caso, no esa salida.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from datetime import date
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DEFAULT_PERIOD = "FY2025"
DEFAULT_FISCAL_YEAR = 2025
DEFAULT_FISCAL_QUARTER = "FY"
DEFAULT_CONFIDENCE = "0.90"
PRICE_DATE = date(2025, 12, 31)


def _hermetic_env() -> str:
    """Point the app at a throwaway SQLite file BEFORE importing it.

    ``app.core.database`` binds its engine to ``settings.database_url`` at import
    time, so the environment has to be set first. Without this the runner would
    read (and seed) whatever local Postgres/SQLite stack the developer runs.
    """
    workdir = tempfile.mkdtemp(prefix="cavaai-valuation-evals-")
    db_path = (Path(workdir) / "valuation_evals.db").as_posix()
    os.environ["APP_ENV"] = "test"
    os.environ["RESEARCH_AUTH_REQUIRED"] = "false"
    os.environ["WORKERS_ENABLED"] = "false"
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
    return workdir


def _unit(value: float) -> str:
    return "decimal" if abs(float(value)) < 1 else "USD"


def _fact_rows(case: dict) -> list[dict]:
    """Seed rows for the case: one per declared metric, with its own period.

    A metric may be declared as a bare number (period/year/quarter/confidence
    default) or as ``{"value": ..., "period": "FY2024", ...}`` so the
    period-anchor cases can move a single fact to another fiscal year.
    """
    rows = []
    for metric, raw in (case.get("facts") or {}).items():
        meta = dict(raw) if isinstance(raw, dict) else {"value": raw}
        raw_value = meta.get("value")
        if raw_value is None:
            raise ValueError(f"fact {metric!r} sin value en el caso")
        value = float(raw_value)
        rows.append(
            {
                "metric": metric,
                "value": value,
                "period": meta.get("period", DEFAULT_PERIOD),
                "fiscal_year": meta.get("fiscal_year", DEFAULT_FISCAL_YEAR),
                "fiscal_quarter": meta.get("fiscal_quarter", DEFAULT_FISCAL_QUARTER),
                "confidence": str(meta.get("confidence", DEFAULT_CONFIDENCE)),
                "is_reported": bool(meta.get("is_reported", True)),
            }
        )
    return rows


def _seed(db, company, case: dict) -> None:
    from app.models import CalculatedMetric, FinancialFact, MarketPrice

    for row in _fact_rows(case):
        db.add(
            FinancialFact(
                company_id=company.id,
                metric=row["metric"],
                value=Decimal(repr(row["value"])),
                unit=_unit(row["value"]),
                period=row["period"],
                fiscal_year=row["fiscal_year"],
                fiscal_quarter=row["fiscal_quarter"],
                source_type="valuation_eval_v1",
                is_reported=row["is_reported"],
                confidence=Decimal(row["confidence"]),
            )
        )
    wacc = case.get("wacc")
    if wacc is not None:
        db.add(
            CalculatedMetric(
                company_id=company.id,
                metric="wacc",
                value=Decimal(repr(float(wacc))),
                unit="decimal",
                period=f"{DEFAULT_FISCAL_YEAR}-12-31:FY",
                fiscal_year=DEFAULT_FISCAL_YEAR,
                status="ok",
                definition_version="WACC_STANDARD_V1",
                formula="ke*E/(D+E) + kd*(1-t)*D/(D+E)",
            )
        )
    price = case.get("price")
    if price is not None:
        db.add(
            MarketPrice(
                company_id=company.id,
                date=PRICE_DATE,
                close=Decimal(repr(float(price))),
                adj_close=Decimal(repr(float(price))),
                source="valuation_eval_v1",
            )
        )
    db.commit()


def _make_company(db, case: dict):
    from app.models import Company

    routing = case.get("company") or {}
    company = Company(
        ticker=routing.get("ticker") or case["id"][:20].upper(),
        name=routing.get("name") or case["id"],
        exchange=routing.get("exchange", "TEST"),
        currency=routing.get("currency", "USD"),
        sector=routing.get("sector", "Test"),
        industry=routing.get("industry", "Test"),
        company_type=routing.get("company_type", "standard"),
        valuation_model=routing.get("valuation_model", "standard_dcf"),
        special_sources=[],
        special_risks=routing.get("special_risks") or [],
        factor_tags=routing.get("factor_tags") or [],
    )
    db.add(company)
    db.flush()
    return company


def _value_case(db, case: dict) -> dict:
    """Run the real engine for one case and return the case enriched with it."""
    from app.data.valuation_scenarios import VALUATION_SCENARIOS
    from app.valuation.engines import resolve, resolve_engine_key
    from app.valuation.engines.base import MODEL_VERSION, apply_publication_blockers

    company = _make_company(db, case)
    _seed(db, company, case)
    price = case.get("price")
    engine = resolve(company)
    context = engine.build_context(db, company, float(price) if price is not None else None)
    # Escenarios declarados del caso (datos, como en app/data/valuation_scenarios.py):
    # solo durante su valoración, para no filtrarse a otros casos.
    declared = case.get("declared_scenarios")
    key = company.ticker.strip().upper()
    if declared is not None:
        VALUATION_SCENARIOS[key] = declared
    try:
        result = apply_publication_blockers(engine.value(context))
    finally:
        if declared is not None:
            VALUATION_SCENARIOS.pop(key, None)
    trace = result.get("trace")
    if not isinstance(trace, dict):
        trace = {}
        result["trace"] = trace
    resolved = resolve_engine_key(company)
    trace.setdefault("engine", resolved)
    trace.setdefault("model_version", MODEL_VERSION)
    result["trace"] = trace
    result["_routing"] = {
        "resolved_engine": resolved,
        "trace_engine": trace.get("engine"),
        "engine_class": type(engine).__name__,
        "engine_key_attribute": getattr(engine, "key", None),
    }
    return {**case, "artifact": result}


def _applies(case: dict, gate_name: str) -> bool:
    """A case that does not declare ``applies_to`` runs every gate."""
    declared = case.get("applies_to")
    if declared is None:
        return True
    return gate_name in declared


def _run(dataset: dict) -> dict:
    import app.models  # noqa: F401  (registers the ORM metadata)
    from app.core.database import Base, SessionLocal
    from app.core.database import engine as db_engine
    from evals.valuation.valuation_gates import GATES

    Base.metadata.create_all(bind=db_engine)
    db = SessionLocal()
    failures: list[str] = []
    executed: dict[str, int] = dict.fromkeys(GATES, 0)
    by_engine: dict[str, dict] = {}
    categories: dict[str, int] = {}
    cases: list[dict] = []
    controls: list[dict] = []
    checks = 0
    try:
        for case in dataset["cases"]:
            enriched = _value_case(db, case)
            engine_key = case["engine"]
            bucket = by_engine.setdefault(
                engine_key, {"cases": 0, "checks": 0, "gates": dict.fromkeys(GATES, 0), "controls": 0}
            )
            bucket["cases"] += 1
            categories[case["category"]] = categories.get(case["category"], 0) + 1
            if case.get("expect_gate_failure"):
                bucket["controls"] += 1
            case_failures: list[str] = []
            expected_failure = case.get("expect_gate_failure")
            for gate_name, gate in GATES.items():
                if not _applies(case, gate_name):
                    continue
                result = gate(enriched)
                checks += 1
                executed[gate_name] += 1
                bucket["checks"] += 1
                bucket["gates"][gate_name] += 1
                if expected_failure == gate_name:
                    controls.append(
                        {
                            "case": case["id"],
                            "engine": engine_key,
                            "gate": gate_name,
                            "passed": bool(result["passed"]),
                            "details": list(result["details"]),
                        }
                    )
                    if result["passed"]:
                        case_failures.append(
                            f"{case['id']}: {gate_name} debia FALLAR y paso"
                        )
                elif not result["passed"]:
                    case_failures.append(
                        f"{case['id']}: {gate_name} fallo: {'; '.join(result['details'])}"
                    )
            failures.extend(case_failures)
            cases.append(
                {
                    "id": case["id"],
                    "engine": engine_key,
                    "category": case["category"],
                    "applies_to": case.get("applies_to"),
                    "expect_gate_failure": expected_failure,
                    "status": "FAIL" if case_failures else "ok",
                    "failures": case_failures,
                }
            )
    finally:
        db.close()

    never_ran = sorted(name for name, count in executed.items() if count == 0)
    if never_ran:
        failures.append(
            "gates que nunca se ejecutaron sobre ningun caso: " + ", ".join(never_ran)
        )
    return {
        "cases": cases,
        "controls": controls,
        "checks": checks,
        "failures": failures,
        "coverage": {
            "gates": executed,
            "engines": by_engine,
            "categories": categories,
        },
        "gates_never_run": never_ran,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--json",
        action="store_true",
        help="emitir el informe como JSON para CI (por stdout, una sola linea)",
    )
    parser.add_argument(
        "--dataset",
        default=str(ROOT / "evals" / "valuation" / "valuation_engines_v1.json"),
        help="ruta del dataset congelado de motores de valoracion",
    )
    args = parser.parse_args(argv)

    workdir = _hermetic_env()
    try:
        dataset = json.loads(Path(args.dataset).read_text(encoding="utf-8"))
        report = _run(dataset)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    payload = {
        "dataset": Path(args.dataset).name,
        "dataset_version": dataset.get("version"),
        "model_version": "valuation-engines-v2",
        "case_count": len(report["cases"]),
        "engine_count": len(report["coverage"]["engines"]),
        "checks": report["checks"],
        "failures": report["failures"],
        "negative_controls": report["controls"],
        "case_results": report["cases"],
        "coverage": report["coverage"],
        "gates_never_run": report["gates_never_run"],
        "ok": not report["failures"],
    }
    if args.json:
        print(json.dumps(payload, sort_keys=True))
        return 1 if report["failures"] else 0

    for case in report["cases"]:
        marker = "  <-- control negativo" if case["expect_gate_failure"] else ""
        print(f"[{case['status']}] {case['id']} ({case['engine']} / {case['category']}){marker}")
        for failure in case["failures"]:
            print(f"    {failure}")

    engines = report["coverage"]["engines"]
    print(
        f"\n{len(report['cases'])} casos -> {report['checks']} checks ejecutados "
        f"en {len(engines)} motores"
    )
    print("Cobertura por puerta:")
    for gate_name, count in report["coverage"]["gates"].items():
        marker = "  <-- NUNCA SE EJECUTO" if count == 0 else ""
        print(f"  {gate_name}: {count}{marker}")
    print("Cobertura por motor:")
    for engine_key, bucket in sorted(engines.items()):
        covered = sum(1 for count in bucket["gates"].values() if count)
        print(
            f"  {engine_key}: {bucket['cases']} casos, {bucket['checks']} checks, "
            f"{covered}/{len(bucket['gates'])} puertas, {bucket['controls']} controles negativos"
        )
    print("Cobertura por categoria:")
    for category, count in sorted(report["coverage"]["categories"].items()):
        print(f"  {category}: {count}")

    if report["failures"]:
        print(f"\n{len(report['failures'])} FALLOS:")
        for failure in report["failures"]:
            print(f"  - {failure}")
        return 1
    print("\nTodos los gates en verde.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
