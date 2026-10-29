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
            "tests/test_mutation_gaps_dca_service.py",
            "tests/test_mutation_gaps_dca_fetch.py",
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
            "tests/test_mutation_gaps_modelo720_cash.py",
            "tests/test_tax_modelo720_cash_zero_flag.py",
            "tests/test_tax_spanish_filing.py",
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
            # Ronda 2: suites que ejercitan este modulo y faltaban en la lista.
            "tests/test_corporate_actions_split_scope.py",
            "tests/test_export_csv_control.py",
            "tests/test_tax_dgt_sale_fx.py",
            "tests/test_tax_fifo_deferred_base_fx.py",
            "tests/test_tax_fifo_differential.py",
            "tests/test_tax_oversell_wash_deferral.py",
            "tests/test_taxes_routes.py",
            "tests/test_mutation_gaps_tax_report_helpers.py",
            "tests/test_mutation_gaps_tax_filing.py",
            # Ronda 3: suites nuevas desde el 28-oct que ejercitan el modulo.
            "tests/test_currency_ledger.py",
            "tests/test_currency_ledger_by_currency.py",
            "tests/test_ibkr_fx_conversions.py",
            "tests/test_tax_cancelled_lot_review.py",
            "tests/test_tax_report_versioning.py",
            "tests/test_tax_sale_fx_cost_characterization.py",
            "tests/test_mutation_gaps_tax_report_r3.py",
            "tests/test_mutation_gaps_sale_simulation.py",
        ],
    ),
    "price_units": (
        "app/services/price_units.py",
        [
            "tests/test_listing_currency.py",
            "tests/test_quote_unit_consumers.py",
            "tests/test_portfolio_minor_currency_unit.py",
            "tests/test_mutation_gaps_units.py",
            "tests/test_lse_paris_quote_currency.py",
            "tests/test_price_units_same_major_unit.py",
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
            "tests/test_mutation_gaps_portfolio_fx.py",
            "tests/test_mutation_gaps_portfolio_fx_r3.py",
        ],
    ),
    "sale_simulation": (
        "app/services/sale_simulation.py",
        [
            "tests/test_chat_sale_audit_regressions.py",
            "tests/test_tax_sale_fx_cost_characterization.py",
            "tests/test_mutation_gaps_sale_simulation.py",
        ],
    ),
    "paper_cost_service": (
        "app/services/paper_cost_service.py",
        [
            "tests/test_paper_costs.py",
            "tests/test_paper_costs_calibration_edges.py",
            "tests/test_paper_corporate_actions.py",
            "tests/test_paper_corporate_actions_edges.py",
            "tests/test_paper_trading_service_edges.py",
            "tests/test_mutation_gaps_paper_costs.py",
            "tests/test_mutation_gaps_paper_trading.py",
        ],
    ),
    "paper_trading_service": (
        "app/services/paper_trading_service.py",
        [
            "tests/test_paper_trading.py",
            "tests/test_paper_trading_service_edges.py",
            "tests/test_paper_costs.py",
            "tests/test_paper_corporate_actions.py",
            "tests/test_paper_corporate_actions_edges.py",
            "tests/test_paper_api_limit_messages.py",
            "tests/test_paper_thesis_anchor.py",
            "tests/test_llm_proposal_service.py",
            "tests/test_paper_scoreboard_bins_corporate_action.py",
            "tests/test_mutation_gaps_paper_trading.py",
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


SCOPED_RUNNER = """\
# Generado por run_mutmut.py --lines: lanza mutmut limitando las lineas mutables.
import sys

from mutmut.mutation import file_mutation, pragma_handling

TARGET, FIRST, LAST = {target!r}, {first}, {last}
_original = pragma_handling.get_ignored_lines


def _scoped(filename, source, *args, **kwargs):
    ignored = _original(filename, source, *args, **kwargs)
    if str(filename).replace("\\\\", "/").endswith(TARGET):
        total = source.count("\\n") + 1
        ignored.no_mutate_lines |= {{n for n in range(1, total + 1) if n < FIRST or n > LAST}}
    return ignored


pragma_handling.get_ignored_lines = _scoped
file_mutation.get_ignored_lines = _scoped

from mutmut.__main__ import cli  # noqa: E402

sys.exit(cli())
"""


def _write_scoped_runner(workdir: Path, target: str, first: int, last: int) -> Path:
    """Runner de mutmut que solo muta las lineas ``first..last`` de ``target``.

    Para modulos con funciones enormes (``compute_report``: ~530 lineas, >1.100
    mutantes) mutmut genera una copia de la funcion entera por mutante y el fichero
    resultante pasa de 700.000 lineas: no termina. Acotar por tramos de lineas lo
    reparte en pasadas pequenas. No toca el codigo: anade las lineas fuera del tramo
    a las ignoradas por mutmut (como un ``# pragma: no mutate``) en el proceso que
    genera los mutantes; los hijos se crean con fork y heredan el parche.
    """
    runner = workdir / "_mutmut_scoped.py"
    runner.write_text(SCOPED_RUNNER.format(target=target, first=first, last=last), encoding="utf-8")
    return runner


def statement_chunks(path: Path, max_lines: int) -> list[tuple[int, int]]:
    """Parte el fichero en tramos de ~``max_lines`` cortando solo en inicios de sentencia.

    Los cortes validos son sentencias (a cualquier profundidad) que no sean ``elif``
    ni lineas con decoradores: cada tramo empieza en una sentencia completa y el
    informe de supervivientes se lee por bloques con sentido.
    """
    import ast

    source = path.read_text(encoding="utf-8")
    src_lines = source.splitlines()
    tree = ast.parse(source)
    starts: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.stmt):
            continue
        line = node.lineno
        if getattr(node, "decorator_list", None):
            line = min(d.lineno for d in node.decorator_list)
        text = src_lines[line - 1].lstrip()
        if text.startswith(("elif ", "elif(")):
            continue
        starts.add(line)
    # Las sentencias de primer nivel del modulo que no son funciones ni clases
    # (imports, constantes) no generan mutantes utiles: empieza en la primera def.
    first_def = min(
        (n.lineno if not n.decorator_list else min(d.lineno for d in n.decorator_list))
        for n in tree.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    )
    cuts = sorted(s for s in starts if s >= first_def)
    chunks: list[tuple[int, int]] = []
    begin = cuts[0]
    for cut in cuts[1:]:
        if cut - begin >= max_lines:
            chunks.append((begin, cut - 1))
            begin = cut
    chunks.append((begin, len(src_lines)))
    return chunks


def prepare(
    target: str,
    workdir: Path,
    deselect: list[str] | None = None,
    lines: tuple[int, int] | None = None,
) -> None:
    src, tests = TARGETS[target]
    pytest_args = ["-p", "no:cacheprovider", "-q", "-x", "-W", "ignore"]
    for node_id in deselect or []:
        pytest_args += ["--deselect", node_id]
    for rel in _tracked_files():
        dest = workdir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / rel, dest)
    if lines is not None:
        _write_scoped_runner(workdir, src, *lines)
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
    parser.add_argument(
        "--lines",
        help="muta solo el tramo A-B del fichero (para funciones enormes; ver --chunks)",
    )
    parser.add_argument(
        "--chunks",
        type=int,
        metavar="N",
        help="imprime tramos de ~N lineas validos para --lines y sale",
    )
    args = parser.parse_args()
    if args.target and args.chunks:
        for first, last in statement_chunks(ROOT / TARGETS[args.target][0], args.chunks):
            print(f"{first}-{last}")
        return 0
    line_range: tuple[int, int] | None = None
    if args.lines:
        first_s, _, last_s = args.lines.partition("-")
        line_range = (int(first_s), int(last_s))
    if args.list or not args.target:
        for name, (src, tests) in sorted(TARGETS.items()):
            print(f"{name:28} {src}  ({len(tests)} ficheros de test)")
        return 0
    workdir = Path(tempfile.mkdtemp(prefix=f"mutmut-{args.target}-{args.lines or 'all'}-"))
    try:
        prepare(args.target, workdir, args.deselect, line_range)
        command = [MUTMUT]
        if line_range is not None:
            command = [sys.executable, str(workdir / "_mutmut_scoped.py")]
        run = subprocess.run(
            [*command, "run", "--max-children", str(args.max_children)],
            cwd=workdir,
        )
        found = results(workdir)
        counts = collections.Counter(found.values())
        total = sum(counts.values())
        killed = counts.get("killed", 0)
        score = 100.0 * killed / total if total else 0.0
        scope = f" [{args.lines}]" if args.lines else ""
        print(f"\n{args.target}{scope}: {killed}/{total} mutantes matados = {score:.1f} % {dict(counts)}")
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
