#!/usr/bin/env python
"""Gate de cobertura de data-engine: mide de verdad y falla si la cobertura baja.

El repo tenia 2585 tests y 0 % de medicion. "2585 tests pasan" no dice nada de
si el codigo nuevo esta probado. Este script lo convierte en un numero que CI
puede gatear:

    python scripts/run_coverage_gate.py                   # suite + gate (CI)
    python scripts/run_coverage_gate.py --report          # imprime y sale 0
    python scripts/run_coverage_gate.py --update-baseline # regenera el baseline

Decisiones de diseno (y por que):

1. NO se anade --cov a `addopts` de pyproject.toml. `python -m pytest` a secas
   es lo que ejecutan ci.yml, CONTRIBUTING y las plantillas de PR; meter
   pytest-cov en addopts rompe esos comandos donde no este instalado. Este
   script es el unico que pasa --cov, y siempre explicito.

2. Los umbrales NO estan hardcodeados: viven en coverage_baseline.json, que es
   la medicion real. El script los deriva de ahi. No hay numeros magicos aqui.

3. Fail-closed en todas las direcciones. Ante la duda, falla:
     - baseline ausente o corrupto             -> falla
     - clave o tipo inesperado en el JSON      -> falla (un typo no es cobertura)
     - paquete medido sin entrada en baseline  -> falla (fuerza a declararlo)
     - paquete del baseline que no se mide     -> falla (fuerza a podarlo)
   Unico escape: la lista `exempt` del baseline, o regenerar el baseline con
   --update-baseline tras revisar el diff a mano.

4. Ratchet por paquete: cada uno tiene linea base y caida maxima
   (`max_drop_points`, por defecto 0). El umbral efectivo es
   floor(linea_base) - max_drop_points, es decir redondeo a la baja. Redondear
   hacia abajo regala hasta 1 punto de holgura por paquete, lo que absorbe el
   ruido normal de medicion sin permitir que la cobertura caiga de verdad.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import math
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ENGINE_ROOT = Path(__file__).resolve().parents[1]
BASELINE_PATH = ENGINE_ROOT / "coverage_baseline.json"
REPORT_DIR = ENGINE_ROOT / "htmlcov"
JSON_REPORT = REPORT_DIR / "coverage.json"

BASELINE_VERSION = 1

# Prefijos de paquete. El match es por prefijo de ruta de componente entero y
# gana el mas largo (longest_match), de modo que app/valuation/engines/dcf.py
# cae en app/valuation/engines y no en app/valuation, y "app/valuationfoo" no
# cuela como app/valuation.
PACKAGE_PREFIXES: tuple[str, ...] = (
    "app/api/routes",
    "app/valuation/engines",
    "app/services",
    "app/workflows",
    "app/models",
    "app/core",
    "app/llm",
    "app/schemas",
    "app/data",
    "app/workers",
    "app/valuation",
    "app/api",
    "app",
    "alembic",
)
CATCH_ALL = "other"
TOTAL_KEY = "TOTAL"

# Claves top-level admitidas en coverage_baseline.json. Fail-closed: una clave
# desconocida suele ser un typo, y un typo silencioso es cobertura que no se
# gatea sin que nadie lo note.
_ALLOWED_TOP_KEYS = {"version", "generated_at", "measurement", "policy", "exempt", "packages"}
_ALLOWED_PACKAGE_KEYS = {"coverage", "statements", "max_drop_points"}
_ALLOWED_POLICY_KEYS = {"max_drop_points"}


class GateConfigError(RuntimeError):
    """Baseline o informe inutilizable. El gate falla cerrado."""


# --------------------------------------------------------------------- extract


def _normalise(path: str) -> str:
    p = path.replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    return p


def package_of(path: str) -> str:
    """Paquete al que pertenece un fichero del informe JSON de coverage.py."""
    parts = _normalise(path).split("/")
    best = ""
    for prefix in PACKAGE_PREFIXES:
        pparts = prefix.split("/")
        if len(pparts) > len(parts):
            continue
        if parts[: len(pparts)] == pparts and len(prefix) > len(best):
            best = prefix
    if best:
        return best
    return CATCH_ALL


@dataclass
class PackageCoverage:
    """Cobertura agregada de un paquete, ponderada por sentencias y ramas.

    Se cuentan RAMAS ademas de sentencias a proposito. Con `branch = True` el
    numero que publica coverage.py es (covered_lines + covered_branches) /
    (num_statements + num_branches), y gatear solo sentencias dejaria
    `branch = True` como decoracion: se pagaria el coste de medir ramas y no se
    gatearian. Measured asi, el total es 81.49% y no el 83.39% de solo
    sentencias, que es un numero mas alto y menos honesto.
    """

    percent: float
    covered: int = 0
    total: int = 0

    def add(self, covered: int, total: int) -> None:
        self.covered += covered
        self.total += total

    def finish(self) -> PackageCoverage:
        self.percent = 100.0 if self.total == 0 else 100.0 * self.covered / self.total
        return self


def aggregate_by_package(report: dict[str, Any]) -> dict[str, PackageCoverage]:
    """Convierte el JSON de coverage.py en cobertura por paquete.

    Pondera por numero de sentencias (y ramas), no como media de porcentajes:
    promediar porcentajes deja que un fichero de 3 lineas al 100 % eleve a un
    paquete de 20 000 lineas. Con la ponderacion, lo que sube y lo baja es
    codigo.
    """
    files = report.get("files")
    if not isinstance(files, dict):
        raise GateConfigError(
            "el informe de coverage no tiene la clave 'files' (objeto). "
            "No es un informe de coverage.py: regeneralo con --cov-report=json."
        )
    buckets: dict[str, PackageCoverage] = {}
    for path, payload in files.items():
        summary = (payload or {}).get("summary")
        if not isinstance(summary, dict):
            raise GateConfigError(f"el fichero {path!r} no trae 'summary' en el informe")
        covered = int(summary.get("covered_lines", 0)) + int(summary.get("covered_branches", 0))
        total = int(summary.get("num_statements", 0)) + int(summary.get("num_branches", 0))
        name = package_of(path)
        bucket = buckets.setdefault(name, PackageCoverage(percent=0.0))
        bucket.add(covered, total)
    return {name: b.finish() for name, b in buckets.items()}


# -------------------------------------------------------------------- baseline


def _require_number(value: Any, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise GateConfigError(f"{where}: se esperaba un numero, hay {type(value).__name__}")
    if math.isnan(value) or math.isinf(value):
        raise GateConfigError(f"{where}: el numero no es finito")
    return float(value)


def load_baseline(path: Path | str = BASELINE_PATH) -> dict[str, Any]:
    """Lee y valida el baseline. Cualquier problema -> GateConfigError."""
    path = Path(path)
    if not path.is_file():
        raise GateConfigError(
            f"no existe el baseline {path}. Sin el, los umbrales serian inventados: "
            "genera uno con `python scripts/run_coverage_gate.py --update-baseline` "
            "y revisalo a mano antes de commitearlo."
        )
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GateConfigError(f"el baseline {path} no se puede leer: {exc}") from exc
    if not isinstance(raw, dict):
        raise GateConfigError(f"el baseline {path} deberia ser un objeto JSON")

    unknown = set(raw) - _ALLOWED_TOP_KEYS
    if unknown:
        raise GateConfigError(
            f"el baseline {path} tiene claves desconocidas: {sorted(unknown)}. "
            f"Admitidas: {sorted(_ALLOWED_TOP_KEYS)}"
        )
    version = raw.get("version")
    if version != BASELINE_VERSION:
        raise GateConfigError(
            f"version de baseline {version!r} no soportada (se espera {BASELINE_VERSION})"
        )
    for key in ("measurement", "policy", "packages"):
        if not isinstance(raw.get(key), dict):
            raise GateConfigError(f"el baseline {path} necesita un objeto '{key}'")
    if "total" not in raw["measurement"]:
        raise GateConfigError(f"el baseline {path} necesita 'measurement.total'")

    policy = raw["policy"]
    unknown = set(policy) - _ALLOWED_POLICY_KEYS
    if unknown:
        raise GateConfigError(f"'policy' tiene claves desconocidas: {sorted(unknown)}")
    default_drop = _require_number(policy.get("max_drop_points", 0.0), "policy.max_drop_points")
    if default_drop < 0:
        raise GateConfigError("policy.max_drop_points no puede ser negativo")

    exempt = raw.get("exempt", [])
    if not isinstance(exempt, list):
        raise GateConfigError("'exempt' debe ser una lista")
    exempt_names: set[str] = set()
    for index, item in enumerate(exempt):
        where = f"exempt[{index}]"
        if not isinstance(item, dict):
            raise GateConfigError(f"{where}: se esperaba un objeto con 'package' y 'reason'")
        unknown = set(item) - {"package", "reason"}
        if unknown:
            raise GateConfigError(f"{where}: claves desconocidas {sorted(unknown)}")
        name = item.get("package")
        if not isinstance(name, str) or not name:
            raise GateConfigError(f"{where}.package: se esperaba un nombre no vacio")
        # El motivo es obligatorio y no puede ser vacio: una exencion sin
        # explicacion es exactamente el tipo de hueco que este gate existe para
        # que alguien decida por escrito, no para que se cuelgue en silencio.
        reason = item.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise GateConfigError(
                f"{where}.reason: toda exencion necesita un motivo escrito y no vacio"
            )
        exempt_names.add(name)

    packages = raw["packages"]
    if not packages:
        raise GateConfigError("'packages' esta vacio: no habria nada que gatear")
    for name, entry in packages.items():
        where = f"packages[{name!r}]"
        if not isinstance(entry, dict):
            raise GateConfigError(f"{where}: se esperaba un objeto")
        unknown = set(entry) - _ALLOWED_PACKAGE_KEYS
        if unknown:
            raise GateConfigError(f"{where}: claves desconocidas {sorted(unknown)}")
        if "coverage" not in entry:
            raise GateConfigError(f"{where}: falta 'coverage'")
        pct = _require_number(entry["coverage"], f"{where}.coverage")
        if not 0.0 <= pct <= 100.0:
            raise GateConfigError(f"{where}.coverage fuera de rango [0, 100]: {pct}")
        if "statements" in entry:
            _require_number(entry["statements"], f"{where}.statements")
        drop = _require_number(entry.get("max_drop_points", default_drop), f"{where}.max_drop_points")
        if drop < 0:
            raise GateConfigError(f"{where}.max_drop_points no puede ser negativo")

    # Normalizado para consumo interno; el original se conserva para --update.
    raw["_default_drop"] = default_drop
    raw["_exempt"] = exempt_names
    return raw


def _aggregate(
    packages: dict[str, PackageCoverage], exempt: set[str]
) -> tuple[float, int, int]:
    """(porcentaje, cubiertas, operaciones) de lo que realmente se gatea.

    Los paquetes `exempt` quedan FUERA. Si se dejaran dentro, marcar un paquete
    como exempt no serviria de nada: seguiria hundiendo el total y el gate
    seguiria fallando por el paquete que se dijo exento.

    evaluate() y render_baseline() usan ESTA misma funcion a proposito: si cada
    uno calculara el total por su cuenta, el total guardado en el baseline y el
    total que se gatea podrian divergir en silencio (y asi fue: 84.07% gateado
    contra un 81.49% guardado, porque uno contaba alembic y el otro no).
    """
    gated = {name: p for name, p in packages.items() if name not in exempt}
    covered = sum(p.covered for p in gated.values())
    statements = sum(p.total for p in gated.values())
    percent = 100.0 if statements == 0 else 100.0 * covered / statements
    return percent, covered, statements


def _aggregate_all(packages: dict[str, PackageCoverage]) -> tuple[float, int, int]:
    """Igual que _aggregate pero incluyendo los exentos, solo para informar."""
    covered = sum(p.covered for p in packages.values())
    statements = sum(p.total for p in packages.values())
    percent = 100.0 if statements == 0 else 100.0 * covered / statements
    return percent, covered, statements


def render_baseline(
    packages: dict[str, PackageCoverage],
    max_drop_points: float,
    exempt: list[dict[str, str]],
) -> dict[str, Any]:
    """Construye el diccionario que se escribe a coverage_baseline.json.

    El total se calcula aqui, con la MISMA regla que evaluate(), para que el
    numero guardado y el numero gateado no puedan separarse. Se guardan los dos
    (con y sin exentos) para que el informe sea auditable.
    """
    exempt_names = {item["package"] for item in exempt}
    total, covered, statements = _aggregate(packages, exempt_names)
    total_all, covered_all, statements_all = _aggregate_all(packages)
    return {
        "version": BASELINE_VERSION,
        "generated_at": _dt.datetime.now(_dt.UTC).replace(microsecond=0).isoformat(),
        "measurement": {
            "command": "python scripts/run_coverage_gate.py",
            "branch": True,
            "total": round(total, 2),
            "operations": statements,
            "covered": covered,
            # Lo que seria el total si tambien se gatearan los exentos. Se
            # guarda para que la cifra que se anuncia no pueda superiorarse
            # escondiendo paquetes en `exempt`.
            "total_including_exempt": round(total_all, 2),
            "operations_including_exempt": statements_all,
            "covered_including_exempt": covered_all,
        },
        "policy": {"max_drop_points": max_drop_points},
        "exempt": sorted(exempt, key=lambda item: item["package"]),
        "packages": {
            name: {
                "coverage": round(pkg.percent, 2),
                "statements": pkg.total,
                "max_drop_points": max_drop_points,
            }
            for name, pkg in sorted(packages.items())
        },
    }


# --------------------------------------------------------------------- evaluate


@dataclass
class Violation:
    kind: str
    subject: str
    message: str


@dataclass
class GateResult:
    total: float
    total_min: float
    total_including_exempt: float
    rows: list[tuple[str, float | None, float, float | None, float | None, str]]
    violations: list[Violation]

    @property
    def ok(self) -> bool:
        return not self.violations


def _threshold(base: float, drop: float) -> float:
    """floor(base) - drop. El floor es la holgura sub-punto gratuita."""
    return math.floor(base) - drop


def evaluate(
    packages: dict[str, PackageCoverage],
    baseline: dict[str, Any],
) -> GateResult:
    """Compara la medicion contra el baseline. logica pura y fail-closed.

    `packages` es lo que se ha medido AHORA; `baseline` viene de load_baseline().
    """
    default_drop = float(baseline.get("_default_drop", 0.0))
    exempt: set[str] = set(baseline.get("_exempt", set()))
    base_packages: dict[str, Any] = baseline["packages"]
    base_total = _require_number(baseline["measurement"]["total"], "measurement.total")
    total_drop = default_drop

    # --- agregado: ver _aggregate(). El total que se gatea y el que se imprime
    # salen de la misma llamada, con los exentos fuera.
    total, covered, statements = _aggregate(packages, exempt)
    total_all, _, _ = _aggregate_all(packages)
    total_min = _threshold(base_total, total_drop)

    violations: list[Violation] = []
    if total + 1e-9 < total_min:
        violations.append(
            Violation(
                "global",
                TOTAL_KEY,
                f"{TOTAL_KEY}: cobertura total {total:.2f}% < minimo {total_min:.2f}% "
                f"(linea base {base_total:.2f}%, caida maxima {total_drop:g} pt)",
            )
        )

    rows: list[tuple[str, float | None, float, float | None, float | None, str]] = []
    for name in sorted(set(packages) | set(base_packages) | exempt):
        measured = packages.get(name)
        entry = base_packages.get(name)
        base_pct = float(entry["coverage"]) if isinstance(entry, dict) else None
        drop = default_drop
        if isinstance(entry, dict) and "max_drop_points" in entry:
            drop = _require_number(entry["max_drop_points"], f"packages[{name!r}].max_drop_points")
        minimum = _threshold(base_pct, drop) if base_pct is not None else None
        delta = (measured.percent - base_pct) if (measured and base_pct is not None) else None
        status = "ok"

        if name in exempt:
            status = "exempt"
        elif measured is not None and entry is None:
            # Fail-closed: paquete nuevo. Puede ser codigo nuevo sin tests, o un
            # paquete renombrado. Las dos cosas exigen una decision humana.
            status = "undeclared"
            violations.append(
                Violation(
                    "undeclared",
                    name,
                    f"{name}: paquete medido sin linea base ({measured.percent:.2f}%). "
                    f"Declaralo en coverage_baseline.json o marcalo `exempt` si es "
                    f"harness. Sin decision explicita, el gate falla.",
                )
            )
        elif measured is None and entry is not None:
            # Fail-closed: el baseline mida algo que ya no se mide. Puede ser un
            # paquete borrado (legitimo) o una medicion rota (no legitimo).
            status = "stale"
            violations.append(
                Violation(
                    "stale",
                    name,
                    f"{name}: el baseline lo declara pero la medicion no lo encuentra. "
                    f"Si el paquete ya no existe, podalo con --update-baseline.",
                )
            )
        elif measured is not None and minimum is not None and measured.percent + 1e-9 < minimum:
            status = "regressed"
            violations.append(
                Violation(
                    "regressed",
                    name,
                    f"{name}: cobertura {measured.percent:.2f}% < minimo {minimum:.2f}% "
                    f"(linea base {base_pct:.2f}%, caida {delta:+.2f} pt, "
                    f"permitida -{drop:g} pt)",
                )
            )
        rows.append((name, base_pct, measured.percent if measured else None, minimum, delta, status))

    return GateResult(
        total=total,
        total_min=total_min,
        total_including_exempt=total_all,
        rows=rows,
        violations=violations,
    )


# ----------------------------------------------------------------------- report


def format_report(result: GateResult, *, title: str, exempt: list[dict[str, str]] | None = None) -> str:
    """Informe legible: una fila por paquete con linea base, actual y delta."""
    width = max((len(r[0]) for r in result.rows), default=10)
    lines = [
        title,
        "=" * len(title),
        f"{'paquete':<{width}}  {'base':>8}  {'actual':>8}  {'delta':>8}  {'minimo':>8}  estado",
        f"{'-' * width}  {'-' * 8}  {'-' * 8}  {'-' * 8}  {'-' * 8}  " + "-" * 9,
    ]

    def fmt(value: float | None, spec: str = ">8.2f") -> str:
        return format(value, spec) if value is not None else format("-", ">8")

    for name, base, actual, minimum, delta, status in result.rows:
        lines.append(
            f"{name:<{width}}  {fmt(base)}  {fmt(actual)}  "
            f"{format(delta, '>+8.2f') if delta is not None else format('-', '>8')}  "
            f"{fmt(minimum)}  {status}"
        )
    lines.append(f"{'-' * width}  {'-' * 8}  {'-' * 8}  {'-' * 8}  {'-' * 8}  " + "-" * 9)
    lines.append(
        f"{TOTAL_KEY:<{width}}  {'-':>8}  {result.total:>8.2f}  {'-':>8}  "
        f"{result.total_min:>8.2f}  {'PASS' if result.ok else 'FAIL'}"
    )
    lines.append("")
    # El total de la tabla excluye los exentos. Se dice aqui cuanto seria
    # incluyendolos, para que mover un paquete a `exempt` no pueda subir el
    # titular sin que se note en el propio informe.
    lines.append(
        f"(total gateado {result.total:.2f}%; incluyendo exentos "
        f"{result.total_including_exempt:.2f}%)"
    )
    if result.violations:
        lines.append(f"GATE FALLIDO: {len(result.violations)} violation/es")
        for violation in result.violations:
            # El mensaje ya trae el sujeto dentro (nombre del paquete + puntos),
            # para que un log que solo recoja el mensaje siga siendo util.
            lines.append(f"  [{violation.kind}] {violation.message}")
    else:
        lines.append("GATE OK: ninguna violacion.")
    if exempt:
        # Los exentos se siguen reportando (con su % medido) y se recuerda por
        # que estan fuera del gate, para que la exencion no se lea como
        # "este paquete lo tapamos y nadie lo mira".
        lines.append("")
        lines.append("Exentos del gate (se miden, no se gatean):")
        for item in exempt:
            lines.append(f"  - {item['package']}: {item['reason']}")
    return "\n".join(lines)


# -------------------------------------------------------------------------- run


def _load_json_report(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise GateConfigError(
            f"no se genero el informe de cobertura {path}. "
            "Se necesita `----cov-report=json` para que el gate pueda gatear por paquete."
        )
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GateConfigError(f"el informe {path} no se puede leer: {exc}") from exc


def _pytest_command(*, extra: list[str] | None) -> list[str]:
    cmd = [sys.executable, "-m", "pytest", "--cov", f"--cov-report=json:{JSON_REPORT}"]
    cmd += ["--cov-report=term:skip-covered"]
    cmd += extra or []
    return cmd


def run_pytest(*, extra: list[str] | None = None) -> int:
    return subprocess.call(_pytest_command(extra=extra), cwd=str(ENGINE_ROOT))


def gate(*, report: bool = False, update: bool = False, extra: list[str] | None = None) -> int:
    """Punto de entrada del gate. Devuelve el codigo de salida.

    `report=True` (--report) es SOLO inspeccion: imprime la medicion real y sale
    0 aunque el gate este en rojo. Es lo que se usa para responder "¿cuanto
    cubrimos hoy?" sin que la respuesta sea "el gate fallo". El gate de verdad es
    la invocacion sin banderas, que es la que usa CI.
    """
    try:
        baseline = load_baseline()
    except GateConfigError as exc:
        # Bootstrap: --update-baseline sobre un repo que aun no tiene linea
        # base tiene que funcionar, o el primer uso del gate es imposible.
        # load_baseline() sigue siendo estricto para el resto de invocaciones.
        if update and not BASELINE_PATH.is_file():
            print(
                "No hay baseline todavia: se genera uno desde esta medicion. "
                "REVISALO A MANO antes de commitearlo (un baseline automatico "
                "hereda el estado real, incluidos los huecos que nadie ha visto).",
                file=sys.stderr,
            )
            baseline = {
                "version": BASELINE_VERSION,
                "measurement": {"total": 0.0, "statements": 0},
                "policy": {"max_drop_points": 0.0},
                "exempt": [],
                "packages": {},
                "_default_drop": 0.0,
                "_exempt": set(),
            }
        else:
            print(f"GATE ERROR: {exc}", file=sys.stderr)
            return 1

    code = run_pytest(extra=extra)
    # La cobertura se evalua SIEMPRE, tambien con pytest en rojo. Gatear la
    # medicion sobre "los tests pasaron" haria que un fallo de suite dejara el
    # gate ciego, que es justo cuando mas falta ver si la cobertura se movio.
    # El codigo de pytest se reporta igual y hace fallar el gate al final.
    if code != 0:
        print(
            f"\nAVISO: pytest termino con codigo {code}. Se evalua la cobertura de todos "
            f" modos, pero el gate quedara en FALLO por los tests, no por la cobertura.",
            file=sys.stderr,
        )

    try:
        report_json = _load_json_report(JSON_REPORT)
        packages = aggregate_by_package(report_json)
    except GateConfigError as exc:
        print(f"GATE ERROR: {exc}", file=sys.stderr)
        return code or 1

    if not packages:
        print("GATE ERROR: la medicion no contiene ningun paquete.", file=sys.stderr)
        return code or 1

    if update:
        payload = render_baseline(
            packages,
            float(baseline["policy"].get("max_drop_points", 0.0)),
            list(baseline.get("exempt", [])),
        )
        BASELINE_PATH.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        print(f"baseline actualizado: {BASELINE_PATH}")
        print(
        format_report(
            evaluate(packages, baseline),
            title="Informe (pre-actualizacion)",
            exempt=baseline.get("exempt", []),
        )
    )
        return 0

    result = evaluate(packages, baseline)
    print(
        format_report(
            result,
            title="Cobertura data-engine (branch=True)",
            exempt=baseline.get("exempt", []),
        )
    )
    if report:
        # --report es inspeccion: responde "¿cuanto cubrimos hoy?" y sale 0.
        if code != 0:
            print(f"\n(recordatorio: pytest devolvio {code}; --report no gatea)")
        return 0
    if not result.ok:
        return 1
    return code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Mide la cobertura de data-engine y falla si baja del umbral."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--report",
        action="store_true",
        help="solo imprime la medicion; el fallo de pytest sigue contando, el gate tambien",
    )
    mode.add_argument(
        "--update-baseline",
        action="store_true",
        help="reescribe coverage_baseline.json con la medicion actual (revisala a mano)",
    )
    parser.add_argument(
        "pytest_args",
        nargs=argparse.REMAINDER,
        help="argumentos extra para pytest, p.ej. -m 'not services'",
    )
    args = parser.parse_args(argv)
    extra = [a for a in (args.pytest_args or []) if a != "--"]
    return gate(report=args.report, update=args.update_baseline, extra=extra)


if __name__ == "__main__":
    sys.exit(main())
