"""Factores observacionales (factors-v0): momentum 12-1 y percentiles
quality/momentum/value. Nada de esto entra en SCORE_WEIGHTS ni en el orden."""

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select, update

from app.models import CalculatedMetric, FinancialFact, MarketPrice
from app.services.propicks_funnel_service import (
    FACTOR_CONTRACT_VERSION,
    _latest_metrics,
    _percentile_ranks,
    run_funnel,
)
from app.services.propicks_price_service import (
    compute_momentum_metrics,
    momentum_12_1_from_series,
)
from app.valuation.irr_pit_backtest import LookAheadError
from tests.test_propicks_funnel import (
    _company,
    _db,
    _five_good_years,
    _full_metrics,
    _metric,
)


def _series(days=420, start=date(2024, 1, 1), price_fn=lambda i: Decimal(100 + i)):
    return [(start + timedelta(days=i), Decimal(str(price_fn(i)))) for i in range(days)]


def _pin_metrics_created_at(db, when: datetime = datetime(2026, 3, 1)) -> None:
    """Fija cuándo se conocieron las métricas: el cutoff PIT (created_at)
    debe poder incluirlas/excluirlas de forma determinista en tests."""
    db.execute(update(CalculatedMetric).values(created_at=when))
    db.commit()


# --- momentum_12_1_from_series ---------------------------------------------


def test_momentum_12_1_excluye_el_ultimo_mes():
    base = _series()
    v1 = momentum_12_1_from_series(base)
    assert v1 is not None
    # Cambiar solo los últimos 25 días no cambia el 12-1 (los salta).
    changed = base[:-25] + [(d, p * 3) for d, p in base[-25:]]
    assert momentum_12_1_from_series(changed) == v1
    # Y sí usa el tramo t-365..t-30: duplicar TODO el tramo lo duplica aprox.
    up = _series(price_fn=lambda i: Decimal(100 + i * 2))
    assert momentum_12_1_from_series(up) > v1


def test_momentum_12_1_tolerancia_20_dias():
    # Hueco de 41 días alrededor de t-365: el punto válido queda a 21+ días
    # del objetivo -> None (no vendemos como 12-1 otra cosa).
    s = _series()
    last = s[-1][0]
    target = last - timedelta(days=365)
    holed = [(d, p) for d, p in s if abs((d - target).days) > 20]
    assert momentum_12_1_from_series(holed) is None


def test_momentum_12_1_serie_corta_o_precio_no_positivo():
    assert momentum_12_1_from_series([]) is None
    assert momentum_12_1_from_series([(date(2025, 1, 1), Decimal("100"))]) is None
    s = _series()
    zeroed = [(d, (Decimal("0") if (s[-1][0] - d).days >= 365 else p)) for d, p in s]
    assert momentum_12_1_from_series(zeroed) is None


def test_compute_momentum_12_1_as_of_e_idempotencia():
    with _db() as db:
        c = _company("M121")
        db.add(c)
        db.flush()
        start = date(2024, 1, 1)
        for i in range(400):
            db.add(
                MarketPrice(
                    company_id=c.id,
                    date=start + timedelta(days=i),
                    close=Decimal(str(100 + i)),
                    adj_close=Decimal(str(100 + i)),
                    source="test",
                )
            )
        db.commit()
        as_of = start + timedelta(days=399)
        stats = compute_momentum_metrics(db, [c], as_of=as_of)
        assert stats["momentum_12_1"] == 1
        row = db.scalar(
            select(CalculatedMetric).where(
                CalculatedMetric.company_id == c.id, CalculatedMetric.metric == "momentum_12_1"
            )
        )
        v = row.value
        # Barras POSTERIORES a as_of no cambian el valor ni duplican la fila.
        for i in range(400, 410):
            db.add(
                MarketPrice(
                    company_id=c.id,
                    date=start + timedelta(days=i),
                    close=Decimal("9999"),
                    adj_close=Decimal("9999"),
                    source="test",
                )
            )
        db.commit()
        stats2 = compute_momentum_metrics(db, [c], as_of=as_of)
        assert stats2["momentum_12_1"] == 1
        rows = db.scalars(
            select(CalculatedMetric).where(
                CalculatedMetric.company_id == c.id, CalculatedMetric.metric == "momentum_12_1"
            )
        ).all()
        assert len(rows) == 1
        assert rows[0].value == v


# --- percentiles ------------------------------------------------------------


def test_percentile_ranks_empates_nulos_un_valor_y_vacio():
    assert _percentile_ranks({}) == {}
    assert _percentile_ranks({1: 5.0}) == {1: 0.5}
    tied = _percentile_ranks({1: 1.0, 2: 2.0, 3: 2.0, 4: 3.0})
    assert tied[2] == tied[3] == 0.5 * (1 + 2) / 3
    assert tied[1] == 0.0 and tied[4] == 1.0


# --- run_funnel: factores observacionales ------------------------------------


def _good_company(db, ticker="GOOD", sector="Industrials", overrides=None):
    c = _company(ticker, sector=sector)
    db.add(c)
    db.flush()
    _full_metrics(db, c, overrides)
    _five_good_years(db, c)
    db.commit()
    return c


def test_factores_no_cambian_score_ni_orden():
    with _db() as db:
        a = _good_company(db, "GOODA")
        b = _good_company(db, "GOODB", overrides={"roic": "0.30"})
        _pin_metrics_created_at(db)
        before = {r.company_id: (r.score, r.passed) for r in run_funnel(db)[0]}
        # Añadir momentum_12_1 y un earnings yield PIT válido no mueve nada.
        _metric(db, a, "momentum_12_1", "0.25")
        _metric(db, b, "momentum_12_1", "0.10")
        _pin_metrics_created_at(db)
        db.add(
            FinancialFact(
                company_id=a.id,
                metric="earnings_yield",
                value=Decimal("0.07"),
                unit="decimal",
                period="FY2025",
                fiscal_year=2025,
                fiscal_quarter="FY",
                source_type="sec_filing",
                filed=date(2026, 3, 1),
            )
        )
        db.commit()
        results, stats = run_funnel(db, as_of=date(2026, 6, 1))
        after = {r.company_id: (r.score, r.passed) for r in results}
        assert after == before
        fa = next(r for r in results if r.company_id == a.id)
        assert fa.metrics["factor_momentum_pct"] == 1.0  # mayor momentum de los dos
        assert fa.metrics["factor_value_pct"] == 0.5  # única con EY: percentil 0,5
        fb = next(r for r in results if r.company_id == b.id)
        assert fb.metrics["factor_value_pct"] is None  # sin EY/FCFY: sin imputar
        # quality = percentil empírico del moat del universo (empate -> 0,5),
        # NO el score normalizado (score/100 sería 0,375/0,625 aquí).
        assert fa.metrics["factor_quality_pct"] == 0.5
        assert fb.metrics["factor_quality_pct"] == 0.5
        assert fa.metrics["factor_quality_pct"] != pytest.approx(fa.score / 100.0)
        f = stats["factors"]
        assert f["version"] == FACTOR_CONTRACT_VERSION
        assert f["factors"] == ["quality", "momentum", "value"]
        assert f["as_of"] == "2026-06-01"
        assert f["coverage"]["momentum"] == 1.0
        assert f["coverage"]["value"] == 0.5


def test_financieras_value_pb_mas_roe_nunca_ebit_ev():
    with _db() as db:
        bank = _good_company(
            db, "BANK", sector="Financials",
            overrides={"roic": "0.01", "cfroi_approx": "0.01", "roe_5y": "0.15"},
        )
        _metric(db, bank, "price_to_book", "1.2")
        db.commit()
        (r,), stats = run_funnel(db)
        assert r.metrics["factor_value_pct"] is not None  # P/B invertido + ROE
        assert stats["factors"]["coverage"]["value"] == 1.0


def test_as_of_corta_todas_las_entradas_de_los_factores():
    """Regresión (auditor): run_funnel(as_of=2020-01-01) con métricas
    persistidas en 2026 no usa nada posterior al corte: momentum_12_1,
    P/B, ROE y moat quedan fuera (created_at >= corte) y los factores
    salen None con cobertura 0 — N/D honesto, sin LookAheadError porque
    tampoco hay FinancialFact de valoración posterior."""
    with _db() as db:
        a = _good_company(db, "PITA")
        _metric(db, a, "momentum_12_1", "0.25")
        bank = _good_company(
            db, "PITB", sector="Financials",
            overrides={"roic": "0.01", "cfroi_approx": "0.01", "roe_5y": "0.15"},
        )
        _metric(db, bank, "price_to_book", "1.2")
        db.commit()
        reference = {r.company_id: (r.score, r.passed) for r in run_funnel(db)[0]}
        results, stats = run_funnel(db, as_of=date(2020, 1, 1))
        assert results, "el embudo corre y devuelve filas aunque todo sea N/D"
        # El score y las gates NO dependen de as_of (mapa sin corte).
        assert {r.company_id: (r.score, r.passed) for r in results} == reference
        for r in results:
            assert r.metrics["factor_quality_pct"] is None
            assert r.metrics["factor_momentum_pct"] is None
            assert r.metrics["factor_value_pct"] is None
        f = stats["factors"]
        assert f["coverage"] == {"quality": 0.0, "momentum": 0.0, "value": 0.0}
        assert f["as_of"] == "2020-01-01"


def test_mismo_periodo_elige_la_revision_disponible_en_el_corte():
    """Regresión (auditor): misma (company, metric, period) con dos
    revisiones — .1 creada en 2019 y .9 creada en 2026 — el corte 2020
    devuelve .1 (la disponible), nunca .9. Sin corte gana la más reciente."""
    with _db() as db:
        a = _good_company(db, "DUP")
        for version, value, created in (
            ("dup-v1", "0.1", datetime(2019, 1, 1)),
            ("dup-v2", "0.9", datetime(2026, 5, 1)),
        ):
            db.add(
                CalculatedMetric(
                    company_id=a.id,
                    metric="momentum_12_1",
                    value=Decimal(value),
                    unit="decimal",
                    period="FY2025",
                    fiscal_year=2025,
                    status="ok",
                    definition_version=version,
                    formula="momentum_12_1",
                    source_fact_ids=[],
                    calculation_trace={},
                    confidence=Decimal("0.9"),
                    created_at=created,
                )
            )
        db.commit()
        assert _latest_metrics(db, date(2020, 1, 1))[(a.id, "momentum_12_1")] == 0.1
        assert _latest_metrics(db)[(a.id, "momentum_12_1")] == 0.9
        # A nivel de embudo: el factor usa la revisión disponible en el
        # corte (única empresa con momentum -> percentil 0,5) y el score
        # sigue intacto.
        reference = {r.company_id: (r.score, r.passed) for r in run_funnel(db)[0]}
        results, stats = run_funnel(db, as_of=date(2020, 1, 1))
        assert {r.company_id: (r.score, r.passed) for r in results} == reference
        r = results[0]
        assert r.metrics["factor_momentum_pct"] == 0.5
        assert stats["factors"]["coverage"]["momentum"] == 1.0
        # Y con un corte ANTERIOR a 2019 no hay nada disponible: N/D.
        results18, stats18 = run_funnel(db, as_of=date(2018, 1, 1))
        assert results18[0].metrics["factor_momentum_pct"] is None
        assert stats18["factors"]["coverage"]["momentum"] == 0.0


def test_earnings_yield_posterior_a_as_of_es_lookahead():
    with _db() as db:
        a = _good_company(db)
        db.add(
            FinancialFact(
                company_id=a.id,
                metric="earnings_yield",
                value=Decimal("0.07"),
                unit="decimal",
                period="FY2026",
                fiscal_year=2026,
                fiscal_quarter="FY",
                source_type="sec_filing",
                filed=date(2026, 12, 1),
            )
        )
        db.commit()
        with pytest.raises(LookAheadError):
            run_funnel(db, as_of=date(2026, 6, 1))
