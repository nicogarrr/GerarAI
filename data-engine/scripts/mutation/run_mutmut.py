"""Mutation testing (mutmut) por modulo, acotado y reproducible.

Uso (desde data-engine/, con el venv del proyecto y ``pip install mutmut``):

    python scripts/mutation/run_mutmut.py dca_signal_engine
    python scripts/mutation/run_mutmut.py --list
    python scripts/mutation/run_mutmut.py currency --max-children 4 --survivors

Que hace: copia los ficheros versionados a un directorio temporal, escribe ahi
un ``[tool.mutmut]`` que muta SOLO el modulo elegido y corre SOLO sus tests
relacionados (asi cada modulo termina en minutos y no toca el arbol de
trabajo), ejecuta ``mutmut run`` e imprime la puntuacion: mutantes matados /
total. Los ``survived`` son cambios del codigo que ningun test detecta.

No es un gate de CI: se lanza a mano (workflow_dispatch ``mutation.yml``).
Ver docs/testing/mutation.md.
"""

from __future__ import annotations

import argparse
import collections
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # data-engine/

# modulo -> (fichero a mutar, tests que lo ejercitan). Los tests
# ``test_mutation_gaps_*`` son los que se anadieron al revisar supervivientes.
TARGETS: dict[str, tuple[str, list[str]]] = {
    "dca_signal_engine": (
        "app/services/dca_signal_engine.py",
        [
            "tests/test_dca_signal_engine.py",
            "tests/test_dca_backtest.py",
            "tests/test_dca_level_provider.py",
            "tests/test_dca_signal_service.py",
            "tests/test_mutation_gaps_dca_engine.py",
        ],
    ),
    "dca_signal_service": (
        "app/services/dca_signal_service.py",
        [
            "tests/test_dca_signal_service.py",
            "tests/test_alert_event_dca_loss_regressions.py",
            "tests/test_dca_actor_scheduler.py",
            "tests/test_dca_signals_api.py",
        ],
    ),
    "tax_irpf_filing": (
        "app/services/tax_irpf_filing.py",
        [
            "tests/test_golden_portfolio_tax.py",
            "tests/test_tax_interest_0027.py",
            "tests/test_tax_irpf_filing.py",
            "tests/test_tax_loss_carry_estimate.py",
            "tests/test_tax_savings_bands_history.py",
            "tests/test_tax_treaty_ca.py",
            "tests/test_tax_treaty_cn_gb.py",
            "tests/test_tax_spanish_filing.py",
            "tests/test_tax_declarant.py",
            "tests/test_mutation_gaps_irpf_losses.py",
            "tests/test_mutation_gaps_irpf_double_tax.py",
        ],
    ),
    "tax_modelo720_service": (
        "app/services/tax_modelo720_service.py",
        [
            "tests/test_tax_modelo720_q4.py",
            "tests/test_tax_modelo720_service.py",
            "tests/test_tax_modelo720_file.py",
        ],
    ),
    "tax_report_service": (
        "app/services/tax_report_service.py",
        [
            "tests/test_audit_hardening.py",
            "tests/test_chat_sale_audit_regressions.py",
            "tests/test_divisa_base.py",
            "tests/test_money_path_contracts.py",
            "tests/test_personal_finance.py",
            "tests/test_portfolio_fifo_reconciliation.py",
            "tests/test_portfolio_fx_service.py",
            "tests/test_tax_cash_row_convention.py",
            "tests/test_tax_fx_bce_fecha.py",
            "tests/test_tax_interest_0027.py",
            "tests/test_tax_irpf_filing.py",
            "tests/test_tax_report_service.py",
            "tests/test_tax_spanish_filing.py",
            "tests/test_tax_wash_sale_eur.py",
            "tests/test_tax_wash_sale_manual.py",
            "tests/test_withholding_reversal_sign.py",
        ],
    ),
    "price_units": (
        "app/services/price_units.py",
        [
            "tests/test_listing_currency.py",
            "tests/test_quote_unit_consumers.py",
            "tests/test_portfolio_minor_currency_unit.py",
            "tests/test_mutation_gaps_units.py",
        ],
    ),
    "units": (
        "app/core/units.py",
        [
            "tests/test_units_to_fraction.py",
            "tests/test_listing_currency.py",
            "tests/test_mutation_gaps_units.py",
        ],
    ),
    "fx_attribution": (
        "app/services/fx_attribution.py",
        [
            "tests/test_divisa_base.py",
            "tests/test_mutation_gaps_units.py",
        ],
    ),
    "thesis_publication_gate": (
        "app/services/thesis_publication_gate.py",
        [
            "tests/test_thesis_publication_gate_current.py",
            "tests/test_thesis_export_publication_gate.py",
            "tests/test_thesis_api_publication_gate.py",
            "tests/test_chat_thesis_publication_gate.py",
            "tests/test_thesis_debate_publication_gate.py",
            "tests/test_fair_value_publication_gate.py",
            "tests/test_mutation_gaps_thesis_gate.py",
        ],
    ),
    "currency": (
        "app/valuation/currency.py",
        [
            "tests/test_listing_currency.py",
            "tests/test_portfolio_minor_currency_unit.py",
            "tests/test_quote_unit_consumers.py",
            "tests/test_valuation_currency_golden.py",
            "tests/test_fact_reporting_currency.py",
            "tests/test_valuation_model_price.py",
            "tests/test_portfolio_fx_service.py",
            "tests/test_market_refresh_service.py",
            "tests/test_mutation_gaps_currency.py",
            "tests/test_resolve_fx_minor_units.py",
        ],
    ),
    "portfolio_snapshot_service": (
        "app/services/portfolio_snapshot_service.py",
        [
            "tests/test_p1_financial_intelligence.py",
            "tests/test_performance_regression.py",
            "tests/test_portfolio_fx_service.py",
            "tests/test_portfolio_snapshot_backfill.py",
            "tests/test_portfolio_snapshot_service.py",
            "tests/test_portfolio_snapshot_twr_integrity.py",
            "tests/test_snapshot_recapture_relinks_f363.py",
            "tests/test_mutation_gaps_snapshot.py",
        ],
    ),
    "portfolio_fx_service": (
        "app/services/portfolio_fx_service.py",
        [
            "tests/test_portfolio_fx_service.py",
            "tests/test_portfolio_fx.py",
            "tests/test_portfolio_fx_rate_parity.py",
            "tests/test_divisa_base.py",
            "tests/test_quote_unit_consumers.py",
            "tests/test_portfolio_minor_currency_unit.py",
        ],
    ),
}

MUTMUT = shutil.which("mutmut", path=str(Path(sys.executable).parent)) or "mutmut"

ALSO_COPY = ["main.py", "quantstats", "bridge", "evals", "scripts", "alembic", "alembic.ini"]


def _tracked_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout
    return [p for p in out.split("\0") if p]


def _toml_list(items: list[str]) -> str:
    return "[" + ", ".join(f'"{item}"' for item in items) + "]"


def prepare(target: str, workdir: Path, deselect: list[str] | None = None) -> None:
    src, tests = TARGETS[target]
    pytest_args = ["-p", "no:cacheprovider", "-q", "-x", "-W", "ignore"]
    for node_id in deselect or []:
        pytest_args += ["--deselect", node_id]
    for rel in _tracked_files():
        dest = workdir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / rel, dest)
    config = (
        "\n[tool.mutmut]\n"
        'source_paths = ["app"]\n'
        f"only_mutate = {_toml_list([src])}\n"
        f"also_copy = {_toml_list(ALSO_COPY)}\n"
        f"pytest_add_cli_args = {_toml_list(pytest_args)}\n"
        f"pytest_add_cli_args_test_selection = {_toml_list(tests)}\n"
    )
    with (workdir / "pyproject.toml").open("a", encoding="utf-8") as fh:
        fh.write(config)


def results(workdir: Path) -> dict[str, str]:
    out = subprocess.run(
        [MUTMUT, "results", "--all", "true"],
        cwd=workdir,
        capture_output=True,
        text=True,
    ).stdout
    found = {}
    for line in out.splitlines():
        if "__mutmut_" in line and ": " in line:
            name, status = line.strip().rsplit(": ", 1)
            found[name] = status
    return found


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("target", nargs="?", choices=sorted(TARGETS))
    parser.add_argument("--list", action="store_true", help="lista los modulos configurados")
    parser.add_argument("--max-children", type=int, default=2)
    parser.add_argument("--survivors", action="store_true", help="imprime el diff de cada superviviente")
    parser.add_argument(
        "--deselect",
        action="append",
        default=[],
        help="node id de pytest a excluir (un test rojo en main bloquea la pasada de estadisticas)",
    )
    parser.add_argument("--keep", action="store_true", help="no borra el directorio temporal")
    args = parser.parse_args()
    if args.list or not args.target:
        for name, (src, tests) in sorted(TARGETS.items()):
            print(f"{name:28} {src}  ({len(tests)} ficheros de test)")
        return 0
    workdir = Path(tempfile.mkdtemp(prefix=f"mutmut-{args.target}-"))
    try:
        prepare(args.target, workdir, args.deselect)
        run = subprocess.run(
            [MUTMUT, "run", "--max-children", str(args.max_children)],
            cwd=workdir,
        )
        found = results(workdir)
        counts = collections.Counter(found.values())
        total = sum(counts.values())
        killed = counts.get("killed", 0)
        score = 100.0 * killed / total if total else 0.0
        print(f"\n{args.target}: {killed}/{total} mutantes matados = {score:.1f} % {dict(counts)}")
        if args.survivors:
            for name, status in sorted(found.items()):
                if status in {"survived", "timeout", "no tests"}:
                    subprocess.run([MUTMUT, "show", name], cwd=workdir)
        if args.keep:
            print(f"directorio conservado: {workdir}")
        return run.returncode
    finally:
        if not args.keep:
            shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
