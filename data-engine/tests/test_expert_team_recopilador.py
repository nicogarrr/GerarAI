"""«Recopilador»: el experto que hace el inventario de impulsores de valor.

Feature aprobada por Nico (equipo de expertos del Cerebro). LLM falso y
determinista; empresa sintética, nada por ticker. Cubre: salida válida
guardada, salida inválida rechazada sin escribir nada (fail-closed), fuente
obligatoria y verificada contra la evidencia de la corrida, posts de X como
rumor, flag apagado = ni LLM ni escritura, e idempotencia al re-ejecutar.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import ValueDriver
from app.models.entities import Base, Company, Document, DocumentChunk, NewsEvent, Tenant
from app.services import prompt_registry
from app.services.expert_team import default_experts
from app.services.expert_team.models import RunContext
from app.services.expert_team.recopilador import (
    build_recopilador_tools,
    run_recopilador,
    social_source_type,
)
from app.services.expert_team.roster import pipeline_experts, recopilador_expert
from app.services.value_driver_service import ValueDriverService, publication_check

T1, T2 = 1, 2
FILING_URL = "https://www.sec.gov/Archives/edgar/data/1/000001-26-000001.htm"
PASSAGE = (
    "On September 30, 2026 we entered into a definitive agreement with Partner A for a five-year "
    "wholesale contract with minimum commitments of $500 million. We also hold spectrum licenses in "
    "Country B and filed for regulatory approval in Country C."
)
POST_URL = "https://x.com/someone/status/123"


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all([Tenant(id=T1, external_id="t1"), Tenant(id=T2, external_id="t2")])
        session.flush()
        company = Company(
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
            factor_tags=[],
        )
        session.add(company)
        session.flush()
        doc = Document(
            tenant_id=T1,
            company_id=company.id,
            title="Form 10-Q",
            source_type="sec_10q",
            source_url=FILING_URL,
            published_at=datetime(2026, 10, 30, tzinfo=UTC),
            metadata_={},
        )
        session.add(doc)
        session.flush()
        session.add_all(
            [
                DocumentChunk(
                    tenant_id=T1, document_id=doc.id, chunk_index=0, text="Cover page.", metadata_={}
                ),
                DocumentChunk(tenant_id=T1, document_id=doc.id, chunk_index=1, text=PASSAGE, metadata_={}),
            ]
        )
        session.add(
            NewsEvent(
                tenant_id=T1,
                company_id=company.id,
                date=datetime.now(UTC).date(),
                title="Rumour: Partner D close to signing",
                summary="A post says Partner D signed a deal.",
                source="X",
                url=POST_URL,
            )
        )
        session.flush()
        yield session


def _ctx(tenant: int = T1) -> RunContext:
    return RunContext(tenant_id=tenant, ticker="SYNTH", mode="thesis")


def _evidence_ids(user: str) -> dict[str, str]:
    """url → id de la evidencia que el LLM recibe (como haría el modelo)."""
    payload = json.loads(user)
    out: dict[str, str] = {}
    for ev in payload["evidence"]:
        url = ev["source"].get("url")
        if url and url not in out:
            out[url] = ev["id"]
    return out


def _good_drivers(ids: dict[str, str]) -> list[dict]:
    return [
        {
            "driver_key": "contrato_mayorista_socio_a",
            "category": "contrato",
            "name": "Contrato mayorista con el socio A",
            "status": "firmado",
            "economics": {"amount": 500, "currency": "USD", "amount_usd": 500_000_000, "term": "5 años"},
            "timing": "2026-2031",
            "source_type": "filing",
            "evidence": "oficial",
            "citations": [ids[FILING_URL]],
            "source_url": FILING_URL,
            "source_quote": "we entered into a definitive agreement with Partner A",
            "as_of": "2026-09-30",
            "headline": True,
            "treatment": "pendiente",
        },
        {
            "driver_key": "espectro_pais_b",
            "category": "activo",
            "name": "Licencias de espectro en el país B",
            "status": "firmado",
            "economics": {},
            "source_type": "filing",
            "evidence": "oficial",
            "citations": [ids[FILING_URL]],
            "source_url": FILING_URL,
            "source_quote": "We also hold spectrum licenses in Country B",
            "headline": False,
        },
        {
            "driver_key": "socio_d_rumor",
            "category": "contrato",
            "name": "Posible acuerdo con el socio D",
            "status": "firmado",  # el modelo se equivoca: es un post en X
            "economics": {},
            "source_type": "prensa",
            "evidence": "oficial",
            "citations": [ids[POST_URL]],
            "source_url": POST_URL,
            "source_quote": "A post says Partner D signed a deal.",
            "headline": True,
        },
    ]


class FakeLLM:
    def __init__(self, answers):
        self.answers = list(answers)
        self.calls: list[tuple[str, str]] = []

    async def __call__(self, system: str, user: str, max_tokens: int, task: str) -> str:
        self.calls.append((system, user))
        answer = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        return str(answer(user) if callable(answer) else answer)


def _good(user: str) -> str:
    return json.dumps({"drivers": _good_drivers(_evidence_ids(user))})


def _run(db, llm, **kw):
    return asyncio.run(
        run_recopilador(db, ctx=kw.pop("ctx", _ctx()), reasoner=llm, enabled=kw.pop("enabled", True), **kw)
    )


# ------------------------------------------------------------------ registro
def test_recopilador_registrado_con_prompt_versionado() -> None:
    spec = recopilador_expert()
    assert [s.name for s in pipeline_experts()][0] == "recopilador"
    definition = prompt_registry.PROMPTS[spec.prompt_name]
    assert definition.version == "recopilador-v1"
    assert "español" in definition.text
    # No entra en el equipo de chat/tesis: su salida es el inventario, no opiniones.
    assert "recopilador" not in {s.name for s in default_experts()}


def test_herramientas_solo_de_lectura_y_con_documentos(db) -> None:
    tools = build_recopilador_tools(db)
    assert set(tools) == set(recopilador_expert().tools)
    passages = tools["company_documents"].fn(_ctx())
    assert [p.data["text"] for p in passages] == [PASSAGE]  # solo el pasaje con señales
    assert passages[0].source["url"] == FILING_URL
    assert tools["company_documents"].fn(_ctx(T2)) == []  # otro tenant no ve los documentos


# ------------------------------------------------------------------ flag
def test_flag_apagado_ni_llm_ni_escritura(db) -> None:
    llm = FakeLLM([_good])
    result = _run(db, llm, enabled=False)
    assert result.status == "disabled"
    assert llm.calls == []
    assert db.query(ValueDriver).count() == 0


def test_flag_por_defecto_es_el_de_la_config(db, monkeypatch) -> None:
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "expert_team_enabled", False, raising=False)
    llm = FakeLLM([_good])
    result = asyncio.run(run_recopilador(db, ctx=_ctx(), reasoner=llm))
    assert result.status == "disabled" and llm.calls == []


# ------------------------------------------------------------------ salida válida
def test_salida_valida_se_guarda_y_el_post_de_x_es_rumor(db) -> None:
    llm = FakeLLM([_good])
    result = _run(db, llm)
    assert result.status == "stored", result.problems
    assert result.stored == 3
    rows = ValueDriverService().current(db, company_id=1, tenant_id=T1)
    assert set(rows) == {"contrato_mayorista_socio_a", "espectro_pais_b", "socio_d_rumor"}
    rumour = rows["socio_d_rumor"]
    assert (rumour.source_type, rumour.status, rumour.evidence) == ("redes", "rumor", "rumor")
    assert rows["contrato_mayorista_socio_a"].document_id is not None
    assert all(r.treatment == "pendiente" for r in rows.values())
    # Firmado, material y sin tratar → la puerta bloquea hasta que el valorador lo trate.
    check = publication_check(rows.values(), market_cap_usd=10_000_000_000)
    assert not check.publishable
    assert [b.driver_key for b in check.blocking] == ["contrato_mayorista_socio_a"]
    # El otro tenant no ve nada.
    assert ValueDriverService().current(db, company_id=1, tenant_id=T2) == {}


def test_reejecutar_es_idempotente(db) -> None:
    _run(db, FakeLLM([_good]))
    again = _run(db, FakeLLM([_good]))
    assert again.status == "stored"
    assert (again.stored, again.unchanged) == (0, 3)
    assert db.query(ValueDriver).count() == 3


def test_evidencia_pasa_al_modelo_con_el_contrato(db) -> None:
    llm = FakeLLM([_good])
    _run(db, llm)
    system, user = llm.calls[0]
    assert "drivers" in system and "pendiente" in system
    tools = {ev["tool"] for ev in json.loads(user)["evidence"]}
    assert {"company_documents", "news_events"} <= tools


# ------------------------------------------------------------------ fail-closed
def _bad(mutator):
    def answer(user: str) -> str:
        drivers = _good_drivers(_evidence_ids(user))
        mutator(drivers)
        return json.dumps({"drivers": drivers})

    return answer


@pytest.mark.parametrize(
    ("mutator", "fragment"),
    [
        (lambda d: d[0].update(source_url=None), "URL"),
        (lambda d: d[0].update(source_url="https://otra.example.com/x"), "URL no es la de la evidencia"),
        (lambda d: d[0].update(citations=[]), "no cita evidencia"),
        (lambda d: d[0].update(citations=["ev-999"]), "no cita evidencia"),
        (lambda d: d[0].update(source_quote="we signed a deal for 900 million"), "cita no aparece"),
        (lambda d: d[0].update(category="inventada"), "categoría"),
        (lambda d: d[1].update(driver_key=d[0]["driver_key"]), "repetida"),
    ],
)
def test_salida_invalida_no_escribe_nada(db, mutator, fragment) -> None:
    llm = FakeLLM([_bad(mutator)])
    result = _run(db, llm)
    assert result.status == "rejected"
    assert any(fragment in p for p in result.problems), result.problems
    assert result.llm_calls == 2  # un reintento con los problemas
    assert "problems_previous_answer" in json.loads(llm.calls[1][1])
    assert db.query(ValueDriver).count() == 0


@pytest.mark.parametrize("answer", ["no es json", json.dumps({"otra": 1}), json.dumps({"drivers": "x"})])
def test_json_invalido_rechazado(db, answer) -> None:
    result = _run(db, FakeLLM([answer]))
    assert result.status == "rejected"
    assert db.query(ValueDriver).count() == 0


def test_reintento_con_salida_corregida_se_guarda(db) -> None:
    llm = FakeLLM([_bad(lambda d: d[0].update(source_quote="inventada")), _good])
    result = _run(db, llm)
    assert result.status == "stored"
    assert result.llm_calls == 2


def test_llm_que_falla_no_escribe(db) -> None:
    async def boom(*_a, **_k):
        raise RuntimeError("sin presupuesto")

    result = _run(db, boom)
    assert result.status == "error"
    assert db.query(ValueDriver).count() == 0


def test_sin_evidencia_no_llama_al_modelo(db) -> None:
    llm = FakeLLM([_good])
    result = _run(db, llm, ctx=_ctx(T2))
    assert result.status == "no_data"
    assert llm.calls == []


def test_empresa_desconocida(db) -> None:
    result = _run(db, FakeLLM([_good]), ctx=RunContext(tenant_id=T1, ticker="NOPE"))
    assert result.status == "no_company"


# ------------------------------------------------------------------ redes y foros
@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://x.com/a/status/1", "redes"),
        ("https://www.twitter.com/a", "redes"),
        ("https://mobile.twitter.com/a", "redes"),
        ("https://www.reddit.com/r/stocks/1", "foro"),
        ("https://stocktwits.com/x", "foro"),
        ("https://www.sec.gov/x", None),
        ("https://box.com/x", None),  # «x.com» solo como dominio entero
        (None, None),
    ],
)
def test_social_source_type(url, expected) -> None:
    assert social_source_type(url) == expected
