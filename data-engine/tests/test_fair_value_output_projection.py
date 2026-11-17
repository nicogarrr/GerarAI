"""Frozen full-payload comparator for candidate/block/gap parity."""
from __future__ import annotations

from collections.abc import Iterable

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from app.core.tenancy import tenant_filters
from app.models import ValuationModel, ValuationOutput
from app.services import fair_value_service as fvs
from app.services.fair_value_service import (
    ENGINE_GAP_ADR,
    ENGINE_GAP_NO_OUTPUT,
    ENGINE_GAP_NO_RUN,
    ENGINE_GAP_NON_POSITIVE,
    Candidate,
    EngineBlock,
    EngineGap,
    _as_date,
    _engine_block,
    _engine_value,
    _estimated_inputs,
    _method_label,
)
from tests.test_peer_ratio_json_projection import _company, _output, db  # noqa: F401


def _legacy_readings(db: Session, company_ids: Iterable[int], *, gaps: dict[int, EngineGap] | None=None) -> tuple[dict[int, Candidate], dict[int, EngineBlock]]:
    """Última corrida PERSISTIDA del motor por empresa (lectura barata, por lotes).

    No recalcula: la watchlist pide hasta 60 tickers y el motor completo por
    ticker es caro. Para un solo ticker, ``resolve_fair_value(live=True)``.

    La ultima corrida manda SEA CUAL SEA SU ESTADO: si es
    ``insufficient_data`` no se resucita el numero de una corrida anterior
    (un borrador viejo seguia sirviendose como «motor orientativo»); la
    empresa queda sin candidato y con su :class:`EngineBlock`. La caducidad
    de los borradores orientativos se aplica en ``choose`` (misma regla para
    la via por lotes y la individual).

    ``gaps`` (opcional) recibe, por empresa sin candidato ni bloqueo, por qué el motor no aporta cifra
    (:class:`EngineGap`: sin corrida guardada, corrida sin resultado, valor no positivo o ADR sin valor cotizado).
    """
    ids = list(company_ids)
    if not ids:
        return ({}, {})
    ranked = select(ValuationModel.id, func.row_number().over(partition_by=ValuationModel.company_id, order_by=ValuationModel.version.desc()).label('rank')).where(ValuationModel.company_id.in_(ids), ValuationModel.status.in_(('final', 'draft', 'insufficient_data')), *tenant_filters(db, ValuationModel)).subquery()
    models = db.scalars(select(ValuationModel).join(ranked, ValuationModel.id == ranked.c.id).where(ranked.c.rank == 1)).all()
    if not models:
        if gaps is not None:
            gaps.update({int(company_id): EngineGap(kind=ENGINE_GAP_NO_RUN) for company_id in ids})
        return ({}, {})
    blocks = {int(model.company_id): _engine_block(model) for model in models if model.status == 'insufficient_data'}
    by_model = {model.id: model for model in models if model.status != 'insufficient_data'}
    outputs = db.scalars(select(ValuationOutput).where(ValuationOutput.valuation_model_id.in_(list(by_model)))).all() if by_model else []
    out: dict[int, Candidate] = {}
    payload_gaps: dict[int, str] = {}
    for output in outputs:
        model = by_model[output.valuation_model_id]
        company_id = int(model.company_id)
        if company_id in out:
            continue
        value = _engine_value(output.output_payload)
        if value is None:
            payload = output.output_payload if isinstance(output.output_payload, dict) else {}
            adr = bool(payload.get('adr_ratio')) and (not isinstance(payload.get('listed_share_values'), dict))
            payload_gaps.setdefault(company_id, ENGINE_GAP_ADR if adr else ENGINE_GAP_NON_POSITIVE)
            continue
        out[company_id] = Candidate(value=value, as_of=_as_date(model.created_at), publishable=model.status == 'final', estimated_inputs=_estimated_inputs(output.output_payload), method_label=_method_label(output.output_payload))
    if gaps is not None:
        models_by_company = {int(model.company_id): model for model in models}
        for company_id in ids:
            if company_id in out or company_id in blocks:
                continue
            model = models_by_company.get(company_id)
            if model is None:
                gaps[company_id] = EngineGap(kind=ENGINE_GAP_NO_RUN)
            else:
                gaps[company_id] = EngineGap(kind=payload_gaps.get(company_id, ENGINE_GAP_NO_OUTPUT), as_of=_as_date(model.created_at))
    return (out, blocks)


def _compare(session, ids):
    old_gaps, new_gaps = {}, {}
    expected = _legacy_readings(session, ids, gaps=old_gaps)
    actual = fvs.persisted_engine_readings(session, ids, gaps=new_gaps)
    assert actual == expected
    assert new_gaps == old_gaps
    return actual, new_gaps


@pytest.mark.parametrize('payload', [
    None, [], [1], 'string', 42, True, {},
    {'expected_value': 150}, {'expected_value': '150'},
    {'expected_value': 0, 'base_value': 125},
    {'expected_value': 'Infinity', 'base_value': 125},
    {'adr_ratio': 8, 'expected_value': 150},
    {'adr_ratio': {}, 'expected_value': 150},
    {'adr_ratio': {'x': 1}, 'expected_value': 150},
    {'listed_share_values': [], 'adr_ratio': 8},
    {'listed_share_values': {}, 'adr_ratio': 8},
    {'listed_share_values': {'expected': '240'}, 'adr_ratio': '8'},
    {'listed_share_values': {'expected': {}, 'base': [2]}, 'expected_value': 150},
    {'listed_share_values': {'expected': -1, 'base': 120}},
    {'expected_value': True},
    {'expected_value': 100, 'estimated_inputs': [{'metric': 'debt'}, {}, 'bad', {'metric': 42}],
     'valuation_label': 'DCF multietapa'},
    {'expected_value': 100, 'estimated_inputs': {}, 'valuation_label': 42},
    {'expected_value': 100, 'estimated_inputs': 'bad', 'valuation_label': ''},
])
def test_full_candidate_and_gap_parity(db, payload):
    session, _ = db
    company = _company(session, 'FAIR')
    _output(session, company, payload)
    session.commit()
    session.info['tenant_id'] = 2
    _compare(session, [company.id])


def test_large_trace_bytes_and_zero_output_orm_loads(db):
    session, decoded = db
    company = _company(session, 'BIGFAIR')
    _output(session, company, {'expected_value': 150, 'trace': 'z' * 1_000_000,
                             'estimated_inputs': [{'metric': 'debt'}], 'valuation_label': 'DCF'})
    session.commit()
    session.info['tenant_id'] = 2
    ids = [company.id]
    expected = _legacy_readings(session, ids)
    old_bytes = sum(decoded)
    session.expunge_all()
    decoded.clear()
    statements, loaded = [], []

    def record(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().startswith('SELECT'):
            statements.append(statement)

    def load(target, context):
        loaded.append(target)

    bind = session.get_bind()
    event.listen(bind, 'before_cursor_execute', record)
    event.listen(ValuationOutput, 'load', load)
    try:
        assert fvs.persisted_engine_readings(session, ids) == expected
    finally:
        event.remove(bind, 'before_cursor_execute', record)
        event.remove(ValuationOutput, 'load', load)
    assert old_bytes > 1_000_000
    assert sum(decoded) < 2000
    assert len(statements) == 2
    assert loaded == []


def test_tenant_latest_block_no_output_and_multiple_scenarios(db):
    session, _ = db
    a, b, c, d = [_company(session, name) for name in ('A', 'B', 'C', 'D')]
    for tenant, value in ((2, 150), (5, 75)):
        _output(session, a, {'expected_value': value}, tenant=tenant)
        _output(session, a, {'expected_value': value + 10}, tenant=tenant, version=2, status='draft')
        _output(session, b, {'expected_value': value}, tenant=tenant)
        _output(session, b, {}, tenant=tenant, version=2, status='insufficient_data')
        model = ValuationModel(tenant_id=tenant, company_id=c.id, model_type='dcf', version=1, status='final')
        session.add(model)
    session.flush()
    models = session.scalars(select(ValuationModel).where(ValuationModel.company_id == a.id,
                                                       ValuationModel.version == 2)).all()
    for model in models:
        session.add(ValuationOutput(tenant_id=model.tenant_id, valuation_model_id=model.id,
                                   scenario='bull', output_payload={'expected_value': 999}))
    session.commit()
    ids = [a.id, b.id, c.id, d.id]
    for tenant in (2, 5):
        session.info['tenant_id'] = tenant
        _compare(session, ids)
    assert fvs.persisted_engine_readings(session, []) == ({}, {})
