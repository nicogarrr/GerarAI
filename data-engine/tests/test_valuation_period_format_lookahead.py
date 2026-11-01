"""Guard point-in-time con el formato de periodo REAL de produccion.

`financial_ingestion_service` / `class_filer_eps_service` persisten el periodo
como ``f"{end}:FY"`` ("2025-09-30:FY"), no como el "FY2025" legado. La cobertura
anterior del wiring solo usaba la forma legada, asi que era cobertura aparente y
ciega al formato que la ingestion escribe de verdad: con `as_of=2025-03-31` un
"2025-09-30:FY" (seis meses en el futuro) pasaba el guard porque el unico digito
que se miraba era el ano y `2025 > 2025` es falso.

Aqui se cubre el formato real end-to-end por `value_company`, mas el contrato
puro de parseo y la resolucion del cutoff.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from app.services import valuation_service
from app.services.moat_service import MoatService
from app.valuation.point_in_time import (
    AS_OF_SOURCE_EXPLICIT,
    AS_OF_SOURCE_TODAY,
    AS_OF_SOURCE_TRACE,
    AS_OF_SOURCE_VALUATION,
    PRECISION_EXACT_DATE,
    PRECISION_FISCAL_YEAR,
    PRECISION_UNKNOWN,
    LookaheadError,
    assert_fiscal_year_no_lookahead,
    assert_no_lookahead,
    assert_period_no_lookahead,
    parse_period_bounds,
    resolve_as_of,
)

# Formatos que el repo emite de verdad (financial_ingestion_service.py:1008,
# 1060, 1227; class_filer_eps_service.py:174; thesis_evidence_service.py:356;
# screener_service.py:710; metric_calculation_service.py:1241).
INGESTED_FORMATS = [
    "2025-09-30:FY",
    "2025-06-30:ANNUAL",
    "2025-06-30:Q2",
    "2025-06-30:10-Q",
]
LEGACY_FORMATS = ["FY2025", "2025", "2025-09-30"]


class _EngineReturning:
    def __init__(self, result: dict) -> None:
        self.result = result

    def build_context(self, db, company, current_price, as_of=None, **_):
        return object()

    def currency_input_units(self, context) -> list[str | None]:
        return []  # This point-in-time fixture supplies no monetary inputs.

    def value(self, context) -> dict:
        return self.result


def _value_company(monkeypatch, result: dict, **kwargs) -> dict:
    engine = _EngineReturning(result)
    company = SimpleNamespace(id=1, ticker="PIT")
    monkeypatch.setattr(valuation_service, "resolve", lambda _company: engine)
    monkeypatch.setattr(valuation_service, "resolve_engine_key", lambda _company: "test")
    monkeypatch.setattr(valuation_service, "_position_price", lambda _db, _company_id, _as_of=None: 100.0)
    monkeypatch.setattr(valuation_service, "_free_data_trace", lambda _db, _company: None)
    monkeypatch.setattr(MoatService, "assess", lambda *_args, **_kwargs: {})
    return valuation_service.ValuationService().value_company(object(), company, **kwargs)


def _valuation(periods: dict) -> dict:
    return {
        "ticker": "PIT",
        "model_type": "test",
        "status": "ok",
        "publishable": True,
        "trace": {"periods": periods},
    }


# --- el bug: "<fin>:FY" comparado contra el ano en vez de contra la fecha ---


def test_ingested_period_inside_same_year_is_rejected(monkeypatch) -> None:
    """Cierre tres meses posterior al cutoff, con el ANO coincidente.

    Con el guard por ano esto pasaba (2025 > 2025 es falso): el hecho es del
    futuro y la valoracion a mitad de ejercicio admitia el ano entero.
    """
    with pytest.raises(LookaheadError, match="2025-06-30:FY"):
        _value_company(
            monkeypatch,
            _valuation({"revenue": "2025-06-30:FY"}),
            as_of=date(2025, 3, 31),
        )


def test_ingested_period_six_months_ahead_is_rejected(monkeypatch) -> None:
    with pytest.raises(LookaheadError, match="2025-09-30:FY"):
        _value_company(
            monkeypatch,
            _valuation({"revenue": "2025-09-30:FY"}),
            as_of=date(2025, 3, 31),
        )


@pytest.mark.parametrize("period", INGESTED_FORMATS)
def test_every_ingested_tag_variant_is_rejected(monkeypatch, period: str) -> None:
    """La etiqueta de "<fin>:<tag>" no puede degradar la precision a ano."""
    with pytest.raises(LookaheadError):
        _value_company(
            monkeypatch,
            _valuation({"revenue": period}),
            as_of=date(2025, 3, 31),
        )


def test_ingested_period_before_cutoff_is_accepted(monkeypatch) -> None:
    result = _value_company(
        monkeypatch,
        _valuation({"revenue": "2024-12-31:FY"}),
        as_of=date(2025, 3, 31),
    )
    assert result["status"] == "ok"
    assert result["trace"]["point_in_time"]["as_of"] == "2025-03-31"


def test_ingested_period_after_its_own_filing_is_accepted(monkeypatch) -> None:
    """El caso que hoy falla: mismo periodo, cutoff ya pasado."""
    result = _value_company(
        monkeypatch,
        _valuation({"revenue": "2025-09-30:FY"}),
        as_of=date(2026, 1, 1),
    )
    assert result["status"] == "ok"
    assert result["trace"]["point_in_time"]["by_precision"] == {PRECISION_EXACT_DATE: 1}


def test_snapshot_anchor_period_is_guarded_too(monkeypatch) -> None:
    """trace["snapshot"] alimenta el trace con periodos que no pasan por
    trace["periods"], asi que el mismo criterio tiene que aplicarsele."""
    valuation = _valuation({})
    valuation["trace"]["snapshot"] = {"as_of": "2025-09-30:FY", "income_statement": "2025-09-30:FY"}
    with pytest.raises(LookaheadError, match="snapshot.as_of"):
        _value_company(monkeypatch, valuation, as_of=date(2025, 3, 31))


def test_period_range_uses_its_latest_bound(monkeypatch) -> None:
    """"FY2020-FY2025" (metric_calculation_service) con cutoff 2021 usa datos de
    2025: mirar solo el primer ano del rango lo validaba."""
    with pytest.raises(LookaheadError, match="FY2020-FY2025"):
        _value_company(
            monkeypatch,
            _valuation({"wacc": "FY2020-FY2025"}),
            as_of=date(2024, 1, 1),
        )


# --- los formatos legados siguen funcionando ---


def test_legacy_fiscal_year_still_rejected(monkeypatch) -> None:
    with pytest.raises(LookaheadError, match="FY2999"):
        _value_company(
            monkeypatch,
            _valuation({"revenue": "FY2999"}),
            as_of=date(2026, 9, 23),
        )


@pytest.mark.parametrize("period", LEGACY_FORMATS)
def test_legacy_and_bare_iso_formats_still_accepted(monkeypatch, period: str) -> None:
    result = _value_company(
        monkeypatch,
        _valuation({"revenue": period}),
        as_of=date(2025, 12, 31),
    )
    assert result["status"] == "ok"


def test_legacy_bare_year_still_rejected_across_years(monkeypatch) -> None:
    with pytest.raises(LookaheadError, match="fiscal year 2026"):
        _value_company(
            monkeypatch,
            _valuation({"revenue": "2026"}),
            as_of=date(2025, 12, 31),
        )


# --- contrato puro de parseo ---


@pytest.mark.parametrize(
    ("period", "end_date", "fiscal_year", "precision"),
    [
        ("2025-09-30:FY", date(2025, 9, 30), None, PRECISION_EXACT_DATE),
        ("2025-09-30:10-K", date(2025, 9, 30), None, PRECISION_EXACT_DATE),
        ("2025-09-30", date(2025, 9, 30), None, PRECISION_EXACT_DATE),
        (date(2025, 9, 30), date(2025, 9, 30), None, PRECISION_EXACT_DATE),
        ("FY2025", None, 2025, PRECISION_FISCAL_YEAR),
        ("2025", None, 2025, PRECISION_FISCAL_YEAR),
        ("FY2020-FY2025", None, 2025, PRECISION_FISCAL_YEAR),
        ("FY", None, None, PRECISION_UNKNOWN),
        ("ANNUAL", None, None, PRECISION_UNKNOWN),
        ("unknown", None, None, PRECISION_UNKNOWN),
        ("ISIN US0378331005", None, None, PRECISION_UNKNOWN),
        (None, None, None, PRECISION_UNKNOWN),
    ],
)
def test_parse_period_bounds_covers_every_persisted_format(
    period, end_date, fiscal_year, precision
) -> None:
    bounds = parse_period_bounds(period)
    assert bounds.end_date == end_date
    assert bounds.fiscal_year == fiscal_year
    assert bounds.precision == precision


def test_assert_period_no_lookahead_uses_the_end_date_not_the_year() -> None:
    """Con el ano no saltaria: el error que sale es el de la FECHA de cierre."""
    with pytest.raises(LookaheadError, match="dated 2025-06-30 is after as_of"):
        assert_period_no_lookahead(
            as_of=date(2025, 3, 31), period="2025-06-30:FY", label="revenue"
        )
    bounds = assert_period_no_lookahead(
        as_of=date(2025, 9, 30), period="2025-06-30:FY", label="revenue"
    )
    assert bounds.end_date == date(2025, 6, 30)
    assert bounds.fiscal_year is None


def test_assert_period_no_lookahead_stays_silent_on_opaque_periods() -> None:
    bounds = assert_period_no_lookahead(
        as_of=date(2020, 1, 1), period="FY", label="revenue"
    )
    assert bounds.precision == PRECISION_UNKNOWN


def test_existing_public_contract_is_unchanged() -> None:
    """assert_no_lookahead / assert_fiscal_year_no_lookahead / LookaheadError son
    el contrato que ya usan el resto del paquete (historical_valuation_service)
    y los tests previos: no se rompen al anadir el parseo de periodos."""
    assert_no_lookahead(as_of=date(2025, 3, 31), data_date=None, label="x")
    assert_fiscal_year_no_lookahead(as_of=date(2025, 3, 31), fiscal_year=2025, label="x")
    assert issubclass(LookaheadError, ValueError)
    with pytest.raises(LookaheadError, match="after as_of"):
        assert_no_lookahead(as_of=date(2025, 3, 31), data_date=date(2025, 4, 1))
    with pytest.raises(LookaheadError, match="fiscal year 2026"):
        assert_fiscal_year_no_lookahead(
            as_of=date(2025, 3, 31), fiscal_year=2026, label="revenue"
        )


# --- el cutoff: fail-open explicito y auditable ---


def test_missing_as_of_falls_back_to_today_and_says_so(monkeypatch) -> None:
    """Decision: hoy como default es DELIBERADO (los llamantes sin as_of
    valoran la empresa hoy), pero queda marcado en el trace. Un as_of deducido
    tiene que ser distinguible de uno pedido por el llamante."""
    result = _value_company(monkeypatch, _valuation({"revenue": "2020-12-31:FY"}))
    point_in_time = result["trace"]["point_in_time"]
    assert point_in_time["as_of_source"] == AS_OF_SOURCE_TODAY
    assert point_in_time["as_of_inferred"] is True
    assert point_in_time["as_of"] == date.today().isoformat()


def test_missing_as_of_still_rejects_data_dated_in_the_future(monkeypatch) -> None:
    with pytest.raises(LookaheadError):
        _value_company(
            monkeypatch,
            _valuation({"revenue": "2999-12-31:FY"}),
        )


def test_explicit_as_of_is_recorded_as_requested(monkeypatch) -> None:
    result = _value_company(
        monkeypatch,
        _valuation({"revenue": "2020-12-31:FY"}),
        as_of=date(2025, 3, 31),
    )
    point_in_time = result["trace"]["point_in_time"]
    assert point_in_time["as_of_source"] == AS_OF_SOURCE_EXPLICIT
    assert point_in_time["as_of_inferred"] is False
    assert point_in_time["as_of"] == "2025-03-31"


def test_as_of_from_the_payload_is_audited_with_its_source(monkeypatch) -> None:
    valuation = _valuation({"revenue": "2025-09-30:FY"})
    valuation["trace"]["as_of"] = "2025-03-31"
    with pytest.raises(LookaheadError):
        _value_company(monkeypatch, valuation)


def test_resolve_as_of_precedence() -> None:
    valuation = {"as_of": "2021-01-01"}
    trace = {"as_of": "2022-01-01"}
    today = date(2019, 1, 1)

    assert resolve_as_of(as_of="2020-01-01", valuation=valuation, trace=trace).source == (
        AS_OF_SOURCE_EXPLICIT
    )
    assert resolve_as_of(valuation=valuation, trace=trace).source == AS_OF_SOURCE_VALUATION
    assert resolve_as_of(trace=trace).source == AS_OF_SOURCE_TRACE
    inferred = resolve_as_of(valuation={}, trace={}, today=today)
    assert (inferred.cutoff, inferred.source, inferred.inferred) == (
        today,
        AS_OF_SOURCE_TODAY,
        True,
    )


def test_resolve_as_of_accepts_iso_strings_and_dates() -> None:
    assert resolve_as_of(as_of="2025-03-31").cutoff == date(2025, 3, 31)
    assert resolve_as_of(as_of=date(2025, 3, 31)).cutoff == date(2025, 3, 31)


def test_resolve_as_of_rejects_a_malformed_explicit_as_of() -> None:
    """Un as_of pedido pero ilegible SI es error: el llamante queria una fecha y
    recibir otra en silencio seria peor que un fallo."""
    with pytest.raises(ValueError, match="must be an ISO date"):
        resolve_as_of(as_of="31-03-2025")


# --- auditoria: precision y periodos opacos ---


def test_trace_reports_precision_per_format(monkeypatch) -> None:
    result = _value_company(
        monkeypatch,
        _valuation(
            {
                "revenue": "2024-12-31:FY",
                "eps": "FY2024",
                "shares_diluted": "FY",
                "net_debt": None,
            }
        ),
        as_of=date(2025, 3, 31),
    )
    point_in_time = result["trace"]["point_in_time"]
    assert point_in_time["periods_checked"] == 4
    assert point_in_time["by_precision"] == {
        PRECISION_EXACT_DATE: 1,
        PRECISION_FISCAL_YEAR: 1,
        PRECISION_UNKNOWN: 2,
    }
    # Un periodo ausente ("net_debt": None) es un hueco de cobertura igual que
    # uno opaco ("FY"): se listan para que la cobertura del guard sea auditable.
    assert point_in_time["opaque_periods"] == [
        "valuation shares_diluted FY",
        "valuation net_debt None",
    ]


def test_valuation_without_a_trace_map_records_nothing() -> None:
    valuation = {"trace": "no-es-un-mapa"}
    assert valuation_service._assert_no_lookahead_guard(valuation) is None
    assert valuation == {"trace": "no-es-un-mapa"}


def test_valuation_with_empty_trace_records_the_cutoff_it_used() -> None:
    valuation = {"trace": {}}
    assert valuation_service._assert_no_lookahead_guard(valuation) is None
    audit = valuation["trace"]["point_in_time"]
    assert audit["periods_checked"] == 0
    assert audit["by_precision"] == {}
    assert audit["as_of_inferred"] is True


def test_valuation_without_periods_still_records_its_cutoff(monkeypatch) -> None:
    """Regresion: con trace vacio el bloque de auditoria se escribia sobre una
    copia descartada (`valuation.get("trace") or {}`), asi que las valoraciones
    con menos datos eran justo las que no dejaban rastro del cutoff."""
    result = _value_company(
        monkeypatch,
        {"ticker": "PIT", "model_type": "test", "status": "ok", "publishable": True},
        as_of=date(2025, 3, 31),
    )
    assert result["trace"]["point_in_time"] == {
        "as_of": "2025-03-31",
        "as_of_source": AS_OF_SOURCE_EXPLICIT,
        "as_of_inferred": False,
        "periods_checked": 0,
        "by_precision": {},
        "opaque_periods": [],
    }
