"""El trabajo del equipo de expertos llega a la tesis v2 como entrada citada (que no se pierda nada).

Antes (8-nov-2026): el Recopilador, la mezcla de analistas y el escéptico corrían (si se encendían) y la tesis
v2 no leía nada de lo que producían; el escéptico ni siquiera se guardaba.
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import DeclaredInputValue, Tenant
from app.models.entities import Base, Company
from app.services.declared_input_service import DeclaredInput, DeclaredInputService
from app.services.expert_team import thesis_v2 as T
from app.services.expert_team import thesis_v2_experts as X
from tests.test_thesis_v2 import _ctx

BELIEF = {"driver_key": "att_contract", "hace_falta_creer": "que el contrato mayorista genere ingresos",
          "postura": "abierta", "motivo": "", "dato_que_lo_cierra": "ingresos reconocidos en el próximo 10-Q",
          "inputs": ["revenue_growth"], "fuente": "https://sec.gov/10q", "cita": "definitive commercial agreement"}
PIPELINE = {"stages": [{"name": "recopilador", "status": "stored"}, {"name": "mezcla_analistas", "status": "stored"},
                       {"name": "esceptico", "status": "ok", "beliefs": [BELIEF]}],
            "consensus": 40.0, "consensus_source": "https://example.com/consenso"}


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Tenant(id=1, external_id="t1"))
        session.flush()
        session.info["tenant_id"] = 1
        yield session


def _company(db):
    c = Company(ticker="SYNTH", name="Synth", exchange="NASDAQ", currency="USD", sector="Tech", industry="Soft",
                company_type="operating", valuation_model="unassigned", special_sources=[], special_risks=[],
                factor_tags=[])
    db.add(c)
    db.flush()
    return c


def test_salida_del_escepetico_y_supuestos_de_analistas_se_guardan_y_se_leen(db):
    c = _company(db)
    assert X.store_pipeline(db, c.id, PIPELINE) is True
    assert X.store_pipeline(db, c.id, PIPELINE) is False  # misma salida: no duplica
    DeclaredInputService().upsert(db, company=c, tenant_id=1, item=DeclaredInput(
        input_key="revenue_growth", base=Decimal("0.25"), unit="ratio", method="analyst", analyst_firm="Firma A",
        source_url="https://example.com/nota", source_quote="We model revenue growth of 25% in 2027.",
        as_of=date(2026, 10, 1)))
    block = X.expert_block(db, c, 1)
    assert block["esceptico"][0]["postura"] == "abierta"
    assert block["supuestos_de_analistas"][0]["firma"] == "Firma A"
    assert block["etapas"]["esceptico"] == "ok"
    m = X.expert_markers(block)
    assert m["expertos.analista.1.valor"] == "25,0 %"
    payload = X.expert_payload(block)
    assert payload["supuestos_de_analistas"][0]["valor"] == "{{expertos.analista.1.valor}}"
    assert "25" not in json.dumps(payload["supuestos_de_analistas"][0]["valor"])
    rows = db.query(DeclaredInputValue).filter_by(input_key=X.EXPERTS_KEY, superseded_at=None).all()
    assert len(rows) == 1


def test_la_tesis_v2_recibe_el_trabajo_del_equipo_y_lo_pinta():
    block = {"impulsores": [{"clave": "att_contract", "nombre": "Contrato AT&T", "estado": "firmado",
                             "fuente": "https://sec.gov/8k", "cita": "definitive commercial agreement"}],
             "supuestos_de_analistas": [{"input": "revenue_growth", "firma": "Firma A", "base": 0.25, "bajo": None,
                                         "alto": None, "unidad": "ratio", "fuente": "https://x", "cita": "q",
                                         "fecha": "2026-10-01"}],
             "esceptico": [BELIEF], "etapas": {}, "fecha": "2026-11-08"}
    plain = _ctx()
    ctx = replace(plain, experts=block)
    assert T.thesis_fingerprint(ctx) != T.thesis_fingerprint(plain)  # trabajo nuevo: se rehace
    seen = []

    async def reasoner(system, user, max_tokens, task):
        payload = json.loads(user)
        seen.append(payload["equipo_de_expertos"])
        keys = [s["clave"] for s in payload["secciones"]]
        text = ("El escéptico deja abierta la tesis del contrato hasta ver ingresos; la firma estima "
                "{{expertos.analista.1.valor}} de crecimiento.")
        return json.dumps({"sections": dict.fromkeys(keys, text), "probabilidades": "sesgo_bajista",
                           "probabilidades_razon": "riesgo"})

    res = asyncio.run(T.write_thesis(reasoner=reasoner, ctx=ctx))
    assert res.status == "ok"
    assert seen[0]["juicios_del_escéptico"][0]["postura"] == "abierta"
    assert seen[0]["impulsores_del_recopilador"][0]["nombre"] == "Contrato AT&T"
    shown = T.present(ctx, {"sections": res.sections}, T.thesis_markers(ctx))
    riesgos = next(s for s in shown["sections"] if s["key"] == "riesgos")
    table = next(t for t in riesgos["tables"] if t["title"].startswith("Equipo de expertos"))
    assert table["rows"][0][:4] == ["Contrato AT&T", "firmado", BELIEF["hace_falta_creer"], "abierta"]
    assert table["links"][0] == "https://sec.gov/10q"
    assert "25,0 %" in riesgos["text"]
    # Sin trabajo del equipo no aparece la tabla vacía.
    bare = T.present(plain, {"sections": res.sections}, T.thesis_markers(plain))
    assert not any(t["title"].startswith("Equipo de expertos") for s in bare["sections"] for t in s["tables"])


def test_valoracion_no_proyectable_tambien_pinta_la_tabla_del_equipo():
    """Antes (8-nov-2026, BN con el modelo de la app): con la valoración «not_meaningful» las tablas salían por
    la rama corta sin «expertos» y la tesis entera caía con KeyError al presentarla."""
    ctx = _ctx()
    val = {"status": "not_meaningful", "reason": "PER fuera del rango", "starting_point": ctx.valuation["starting_point"],
           "scenarios": {}, "discount_rate": 0.09}
    ctx2 = replace(ctx, valuation={**ctx.valuation, **val}, experts={"esceptico": [BELIEF]})
    assert T.tables(ctx2)["expertos"]["rows"]
    assert T.tables(replace(ctx2, experts=None))["expertos"]["rows"] == []
