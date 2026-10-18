"""Genera snapshots ESEF (xBRL-JSON normalizado) para emisores IBEX reviewed.

Fuente: filings.xbrl.org (indice ESEF de XBRL International, gratuito, sin key).
Para cada LEI con filings ES se toman los N filings mas recientes con json_url
(--max-filings, por defecto 5: historia real de ~5 ejercicios) y se normalizan
a un layout tipo companyfacts, fusionando con dedup por (concepto, unidad,
start, end): ante reexpresiones gana el filing mas reciente. Solo se construyen
snapshots de emisores cuyo nombre legal resuelve contra la tabla REVIEWED de
cnmv_mapping: ningun ticker se asigna por aproximacion; los no resueltos quedan
listados en el manifest como "unresolved", nunca inventados.

Uso:
    python scripts/build_esef_snapshots.py --out data/esef_snapshots \
        --country ES --fetched-at 2026-09-24

Manifest: {"issuers": {LEI: {ticker, entity_name, period_end, fxo_id, sha256}},
           "unresolved": {LEI: entity_name}, "fetched_at": ..., "source": ...}
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from app.services.connectors.esef import (
    EsefClient,
    EsefError,
    EsefFiling,
    normalize_xbrl_json,
)
from app.services.esef_issuer_mapping import resolve_ticker_for_country

SOURCE = "filings.xbrl.org (XBRL International ESEF filing index), xBRL-JSON render"


def latest_filing_per_lei(filings: list[EsefFiling]) -> dict[str, EsefFiling]:
    """Un filing por LEI: el de period_end mas reciente que tenga json_url."""
    best: dict[str, EsefFiling] = {}
    for f in sorted(filings, key=lambda x: x.period_end or ""):
        if not f.json_url:
            continue
        best[f.lei] = f  # sorted ascending: last write wins = latest period
    return best


def filings_per_lei(filings: list[EsefFiling], max_filings: int = 5) -> dict[str, list[EsefFiling]]:
    """Hasta max_filings filings por LEI: period_end distintos, mas reciente
    primero, solo con json_url. La historia de 5y de las metricas windowed
    sale de aqui; sin filings antiguos esas metricas quedan honestamente
    insufficient_history."""
    selected: dict[str, list[EsefFiling]] = {}
    for f in sorted(filings, key=lambda x: x.period_end or "", reverse=True):
        if not f.json_url:
            continue
        chosen = selected.setdefault(f.lei, [])
        if len(chosen) >= max_filings or any(c.period_end == f.period_end for c in chosen):
            continue
        chosen.append(f)
    return selected


def merge_facts(normalized_docs: list[dict]) -> dict:
    """Fusiona facts normalizados de varios filings (mas reciente primero).
    Dedup por (concepto, unidad, start, end|instant): el filing mas reciente
    gana porque recoge las reexpresiones.

    OJO con los instantes (balance): su periodo es solo "instant", sin
    start/end. Si la clave no lo incluye, TODOS los instantes de un concepto
    colapsan en uno solo y el balance queda con un unico ejercicio (bug
    detectado 2026-09-25: total_assets/total_equity con 1 solo ano en BD
    pese a tener 6 anos de filings).

    La clave incluye las dimensiones (dims). Un desglose por miembro
    (ifrs-full:SegmentAxis) comparte concepto, unidad y periodo con el
    consolidado, asi que sin `dims` en la clave un miembro podia ocupar el
    sitio del consolidado segun el orden del JSON. `refresh_from_esef` descarta
    las entradas con dims, de modo que el consolidado se perdia y el ejercicio
    desaparecia entero de la serie, sin aviso."""
    merged: dict = {}
    seen: set = set()
    for facts in normalized_docs:
        for concept, units in facts.items():
            for unit, entries in units.items():
                bucket = merged.setdefault(concept, {}).setdefault(unit, [])
                for entry in entries:
                    key = (
                        concept,
                        unit,
                        entry.get("start"),
                        entry.get("end") or entry.get("instant"),
                        tuple(entry.get("dims") or ()),
                    )
                    if key in seen:
                        continue
                    seen.add(key)
                    bucket.append(entry)
    return merged


async def build(out: Path, countries: str | list[str], fetched_at: str, client: EsefClient, max_filings: int = 5) -> dict:
    """Snapshots ESEF para uno o varios paises (p.ej. ["ES", "NL"]) en un
    unico manifest: correr paises por separado sobrescribia el manifest y
    dejaba solo el ultimo pais. Cada pais resuelve contra SU tabla
    reviewed (CNMV para ES, AFM/ESEF para NL)."""
    if isinstance(countries, str):
        countries = [countries]
    selected: dict[str, list[EsefFiling]] = {}
    for country in countries:
        filings = await client.list_all_filings(country)
        for lei, issuer_filings in filings_per_lei(filings, max_filings).items():
            selected.setdefault(lei, []).extend(issuer_filings)
    (out / "snapshots").mkdir(parents=True, exist_ok=True)

    issuers: dict[str, dict] = {}
    unresolved: dict[str, str] = {}
    for lei, issuer_filings in sorted(selected.items()):
        issuer_filings.sort(key=lambda f: f.period_end or "", reverse=True)
        country = issuer_filings[0].country
        try:
            name = await client.get_entity_name(lei)
        except EsefError:
            name = ""
        ticker = resolve_ticker_for_country(country, name) if name else None
        if ticker is None:
            unresolved[lei] = name or "<entity lookup failed>"
            continue
        normalized_docs = []
        for filing in issuer_filings:
            doc = await client.fetch_filing_json(filing)
            normalized_docs.append(normalize_xbrl_json(doc))
        facts = merge_facts(normalized_docs)
        latest = issuer_filings[0]
        periods = [f.period_end for f in issuer_filings]
        payload = {
            "lei": lei,
            "ticker": ticker,
            "entity_name": name,
            "period_end": latest.period_end,
            "periods": periods,
            "fxo_id": latest.fxo_id,
            "sha256": latest.sha256,
            "fetched_at": fetched_at,
            "facts": facts,
        }
        path = out / "snapshots" / f"{lei}.json"
        path.write_text(json.dumps(payload))
        issuers[lei] = {
            "ticker": ticker,
            "entity_name": name,
            "period_end": latest.period_end,
            "periods": periods,
            "fxo_id": latest.fxo_id,
            "sha256": latest.sha256,
        }
        n = sum(len(u) for c in facts.values() for u in c.values())
        print(f"{ticker} ({name}): {len(facts)} conceptos, {n} entradas, {len(periods)} filings, period {latest.period_end} -> {path}")

    manifest = {
        "issuers": dict(sorted(issuers.items())),
        "unresolved": dict(sorted(unresolved.items())),
        "countries": countries,
        "fetched_at": fetched_at,
        "source": SOURCE,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1, ensure_ascii=False))
    print(f"manifest -> {out / 'manifest.json'} ({len(issuers)} issuers, {len(unresolved)} unresolved)")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--country", action="append", default=None,
                        help="Pais ESEF a construir (repetible; por defecto ES).")
    parser.add_argument("--fetched-at", required=True, help="Fecha de captura (provenance).")
    parser.add_argument("--max-filings", type=int, default=5,
                        help="Filings mas recientes por emisor (historia ~5 ejercicios).")
    args = parser.parse_args()
    asyncio.run(build(Path(args.out), args.country or ["ES"], args.fetched_at, EsefClient(), args.max_filings))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
