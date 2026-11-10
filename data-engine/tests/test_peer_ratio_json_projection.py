"""Project peer-rank inputs without changing legacy full-payload results."""

import json
import os
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session

from app.core.database import Base
from app.core.tenancy import tenant_filters
from app.models import Company, Tenant, ValuationModel, ValuationOutput
from app.services.fair_value_service import listed_value
from app.valuation.currency import normalize_currency
from app.valuation.relative_rank import _ratio, engine_peer_ratios


def _legacy_ratios(db):
    """Frozen original query/loop, only used as the full-payload comparator."""
    ranked = select(
        ValuationModel.id,
        func.row_number().over(
            partition_by=ValuationModel.company_id, order_by=ValuationModel.version.desc()
        ).label("rank"),
    ).where(
        ValuationModel.status.in_(("final", "draft", "insufficient_data")),
        *tenant_filters(db, ValuationModel),
    ).subquery()
    rows = db.execute(
        select(ValuationModel.company_id, ValuationModel.status,
               ValuationOutput.output_payload, Company.currency)
        .join(ranked, ValuationModel.id == ranked.c.id)
        .join(ValuationOutput, ValuationOutput.valuation_model_id == ValuationModel.id)
        .join(Company, Company.id == ValuationModel.company_id)
        .where(ranked.c.rank == 1)
    ).all()
    out = {}
    for company_id, status, payload, currency in rows:
        if status == "insufficient_data" or not isinstance(payload, dict) or int(company_id) in out:
            continue
        if normalize_currency(currency)[1] != 1:
            continue
        ratio = _ratio(listed_value(payload, fallback=payload), payload.get("current_price"))
        if ratio is not None:
            out[int(company_id)] = ratio
    return out


@pytest.fixture
def db():
    decoded_bytes = []

    def decode(value):
        decoded_bytes.append(len(value))
        return json.loads(value)

    # Optional PG run uses a unique schema only, never existing application tables.
    url = os.environ.get("PEER_RATIO_TEST_PG_URL", "sqlite:///:memory:")
    engine = create_engine(url, json_deserializer=decode)
    schema = None
    if engine.dialect.name == "postgresql":
        schema = "peer_projection_" + uuid4().hex
        with engine.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        engine = engine.execution_options(schema_translate_map={None: schema})
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            session.add_all([Tenant(id=i, external_id=f"projection-{i}", name="synthetic") for i in (2, 5)])
            session.commit()
            yield session, decoded_bytes
    finally:
        if schema is not None:
            with engine.begin() as conn:
                conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        engine.dispose()


def _company(db, index, currency="USD"):
    company = Company(ticker=f"JP{index}", name="Synthetic", exchange="TEST", currency=currency,
                      company_type="standard", valuation_model="dcf")
    db.add(company)
    db.flush()
    return company


def _output(db, company, payload, *, tenant=2, version=1, status="final"):
    model = ValuationModel(tenant_id=tenant, company_id=company.id,
                           model_type="dcf", version=version, status=status)
    db.add(model)
    db.flush()
    db.add(ValuationOutput(tenant_id=tenant, valuation_model_id=model.id,
                           scenario="base", output_payload=payload))
    db.flush()


def test_large_irrelevant_payload_is_not_transferred_or_decoded(db):
    session, decoded_bytes = db
    company = _company(session, "BIG")
    _output(session, company, {
        "current_price": 100, "expected_value": 150,
        "listed_share_values": {"expected": 200, "unused": "z" * 250_000},
        "trace": {"unused": "x" * 1_000_000},
    })
    session.commit()
    session.info["tenant_id"] = 2
    expected = _legacy_ratios(session)
    assert expected == {company.id: 2.0}
    decoded_bytes.clear()
    assert engine_peer_ratios(session) == expected
    assert decoded_bytes
    assert max(decoded_bytes) < 1000, "peer query still materializes the unrelated large JSON"
    assert sum(decoded_bytes) < 2000


@pytest.mark.parametrize(("payload", "ratio"), [
    (None, None), ([], None), ([{"expected_value": 150}], None), ("not an object", None),
    (42, None), (True, None), ({}, None),
    ({"expected_value": 150, "current_price": 100}, 1.5),
    ({"expected_value": "150", "current_price": "100"}, 1.5),
    ({"expected_value": 0, "base_value": 125, "current_price": 100}, 1.25),
    ({"expected_value": "Infinity", "base_value": 125, "current_price": 100}, 1.25),
    ({"expected_value": 150, "current_price": 0}, None),
    ({"expected_value": 150, "current_price": "NaN"}, None),
    ({"expected_value": 10000, "current_price": 100}, None),
    ({"expected_value": 2, "current_price": 100}, .02),
    ({"expected_value": 5000, "current_price": 100}, 50),
    ({"adr_ratio": 8, "expected_value": 150, "current_price": 100}, None),
    ({"adr_ratio": "8", "expected_value": 150, "current_price": 100,
      "listed_share_values": {"expected": "240", "base": 220}}, 2.4),
    ({"adr_ratio": 8, "expected_value": 150, "current_price": 100,
      "listed_share_values": {"expected": -2, "base": 180}}, 1.8),
    ({"adr_ratio": False, "expected_value": 150, "current_price": 100,
      "listed_share_values": [200]}, 1.5),
    ({"adr_ratio": {}, "expected_value": 150, "current_price": 100}, 1.5),
    ({"adr_ratio": {"bad": 1}, "expected_value": 150, "current_price": 100}, None),
    ({"listed_share_values": "bad", "base_value": 125, "current_price": 100}, 1.25),
    ({"listed_share_values": {"expected": {}, "base": [180]},
      "expected_value": 150, "current_price": 100}, 1.5),
    ({"listed_share_values": {"expected": True}, "current_price": True}, 1.0),
])
def test_projection_preserves_full_json_types_precedence_and_adr(db, payload, ratio):
    session, _ = db
    company = _company(session, "TYPES")
    _output(session, company, payload)
    session.commit()
    session.info["tenant_id"] = 2
    expected = {} if ratio is None else {company.id: ratio}
    assert _legacy_ratios(session) == expected
    assert engine_peer_ratios(session) == expected


def test_projection_preserves_tenant_2_5_latest_status_and_subunit_rules(db):
    session, _ = db
    shared = _company(session, "SHARED")
    insufficient = _company(session, "INSUFF")
    minor = _company(session, "MINOR", currency="GBX")
    for tenant, value in ((2, 150), (5, 75)):
        _output(session, shared, {"expected_value": 999, "current_price": 100}, tenant=tenant)
        _output(session, shared, {"expected_value": value, "current_price": 100},
                tenant=tenant, version=2, status="draft")
        _output(session, insufficient, {"expected_value": value, "current_price": 100}, tenant=tenant)
        _output(session, insufficient, {"expected_value": value, "current_price": 100},
                tenant=tenant, version=2, status="insufficient_data")
        _output(session, minor, {"expected_value": value, "current_price": 100}, tenant=tenant)
    session.commit()
    for tenant, ratio in ((2, 1.5), (5, .75)):
        session.info["tenant_id"] = tenant
        assert _legacy_ratios(session) == {shared.id: ratio}
        assert engine_peer_ratios(session) == {shared.id: ratio}
        # Core execution bypasses the ORM loader-criteria hook. This verifies
        # the explicit tenant predicate independently of that second guard.
        core_only = SimpleNamespace(
            info=session.info, get_bind=session.get_bind,
            execute=session.connection().execute,
        )
        assert engine_peer_ratios(core_only) == {shared.id: ratio}
