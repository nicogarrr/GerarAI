"""Regresión de la batería de 7 sobre datos reales grabados (UBER, CHTR, UNH,
Basic-Fit, ASTS, PLTR, TSLA).

Cada fixture de ``tests/fixtures/valuation/battery7/<TICKER>.json` lo genera
``scripts/record_battery_fixtures.py`` en la VM, SOLO LECTURA: vuelca las
filas de mercado de la empresa (company, financial_facts, último precio,
calculated_metrics — nunca tenant, inputs declarados ni tesis), reconstruye
un sqlite en memoria con ``load_fixture_into_session`` (este mismo módulo, es
la única fuente de verdad del formato) y corre el motor que enruta el
registry. El test reconstruye ese mismo sqlite, corre el mismo motor y
compara la salida COMPLETA contra la grabada:

- estructura, cadenas y estados: exactos (un N/D grabado sigue siendo N/D);
- números: tolerancia relativa 1e-9 (deriva ARM64/x86 del último dígito,
  mismo criterio que el baseline VM de test_valuation_engines_golden).

Si un PR cambia el resultado de una empresa real de la batería, este test
falla con la ruta exacta del campo. Regenerar con BATTERY_GEN=1 regraba las
salidas desde el código ACTUAL: nunca se commitea una regrabación sobre un
refactor sin revisar el diff campo a campo — es la FAV del auditor por SHA.
Sin fixtures todavía (recorder no corrido en la VM) el test se salta.
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import (
    Base,
    CalculatedMetric,
    Company,
    FinancialFact,
    MarketPrice,
)

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "valuation" / "battery7"
GEN = os.environ.get("BATTERY_GEN") == "1"

#: Tolerancia numérica única de la comparación (ver docstring).
REL = 1e-9
ABS = 1e-12

_COMPANY_FIELDS = (
    "ticker",
    "name",
    "exchange",
    "currency",
    "sector",
    "industry",
    "cik",
    "ir_url",
    "domicile_country",
    "isin",
    "company_type",
    "valuation_model",
    "special_sources",
    "special_risks",
    "factor_tags",
)


def _default(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (set, frozenset)):
        return sorted(value)
    if hasattr(value, "item"):  # escalares numpy
        return value.item()
    raise TypeError(f"not serializable: {type(value)!r}")


def company_to_dict(company: Company) -> dict:
    return {field: getattr(company, field) for field in _COMPANY_FIELDS}


def load_fixture_into_session(db: Session, fixture: dict) -> Company:
    """Reconstruye el sqlite de un fixture. ÚNICA fuente del formato: la usa
    este test y scripts/record_battery_fixtures.py."""
    company = Company(**{f: fixture["company"].get(f) for f in _COMPANY_FIELDS})
    db.add(company)
    db.flush()
    fact_ids: dict[int, int] = {}
    for row in fixture["facts"]:
        old_id = row.get("_id")
        fact = FinancialFact(
            company_id=company.id,
            metric=row["metric"],
            value=Decimal(str(row["value"])),
            unit=row.get("unit", "USD"),
            period=row["period"],
            fiscal_year=row.get("fiscal_year"),
            fiscal_quarter=row.get("fiscal_quarter"),
            source_type=row.get("source_type", "battery7"),
            is_reported=row.get("is_reported", True),
            is_adjusted=row.get("is_adjusted", False),
            confidence=Decimal(str(row.get("confidence", "0.80"))),
            accession_number=row.get("accession_number"),
            filed=date.fromisoformat(row["filed"]) if row.get("filed") else None,
            # Desempate fiel a prod (financial_snapshot ordena created_at DESC).
            created_at=(datetime.fromisoformat(row["created_at"]) if row.get("created_at") else None),
        )
        db.add(fact)
        db.flush()
        if old_id is not None:
            fact_ids[old_id] = fact.id
    price = fixture["price"]
    db.add(
        MarketPrice(
            company_id=company.id,
            date=date.fromisoformat(price["date"]),
            open=Decimal(str(price.get("open", price["close"]))),
            high=Decimal(str(price.get("high", price["close"]))),
            low=Decimal(str(price.get("low", price["close"]))),
            close=Decimal(str(price["close"])),
            adj_close=Decimal(str(price["adj_close"])) if price.get("adj_close") is not None else None,
            volume=price.get("volume"),
            quote_currency=price.get("quote_currency"),
            source=price.get("source", "battery7"),
        )
    )
    for row in fixture.get("calculated_metrics", []):
        db.add(
            CalculatedMetric(
                company_id=company.id,
                metric=row["metric"],
                value=Decimal(str(row["value"])) if row.get("value") is not None else None,
                unit=row.get("unit", "decimal"),
                period=row["period"],
                fiscal_year=row.get("fiscal_year"),
                fiscal_quarter=row.get("fiscal_quarter"),
                status=row.get("status", "ok"),
                definition_version=row.get("definition_version", "v1"),
                formula=row.get("formula", ""),
                numerator=Decimal(str(row["numerator"])) if row.get("numerator") is not None else None,
                denominator=Decimal(str(row["denominator"])) if row.get("denominator") is not None else None,
                source_fact_ids=[fact_ids.get(i, i) for i in row.get("source_fact_ids", [])],
                calculation_trace=row.get("calculation_trace", {}),
                confidence=Decimal(str(row.get("confidence", "0.70"))),
                # El WACC trazable desempata por created_at DESC (engines/base).
                created_at=(datetime.fromisoformat(row["created_at"]) if row.get("created_at") else None),
            )
        )
    db.commit()
    return company


def run_fixture(db: Session, fixture: dict) -> dict:
    """Corre el motor enrutado por el registry sobre el fixture cargado."""
    from app.valuation.engines.registry import resolve, resolve_engine_key

    company = load_fixture_into_session(db, fixture)
    routed = resolve_engine_key(company)
    recorded = fixture["meta"]["engine_key"]
    assert routed == recorded, (
        f"el routing cambió: fixture grabado con {recorded}, el registry ahora enruta a {routed}"
    )
    engine = resolve(company)
    price = float(fixture["price"]["close"])
    context = engine.build_context(
        db, company, price, price_as_of=date.fromisoformat(fixture["price"]["date"])
    )
    return engine.value(context)


def _compare(actual, expected, path: str) -> list[str]:
    """Devuelve la lista de diferencias "ruta: actual != esperado"."""
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return [f"{path}: {actual!r} no es dict"]
        diffs = []
        for key in sorted(set(actual) | set(expected)):
            if key not in actual:
                diffs.append(f"{path}.{key}: falta en actual")
            elif key not in expected:
                diffs.append(f"{path}.{key}: falta en esperado")
            else:
                diffs.extend(_compare(actual[key], expected[key], f"{path}.{key}"))
        return diffs
    if isinstance(expected, list):
        if not isinstance(actual, list) or len(actual) != len(expected):
            return [
                f"{path}: lista len {len(actual) if isinstance(actual, list) else '?'} != {len(expected)}"
            ]
        diffs = []
        for i, (a, e) in enumerate(zip(actual, expected)):
            diffs.extend(_compare(a, e, f"{path}[{i}]"))
        return diffs
    if isinstance(expected, (int, float)) and not isinstance(expected, bool):
        try:
            a = float(actual)
            e = float(expected)
        except (TypeError, ValueError):
            return [f"{path}: {actual!r} != {expected!r}"]
        if a == e or abs(a - e) <= max(ABS, REL * max(abs(a), abs(e))):
            return []
        return [f"{path}: {a!r} != {e!r}"]
    if actual != expected:
        return [f"{path}: {actual!r} != {expected!r}"]
    return []


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _fixture_files() -> list[Path]:
    if not FIXTURES_DIR.is_dir():
        return []
    return sorted(FIXTURES_DIR.glob("*.json"))


@pytest.mark.parametrize("fixture_path", _fixture_files(), ids=lambda p: p.stem)
def test_battery7_output_matches_recorded(db, fixture_path: Path):
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    actual = run_fixture(db, fixture)
    if GEN:
        fixture["output"] = json.loads(json.dumps(actual, default=_default))
        fixture_path.write_text(
            json.dumps(fixture, default=_default, indent=1, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        pytest.skip("BATTERY_GEN=1: salida regrabada, nada que comparar")
    diffs = _compare(actual, fixture["output"], fixture_path.stem)
    assert not diffs, (
        f"la salida de {fixture['meta']['ticker']} cambió respecto a la grabada "
        f"en {fixture['meta']['recorded_sha']}:\n" + "\n".join(diffs[:40])
    )


def test_battery7_fixtures_have_no_private_data():
    """Los fixtures son datos de mercado públicos: nunca tenant, usuario,
    inputs declarados ni secretos."""
    for path in _fixture_files():
        raw = path.read_text(encoding="utf-8")
        for forbidden in ("tenant", "external_id", "declared_input", "user", "email", "token"):
            assert forbidden not in raw.lower(), f"{path.name}: contiene {forbidden!r}"
