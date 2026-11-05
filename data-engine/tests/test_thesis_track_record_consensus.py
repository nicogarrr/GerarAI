"""Consenso congelado al emitir la tesis, puntuado junto al valor razonable.

El consenso sale de ``ThesisVersion.valuation_basis["consensus_check"]`` (un
dict con ``mean`` o un número) y nunca de la red: una versión sin consenso
conserva la salida antigua intacta.
"""

from __future__ import annotations

import math
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.core.database import SessionLocal, init_db
from app.models import Company, MarketPrice, Tenant, ThesisVersion
from app.models.thesis_realized_return import ThesisRealizedReturn
from app.services import thesis_track_record_service as svc
from app.services.thesis_track_record_service import PriceRow, score_version

ISSUE = date(2026, 1, 5)  # lunes
TODAY_6M = date(2026, 7, 10)
CONSENSUS_KEYS = {
    "consensus_at_issue",
    "consensus_signed_error",
    "consensus_abs_error",
    "consensus_error_vs_realized",
    "consensus_abs_error_vs_realized",
    "closer_than_consensus",
    "beat_consensus",
}


def _series(start: date, days: int, fn) -> list[PriceRow]:
    out = []
    for i in range(days):
        d = start + timedelta(days=i)
        if d.weekday() < 5:
            out.append(PriceRow(day=d, close=fn(i)))
    return out


def _rising() -> list[PriceRow]:
    return _series(ISSUE, 400, lambda i: 100 + i * 30 / 181)


# ------------------------------------------------------------------ función pura


def test_score_con_consenso_anade_metricas_en_horizontes_vencidos():
    out = score_version(issue=ISSUE, fair_value=120.0, stored_price=100.0, prices=_rising(),
                        today=TODAY_6M, consensus_at_issue={"mean": 110.0})
    h6, h12 = out["horizons"]
    assert h6["status"] == "matured" and h12["status"] == "pending"
    fv, p1, consensus = h6["fair_value"], h6["price"], 110.0
    signed = (fv - consensus) / consensus
    vs_realized = (consensus - p1) / p1
    assert h6["consensus_at_issue"] == consensus
    assert h6["consensus_signed_error"] == pytest.approx(signed, abs=1e-6)
    assert h6["consensus_abs_error"] == pytest.approx(abs(signed), abs=1e-6)
    assert h6["consensus_error_vs_realized"] == pytest.approx(vs_realized, abs=1e-6)
    assert h6["consensus_abs_error_vs_realized"] == pytest.approx(abs(vs_realized), abs=1e-6)
    assert h6["closer_than_consensus"] is (abs(fv - p1) < abs(consensus - p1))
    assert h6["beat_consensus"] is h6["closer_than_consensus"]
    assert CONSENSUS_KEYS.isdisjoint(h12)


def test_score_acepta_consenso_numerico_igual_que_dict():
    as_dict = score_version(issue=ISSUE, fair_value=120.0, stored_price=100.0, prices=_rising(),
                            today=TODAY_6M, consensus_at_issue={"mean": 110.0})
    as_number = score_version(issue=ISSUE, fair_value=120.0, stored_price=100.0, prices=_rising(),
                              today=TODAY_6M, consensus_at_issue=110.0)
    assert as_dict == as_number


@pytest.mark.parametrize("consensus", [
    None, 0, -5.0, math.nan, math.inf, {}, {"mean": None}, {"mean": "no-es-un-numero"},
])
def test_sin_consenso_valido_no_anade_claves(consensus):
    baseline = score_version(issue=ISSUE, fair_value=120.0, stored_price=100.0, prices=_rising(),
                             today=TODAY_6M)
    out = score_version(issue=ISSUE, fair_value=120.0, stored_price=100.0, prices=_rising(),
                        today=TODAY_6M, consensus_at_issue=consensus)
    assert out == baseline
    assert all(CONSENSUS_KEYS.isdisjoint(h) for h in out["horizons"])


def test_sin_lookahead_con_consenso_un_precio_posterior_no_cambia_el_horizonte():
    base = _series(ISSUE, 200, lambda i: 100 - i * 0.05)
    today = date(2026, 12, 31)
    after = [PriceRow(day=date(2026, 7, 7) + timedelta(days=i), close=1000.0, high=1000.0)
             for i in range(60)]
    a = score_version(issue=ISSUE, fair_value=150.0, stored_price=None, prices=base,
                      today=today, consensus_at_issue={"mean": 140.0})
    b = score_version(issue=ISSUE, fair_value=150.0, stored_price=None, prices=base + after,
                      today=today, consensus_at_issue={"mean": 140.0})
    assert a["horizons"][0]["status"] == "matured"
    assert a["horizons"][0] == b["horizons"][0]


# ------------------------------------------------------------------ resumen


def _sample(**overrides) -> dict:
    sample = {
        "direction_hit": True,
        "abs_error": 0.1,
        "signed_error": 0.1,
        "touched": True,
        "consensus_signed_error": 0.05,
        "consensus_abs_error": 0.05,
        "consensus_abs_error_vs_realized": 0.04,
        "closer_than_consensus": True,
    }
    sample.update(overrides)
    return sample


def test_summary_agrega_metricas_de_consenso():
    samples = [
        _sample(),
        _sample(direction_hit=False, consensus_signed_error=-0.15, consensus_abs_error=0.15,
                consensus_abs_error_vs_realized=0.10, closer_than_consensus=False),
        _sample(consensus_signed_error=None, consensus_abs_error=None,
                consensus_abs_error_vs_realized=None, closer_than_consensus=None),
    ]
    out = svc._summary(samples)
    assert out["samples"] == 3 and out["consensus_samples"] == 2
    assert out["beat_consensus_rate"] == 0.5
    assert out["median_abs_error_vs_consensus"] == pytest.approx(0.10, abs=1e-4)
    assert out["median_consensus_abs_error_vs_realized"] == pytest.approx(0.07, abs=1e-4)
    assert out["median_signed_error_vs_consensus"] == pytest.approx(-0.05, abs=1e-4)


def test_summary_sin_muestras_mantiene_ceros_y_consenso_en_none():
    out = svc._summary([])
    assert out["samples"] == 0 and out["hits"] == 0 and out["hit_rate"] is None
    assert out["consensus_samples"] == 0
    assert out["beat_consensus_rate"] is None
    assert out["median_abs_error_vs_consensus"] is None
    assert out["median_consensus_abs_error_vs_realized"] is None
    assert out["median_signed_error_vs_consensus"] is None


def test_summary_beat_rate_ignora_muestras_sin_comparacion():
    out = svc._summary([_sample(closer_than_consensus=None)])
    assert out["consensus_samples"] == 1
    assert out["beat_consensus_rate"] is None


# ------------------------------------------------------------------ job con BD


def _company(db, ticker: str) -> Company:
    company = Company(ticker=ticker, name=f"Empresa {ticker}", exchange="NASDAQ", currency="USD",
                      sector="Test", industry="Test", company_type="standard", valuation_model="standard_dcf")
    db.add(company)
    db.flush()
    return company


def _tenant(db, label: str) -> int:
    tenant = Tenant(external_id=f"{label}-{uuid4().hex[:8]}", name=label, status="active")
    db.add(tenant)
    db.flush()
    return tenant.id


def _version(company_id: int, tenant_id: int, issued: date, base: str,
             consensus, n: int = 1) -> ThesisVersion:
    return ThesisVersion(
        company_id=company_id, tenant_id=tenant_id, version=n, status="draft", thesis_markdown="t",
        executive_summary="s", base_value=Decimal(base), current_price=Decimal("100"),
        valuation_basis={"consensus_check": consensus},
        created_at=datetime(issued.year, issued.month, issued.day, 15, tzinfo=UTC),
    )


def _prices(db, company_id: int, start: date, days: int, fn) -> None:
    for row in _series(start, days, fn):
        db.add(MarketPrice(company_id=company_id, date=row.day, close=Decimal(str(round(row.close, 4))),
                           source="test"))


def test_refresh_lee_el_consenso_congelado_y_lo_persiste_en_horizontes():
    init_db()
    ticker = f"TC{uuid4().hex[:4].upper()}"
    with SessionLocal() as db:
        tenant_id = _tenant(db, "consensus")
        company = _company(db, ticker)
        _prices(db, company.id, ISSUE, 220, lambda i: 100 + i * 0.1)
        db.add(_version(company.id, tenant_id, ISSUE, "130", {"mean": 110.0}, n=1))
        db.add(_version(company.id, tenant_id, ISSUE, "131", 111.0, n=2))
        db.commit()
        company_id = company.id

    def run(today: date) -> dict:
        with SessionLocal() as db:
            db.info["tenant_id"] = tenant_id
            return svc.refresh_track_record(db, today=today)

    first = run(date(2026, 7, 20))
    assert (first["versions"], first["created"]) == (2, 2)
    with SessionLocal() as db:
        db.info["tenant_id"] = tenant_id
        rows = db.scalars(
            select(ThesisRealizedReturn)
            .where(ThesisRealizedReturn.company_id == company_id)
            .order_by(ThesisRealizedReturn.thesis_version)
        ).all()
        assert [r.horizons[0]["consensus_at_issue"] for r in rows] == [110.0, 111.0]
        assert all(r.horizons[0]["beat_consensus"] == r.horizons[0]["closer_than_consensus"]
                   for r in rows)
        version = db.scalar(select(ThesisVersion).where(
            ThesisVersion.company_id == company_id, ThesisVersion.version == 1))
        assert version is not None
        version.valuation_basis = {"consensus_check": {"mean": 125.0}}
        db.commit()

    changed = run(date(2026, 7, 20))
    assert changed["updated"] == 1 and changed["unchanged"] == 1
    with SessionLocal() as db:
        db.info["tenant_id"] = tenant_id
        row = db.scalar(select(ThesisRealizedReturn).where(
            ThesisRealizedReturn.company_id == company_id,
            ThesisRealizedReturn.thesis_version == 1))
        assert row is not None
        assert row.horizons[0]["consensus_at_issue"] == 125.0
        assert row.revision == 2
