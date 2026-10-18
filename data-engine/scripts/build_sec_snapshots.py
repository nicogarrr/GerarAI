"""Genera snapshots EDGAR (formato companyfacts oficial) desde el parquet
espejo de HuggingFace (DenyTranDFW/edgar_xbrl_companyfacts), para el modo
snapshot del conector (SEC_SNAPSHOT_DIR). La SEC bloquea IPs de datacenter;
el espejo replica el companyfacts oficial (validado fila a fila contra la
API directa para AAPL FY25: revenue/OCF/capex identicos).

Uso:
    python scripts/build_sec_snapshots.py --parquet /tmp/usgaap.parquet \
        --out data/sec_snapshots TICKER:CIK [TICKER:CIK ...]

Manifest: {"tickers": {T: cik10}, "fetched_at": <fecha del parquet>,
           "source": "..."} - la procedencia queda declarada, nunca implicita.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import polars as pl
from sec_snapshot_values import entry_value

# Sincronizada con SEC_METRIC_MAP de financial_ingestion_service: un concepto
# mapeado que falte aqui deja su metrica sin cobertura en el universo (B-share:
# las recompras/emisiones/SBC nunca llegaron a los ~2.012 snapshots porque la
# lista los omitia; UNH salia N/D en dilucion teniendolo todo reportado).
CONCEPTS = [
    "Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax",
    "SalesRevenueNet", "RevenueFromContractWithCustomerIncludingAssessedTax",
    "RegulatedAndUnregulatedOperatingRevenue",
    "GrossProfit", "OperatingIncomeLoss",
    "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
    "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
    "IncomeLossFromContinuingOperationsBeforeIncomeTaxesDomesticAndForeign",
    "IncomeTaxExpenseBenefit", "InterestExpenseNonoperating",
    "InterestExpenseNonOperating", "InterestExpense", "InterestExpenseDebt",
    "InterestExpenseLongTermDebt", "InterestAndDebtExpense",
    "NetIncomeLoss", "ProfitLoss",
    "EarningsPerShareDiluted", "WeightedAverageNumberOfDilutedSharesOutstanding",
    "WeightedAverageNumberOfSharesOutstandingBasic",
    "CommonStockSharesOutstanding", "CommonStockSharesIssued",
    "CashAndCashEquivalentsAtCarryingValue",
    "CashCashEquivalentsAndShortTermInvestments", "LongTermDebt",
    "LongTermDebtNoncurrent", "DebtLongtermAndShorttermCombinedAmount",
    "LongTermDebtAndCapitalLeaseObligations",
    "Assets", "Liabilities", "StockholdersEquity",
    "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    "Goodwill", "FiniteLivedIntangibleAssetsNet",
    "IndefiniteLivedIntangibleAssetsExcludingGoodwill",
    "OperatingLeaseLiability", "OperatingLeaseLiabilityNoncurrent",
    "NetCashProvidedByUsedInOperatingActivities",
    "PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets",
    "DepreciationDepletionAndAmortization", "DepreciationAmortizationAndAccretionNet",
    "Depreciation", "DepreciationAndAmortization",
    "PaymentsOfDividends", "PaymentsOfDividendsCommonStock",
    # Capital: recompras, emisiones y SBC (flujos con start; requieren el
    # campo `start` conservado abajo para pasar require_start de la ingesta).
    "PaymentsForRepurchaseOfCommonStock", "StockRepurchasedDuringPeriodShares",
    "StockRepurchasedDuringPeriodValue", "ProceedsFromIssuanceOfCommonStock",
    "StockIssuedDuringPeriodValueNewIssues", "ShareBasedCompensation",
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--parquet", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--fetched-at", required=True,
                        help="Fecha de los datos del espejo (provenance).")
    parser.add_argument("--dei-parquet", default=None,
                        help="Parquet dei (portada) con EntityCommonStockSharesOutstanding.")
    parser.add_argument("targets", nargs="+", help="TICKER:CIK (cik a 10 o sin padding)")
    args = parser.parse_args()

    out = Path(args.out)
    (out / "companyfacts").mkdir(parents=True, exist_ok=True)

    targets: dict[str, str] = {}
    for raw in args.targets:
        ticker, cik = raw.split(":")
        targets[ticker.strip().upper()] = cik.strip().zfill(10)

    # start/accn son carga util, no decoracion: sin `start` la ingesta no
    # puede verificar duraciones ni admitir flujos (require_start) y sin
    # `accn` no puede anclar cada hecho anual a su filing 10-K. El parquet
    # fuente los trae; el builder anterior los tiraba.
    df = pl.scan_parquet(args.parquet).filter(
        pl.col("item").is_in(CONCEPTS),
        pl.col("source_folder").str.extract(r"CIK(\d{10})").is_in(
            list(targets.values())
        ),
    ).select("item", "start", "end", "fy", "fp", "form", "filed", "accn",
             "frame", "unit_type", "val_dec", "source_folder").collect()

    # dei (portada): acciones en circulacion, namespace separado de us-gaap.
    # Sin este parquet los snapshots no llevan shares_outstanding y la pagina
    # de capital/dilucion sale N/D aun con todo lo demas reportado.
    dei_rows: dict[str, list[dict]] = {}
    if args.dei_parquet:
        q = pl.scan_parquet(args.dei_parquet)
        # El parquet puede traer varios conceptos dei (columna item) o venir
        # prefiltrado a EntityCommonStockSharesOutstanding.
        if "item" in q.collect_schema().names():
            q = q.filter(pl.col("item") == "EntityCommonStockSharesOutstanding")
        dei_df = q.filter(
            pl.col("source_folder").str.extract(r"CIK(\d{10})").is_in(
                list(targets.values())
            ),
        ).select("end", "fy", "fp", "form", "filed", "accn", "frame",
                 "val_dec", "source_folder").collect()
        for row in dei_df.iter_rows(named=True):
            m = re.search(r"CIK(\d{10})", row["source_folder"] or "")
            if m:
                dei_rows.setdefault(m.group(1), []).append(row)

    for ticker, cik in targets.items():
        sub = df.filter(pl.col("source_folder").str.starts_with(f"CIK{cik}"))
        us_gaap: dict[str, dict] = {}
        for row in sub.iter_rows(named=True):
            concept = us_gaap.setdefault(row["item"], {"units": {}})
            unit = row["unit_type"] or "USD"
            entry = {
                "end": row["end"], "fy": int(row["fy"]) if row["fy"] else None,
                "fp": row["fp"], "form": row["form"], "filed": row["filed"],
                "val": entry_value(row["val_dec"]),
            }
            if row["start"]:
                entry["start"] = row["start"]
            if row["accn"]:
                entry["accn"] = row["accn"]
            if row["frame"]:
                entry["frame"] = row["frame"]
            concept["units"].setdefault(unit, []).append(entry)
        dei: dict[str, dict] = {}
        for row in dei_rows.get(cik, []):
            concept = dei.setdefault(
                "EntityCommonStockSharesOutstanding", {"units": {}})
            entry = {
                "end": row["end"], "fy": int(row["fy"]) if row["fy"] else None,
                "fp": row["fp"], "form": row["form"], "filed": row["filed"],
                "val": entry_value(row["val_dec"]),
            }
            if row["accn"]:
                entry["accn"] = row["accn"]
            if row["frame"]:
                entry["frame"] = row["frame"]
            concept["units"].setdefault("shares", []).append(entry)
        payload = {
            "cik": int(cik), "entityName": ticker,
            "facts": {"us-gaap": us_gaap, "dei": dei},
        }
        path = out / "companyfacts" / f"CIK{cik}.json"
        path.write_text(json.dumps(payload))
        n = sum(len(u) for c in us_gaap.values() for u in c["units"].values())
        print(f"{ticker}: {len(us_gaap)} conceptos, {n} entradas -> {path}")

    manifest_path = out / "manifest.json"
    existing: dict[str, str] = {}
    if manifest_path.exists():
        try:
            existing = json.loads(manifest_path.read_text()).get("tickers", {})
        except Exception:
            existing = {}
    existing.update(targets)
    manifest = {
        "tickers": dict(sorted(existing.items())),
        "fetched_at": args.fetched_at,
        "source": "HuggingFace mirror of SEC EDGAR companyfacts "
                  "(DenyTranDFW/edgar_xbrl_companyfacts), validado contra API directa",
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1))
    print("manifest ->", out / "manifest.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
