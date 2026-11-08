"""Notas de analista (#4582) como evidencia del equipo: solo verificadas, por tenant y vigentes.

Y la cadena completa con LLM falso: una nota verificada con supuestos por
segmento alimenta la mezcla de analistas, que guarda el input como estimado.
"""

from __future__ import annotations

import asyncio
import json
from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.analyst_note import AnalystNote
from app.models.entities import Base, Company, Tenant
from app.services.analyst_history_service import AnalystHistory, FirmScore, HorizonSummary
from app.services.declared_input_service import DeclaredInputService
from app.services.expert_team.analyst_blend import run_analyst_blend
from app.services.expert_team.analyst_notes_source import analyst_notes_source
from app.services.expert_team.models import RunContext

T1, T2 = 1, 2
TODAY = date(2026, 11, 5)
URL = "https://www.example-news.com/2026/10/firm-a-initiates"
QUOTE = "Firm A models 160 million paying subscribers by 2033"


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all([Tenant(id=T1, external_id="t1"), Tenant(id=T2, external_id="t2")])
        session.flush()
        session.add(
            Company(
                ticker="SYNTH",
                name="Synthetic Networks",
                exchange="NASDAQ",
                currency="USD",
                sector="Telecom",
                industry="Telecom Services",
                company_type="operating",
                valuation_model="unassigned",
                special_sources=[],
                special_risks=[],
                factor_tags=["subscriber"],
            )
        )
        session.flush()
        yield session


def _note(db, firm: str, *, tenant=T1, verification="verificado", quote=QUOTE, days_ago=10, n=0):
    note = AnalystNote(
        tenant_id=tenant,
        company_id=1,
        ticker="SYNTH",
        firm=firm,
        firm_key=firm.lower(),
        note_date=TODAY - timedelta(days=days_ago),
        action="initiate",
        source_type="news",
        verification=verification,
        quote=quote,
        source_url=URL,
        key_arguments=["adopción vía operadoras"],
        estimates={},
        valuation={},
        segment_assumptions={"subscribers_2033": 160_000_000},
        catalysts=[],
        risks=[],
        links=[],
        extras={},
        dedupe_key=f"{firm}-{tenant}-{verification}-{days_ago}-{n}",
    )
    db.add(note)
    db.flush()
    return note


def _ctx(tenant=T1) -> RunContext:
    return RunContext(tenant_id=tenant, ticker="SYNTH", mode="thesis")


def test_solo_notas_verificadas_vigentes_y_del_tenant(db) -> None:
    _note(db, "Firm A")
    _note(db, "Firm B", verification="rumor_no_verificado")
    _note(db, "Firm C", verification="fragmento", quote=None)
    _note(db, "Firm D", days_ago=500)
    _note(db, "Firm A", tenant=T2, n=1)
    source = analyst_notes_source(db, today=TODAY)
    out = source(_ctx(), ["Firm A", "Firm B", "Firm C", "Firm D"])
    assert [o.source["firm"] for o in out] == ["Firm A"]
    assert out[0].data["text"] == QUOTE and out[0].source["url"] == URL
    assert out[0].data["segment_assumptions"] == {"subscribers_2033": 160_000_000}
    assert source(_ctx(T2), ["Firm B"]) == []
    # Sin lista de firmas: las verificadas recientes del ticker.
    assert [o.source["firm"] for o in source(_ctx(), [])] == ["Firm A"]


def test_cadena_nota_verificada_a_input_estimado(db) -> None:
    _note(db, "Firm A")
    history = AnalystHistory(
        symbol="SYNTH",
        status="available",
        fetched_at=0,
        best_horizon="12m",
        horizons=[
            HorizonSummary(
                horizon="12m",
                months=12,
                matured_targets=30,
                top=[
                    FirmScore(
                        firm="Firm A",
                        samples=8,
                        median_abs_error_pct=20.0,
                        median_bias_pct=3.0,
                        direction_hit_rate=0.6,
                        relative_error=-4.0,
                        peer_scored_samples=8,
                        last_date="2026-10-01",
                        last_target=60.0,
                    )
                ],
            )
        ],
    )

    async def llm(system: str, user: str, max_tokens: int, task: str) -> str:
        ev = [e for e in json.loads(user)["evidence"] if e["source"].get("table") == "analyst_notes"][0]
        return json.dumps(
            {
                "assumptions": [
                    {
                        "input_key": "subscribers",
                        "segment_key": "",
                        "firm": "Firm A",
                        "value": 160_000_000,
                        "unit": "subscribers",
                        "citations": [ev["id"]],
                        "source_url": URL,
                        "source_quote": QUOTE,
                    }
                ]
            }
        )

    result = asyncio.run(
        run_analyst_blend(
            db,
            ctx=_ctx(),
            reasoner=llm,
            history=history,
            extra_sources=[analyst_notes_source(db, today=TODAY)],
            enabled=True,
        )
    )
    assert result.status == "stored", result.problems
    row = DeclaredInputService().current(db, company_id=1, tenant_id=T1)[("subscribers", "")]
    assert (row.method, row.status, row.analyst_firm) == ("analyst", "estimado", "Firm A")
    assert row.source_url == URL and row.source_quote == QUOTE
