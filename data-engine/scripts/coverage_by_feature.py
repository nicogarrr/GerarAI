"""Cobertura de data-engine POR FUNCIONALIDAD (informativo, nunca falla).

El gate de `run_coverage_gate.py` mide por PAQUETE (app/services, app/api/routes...).
Eso no dice si una funcionalidad concreta (impuestos, DCA, cartera...) esta bien
probada: app/services mezcla 300 modulos. Este script agrupa los ficheros de
`htmlcov/coverage.json` por funcionalidad de producto y lista, para cada una,
el % de sentencias+ramas y los ficheros con mas lineas sin cubrir.

    python scripts/coverage_by_feature.py                 # tabla en texto
    python scripts/coverage_by_feature.py --markdown      # para $GITHUB_STEP_SUMMARY
    python scripts/coverage_by_feature.py --json out.json # volcado para comparar

Sale SIEMPRE con 0: es un informe, no un gate (el gate es run_coverage_gate.py).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ENGINE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_JSON = ENGINE_ROOT / "htmlcov" / "coverage.json"

# Orden = prioridad: el primer patron que encaja se queda el fichero.
FEATURES: list[tuple[str, str]] = [
    ("impuestos (IRPF/720)", r"app/(api/routes/taxes|services/tax_|services/sale_(simulation|hypothetical))"),
    ("DCA", r"app/services/dca_|app/services/entry_level_alerts"),
    ("cartera/tearsheet", r"app/(api/routes/portfolio|services/(portfolio_|tearsheet|ibkr_|fx_attribution|dividend_|plan_contribution|historical_stress|split_adjustment))"),
    ("divisa base/FX/unidades", r"app/(services/(price_units|number_format|number_parsing)|core/units)"),
    ("watchlist", r"app/(api/routes/watchlist|services/(watchlist|extended_quote|market_close_sync))"),
    ("alertas", r"app/(api/routes/alerts|services/(alert_|outbound_alerts|notification_|review_alert|insider_alerts|tracked_news_alerts|daily_digest_alerts|email_delivery))"),
    ("tesis", r"app/(api/routes/thesis|services/thesis_)"),
    ("Cerebro/chat", r"app/(api/routes/(chat|research_assistant|memory)|services/(chat_|brain_|personal_answer|research_assistant|memory_|user_context|read_tool_registry|llm_))"),
    ("biblioteca/conocimiento", r"app/(api/routes/knowledge|services/(knowledge_|library_|document_|corpus_|hybrid_retrieval|rag))"),
    ("ficha/valoracion", r"app/(api/routes/(companies|valuation|company_events|earnings|financial|filing_intelligence)|services/(company_|valuation_|fair_value|long_term_model|wacc_|financial_|ttm_|peer_|moat_|driver_)|valuation/)"),
    ("ajustes/privacidad", r"app/(api/routes/(settings|privacy|telegram_link)|services/(privacy_|tenant_llm_settings|telegram_link|retention_))"),
    ("auth/tenancy", r"app/(core/(auth|tenancy|llm_tenant_scope|rate_limit|llm_settings_crypto)|api/deps)"),
]
OTHER = "resto"


def classify(path: str) -> str:
    for name, pattern in FEATURES:
        if re.search(pattern, path):
            return name
    return OTHER


def _pct(covered: int, total: int) -> float:
    return 100.0 if total == 0 else round(100.0 * covered / total, 2)


def summarize(data: dict) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for path, info in data.get("files", {}).items():
        if not path.startswith("app/"):
            continue
        s = info["summary"]
        f = out.setdefault(classify(path), {"statements": 0, "covered": 0, "branches": 0,
                                             "covered_branches": 0, "files": []})
        f["statements"] += s["num_statements"]
        f["covered"] += s["covered_lines"]
        f["branches"] += s.get("num_branches", 0)
        f["covered_branches"] += s.get("covered_branches", 0)
        f["files"].append({
            "path": path,
            "percent": round(s["percent_covered"], 2),
            "missing_lines": s["missing_lines"],
            "missing_branches": s.get("missing_branches", 0),
        })
    for f in out.values():
        f["percent"] = _pct(f["covered"] + f["covered_branches"], f["statements"] + f["branches"])
        f["percent_lines"] = _pct(f["covered"], f["statements"])
        f["percent_branches"] = _pct(f["covered_branches"], f["branches"])
        f["files"].sort(key=lambda r: -(r["missing_lines"] + r["missing_branches"]))
    return out


def render(summary: dict[str, dict], markdown: bool, top: int) -> str:
    order = [n for n, _ in FEATURES] + [OTHER]
    rows = [(n, summary[n]) for n in order if n in summary]
    lines: list[str] = []
    if markdown:
        lines += ["### Cobertura backend por funcionalidad (informativo)", "",
                  "| Funcionalidad | Total | Lineas | Ramas | Ficheros con mas hueco |",
                  "|---|---:|---:|---:|---|"]
        for n, f in rows:
            worst = ", ".join(f"`{Path(r['path']).name}` ({r['percent']}%)" for r in f["files"][:top]
                              if r["missing_lines"] + r["missing_branches"])
            lines.append(f"| {n} | {f['percent']}% | {f['percent_lines']}% | {f['percent_branches']}% | {worst} |")
    else:
        for n, f in rows:
            lines.append(f"{n:<26} total {f['percent']:6.2f}%  lineas {f['percent_lines']:6.2f}%  ramas {f['percent_branches']:6.2f}%")
            for r in f["files"][:top]:
                if r["missing_lines"] + r["missing_branches"]:
                    lines.append(f"    {r['percent']:6.2f}%  -{r['missing_lines']}l/-{r['missing_branches']}r  {r['path']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--input", type=Path, default=DEFAULT_JSON)
    ap.add_argument("--markdown", action="store_true")
    ap.add_argument("--json", type=Path)
    ap.add_argument("--top", type=int, default=3)
    a = ap.parse_args(argv)
    if not a.input.exists():
        print(f"(sin {a.input}: no hay medicion que resumir)")
        return 0
    summary = summarize(json.loads(a.input.read_text(encoding="utf-8")))
    print(render(summary, a.markdown, a.top))
    if a.json:
        a.json.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
