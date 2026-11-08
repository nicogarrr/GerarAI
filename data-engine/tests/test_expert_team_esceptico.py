"""«Escéptico»: qué hace falta creer por impulsor, con postura y cita verificada.

Feature aprobada por Nico (equipo de expertos). LLM falso y determinista;
empresa sintética, nada por ticker. Cubre: flag apagado, sin inventario, lee
la puerta de publicación y los argumentos de la mezcla de analistas, juicios
válidos, fail-closed (cita, impulsor, postura, cobertura de lo que bloquea),
reintento, fallo del LLM y etiquetas para la conciliación con el consenso.
"""

from __future__ import annotations

import asyncio
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, Tenant
from app.services import prompt_registry
from app.services.declared_input_service import DeclaredInput, DeclaredInputService
from app.services.expert_team.esceptico import (
    DriverBelief,
    labels_for_reconciliation,
    run_esceptico,
)
from app.services.expert_team.models import RunContext, ToolOutput
from app.services.expert_team.roster import esceptico_expert, pipeline_experts
from app.services.value_driver_service import ValueDriverItem, ValueDriverService

T1, T2 = 1, 2
FILING_URL = "https://www.sec.gov/Archives/edgar/data/1/000001-26-000001.htm"
NOTE_URL = "https://www.example-news.com/2026/10/firm-a"
CONTRACT_QUOTE = "a five-year wholesale contract with minimum commitments of $500 million"
SPECTRUM_QUOTE = "We also hold spectrum licenses in Country B"
ANALYST_QUOTE = "Firm A models 160 million paying subscribers by 2033"


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
            factor_tags=["subscriber"],
        )
        session.add(company)
        session.flush()
        ValueDriverService().upsert_many(
            session,
            company=company,
            tenant_id=T1,
            items=[
                ValueDriverItem(
                    driver_key="contrato_mayorista_socio_a",
                    category="contrato",
                    name="Contrato mayorista con el socio A",
                    status="firmado",
                    source_type="filing",
                    evidence="oficial",
                    source_url=FILING_URL,
                    source_quote=CONTRACT_QUOTE,
                    economics={"amount_usd": 500_000_000},
                    headline=True,
                ),
                ValueDriverItem(
                    driver_key="espectro_pais_b",
                    category="activo",
                    name="Licencias de espectro en el país B",
                    status="firmado",
                    source_type="filing",
                    evidence="oficial",
                    source_url=FILING_URL,
                    source_quote=SPECTRUM_QUOTE,
                    treatment="suelo",
                ),
            ],
        )
        DeclaredInputService().upsert(
            session,
            company=company,
            tenant_id=T1,
            item=DeclaredInput(
                input_key="subscribers",
                base=160_000_000,
                unit="subscribers",
                method="analyst",
                analyst_firm="Firm A",
                source_url=NOTE_URL,
                source_quote=ANALYST_QUOTE,
                metadata={
                    "metodo": "mezcla de analistas",
                    "firmas": [
                        {"firma": "Firm A", "valor": 160_000_000, "fuente": NOTE_URL, "cita": ANALYST_QUOTE}
                    ],
                },
            ),
        )
        session.flush()
        yield session


def _ctx(tenant: int = T1, ticker: str = "SYNTH") -> RunContext:
    return RunContext(tenant_id=tenant, ticker=ticker, mode="thesis")


def _ids(user: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for ev in json.loads(user)["evidence"]:
        key = ev["source"].get("driver_key") or ev["source"].get("input")
        out.setdefault(key, ev["id"])
    return out


def _good_items(ids: dict[str, str]) -> list[dict]:
    return [
        {
            "driver_key": "contrato_mayorista_socio_a",
            "hace_falta_creer": "que el socio A cumpla los compromisos mínimos y renueve tras cinco años",
            "postura": "abierta",
            "motivo": "",
            "dato_que_lo_cierra": "ingresos reconocidos del contrato en el próximo 10-Q",
            "inputs": ["subscribers"],
            "citations": [ids["contrato_mayorista_socio_a"], ids["subscribers"]],
            "source_quote": CONTRACT_QUOTE,
        },
        {
            "driver_key": "espectro_pais_b",
            "hace_falta_creer": "que el espectro se pueda vender o usar en el país B",
            "postura": "aceptamos",
            "motivo": "licencias en vigor",
            "citations": [ids["espectro_pais_b"]],
            "source_quote": SPECTRUM_QUOTE,
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
    return json.dumps({"beliefs": _good_items(_ids(user))})


def _bad(mutator):
    def answer(user: str) -> str:
        items = _good_items(_ids(user))
        mutator(items)
        return json.dumps({"beliefs": items})

    return answer


def _run(db, llm, **kw):
    kw.setdefault("market_cap_usd", 10_000_000_000)
    return asyncio.run(
        run_esceptico(db, ctx=kw.pop("ctx", _ctx()), reasoner=llm, enabled=kw.pop("enabled", True), **kw)
    )


# ------------------------------------------------------------------ registro y flag
def test_rol_registrado_con_prompt_versionado() -> None:
    spec = esceptico_expert()
    assert [s.name for s in pipeline_experts()] == ["recopilador", "mezcla_analistas", "esceptico"]
    assert prompt_registry.PROMPTS[spec.prompt_name].version == "esceptico-v1"


def test_flag_apagado_no_llama(db) -> None:
    llm = FakeLLM([_good])
    assert _run(db, llm, enabled=False).status == "disabled"
    assert llm.calls == []


def test_flag_por_defecto_es_el_de_la_config(db, monkeypatch) -> None:
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "expert_team_enabled", False, raising=False)
    llm = FakeLLM([_good])
    assert asyncio.run(run_esceptico(db, ctx=_ctx(), reasoner=llm)).status == "disabled"
    assert llm.calls == []


def test_sin_inventario_no_llama(db) -> None:
    llm = FakeLLM([_good])
    result = _run(db, llm, ctx=_ctx(T2))
    assert result.status == "no_data" and llm.calls == []


def test_empresa_desconocida(db) -> None:
    assert _run(db, FakeLLM([_good]), ctx=_ctx(ticker="NOPE")).status == "no_company"


# ------------------------------------------------------------------ salida válida
def test_juicios_validos_con_puerta_y_argumentos(db) -> None:
    llm = FakeLLM([_good])
    result = _run(db, llm, consensus_reconciliation={"status": "revisar", "main_driver": "margin"})
    assert result.status == "ok", result.problems
    assert [b.driver_key for b in result.beliefs] == ["contrato_mayorista_socio_a", "espectro_pais_b"]
    contract = result.beliefs[0]
    assert contract.posture == "abierta" and "10-Q" in (contract.closing_data or "")
    assert result.publication is not None and not result.publication.publishable
    payload = json.loads(llm.calls[0][1])
    assert payload["publication_check"]["blocking"][0]["driver_key"] == "contrato_mayorista_socio_a"
    assert payload["consensus_reconciliation"]["status"] == "revisar"
    tools = {ev["tool"] for ev in payload["evidence"]}
    assert tools == {"value_drivers", "analyst_arguments"}
    analyst = [ev for ev in payload["evidence"] if ev["tool"] == "analyst_arguments"][0]
    assert analyst["data"]["firm"] == "Firm A" and ANALYST_QUOTE in analyst["data"]["text"]
    assert result.as_dict()["beliefs"][0]["hace_falta_creer"].startswith("que el socio A")


def test_fuente_extra_de_argumentos(db) -> None:
    seen: list[list[str]] = []

    def notes(ctx, firms):
        seen.append(list(firms))
        return [
            ToolOutput(
                source={"table": "analyst_notes", "url": "https://n.example.com/1"}, data={"text": "x"}
            )
        ]

    llm = FakeLLM([_good])
    _run(db, llm, extra_sources=[notes])
    assert seen == [["Firm A"]]
    assert any(ev["source"].get("table") == "analyst_notes" for ev in json.loads(llm.calls[0][1])["evidence"])


# ------------------------------------------------------------------ fail-closed
@pytest.mark.parametrize(
    ("mutator", "fragment"),
    [
        (lambda i: i[0].update(source_quote="the partner signed for $900 million"), "cita no aparece"),
        (lambda i: i[0].update(citations=[]), "no cita evidencia"),
        (lambda i: i[0].update(citations=["ev-999"]), "no cita evidencia"),
        (lambda i: i[0].update(driver_key="inventado"), "no es un impulsor del inventario"),
        (lambda i: i[0].update(postura="quizá"), "postura no válida"),
        (lambda i: i[0].update(dato_que_lo_cierra=None), "exige el dato que la cierra"),
        (lambda i: i[1].update(postura="rechazamos", motivo=""), "rechazar exige motivo"),
        (lambda i: i[0].update(hace_falta_creer=""), "qué hace falta creer"),
        (lambda i: i.pop(0), "bloquean la publicación sin juicio"),
        (lambda i: i.append(dict(i[1])), "repetido"),
    ],
)
def test_salida_invalida_rechazada(db, mutator, fragment) -> None:
    llm = FakeLLM([_bad(mutator)])
    result = _run(db, llm)
    assert result.status == "rejected"
    assert any(fragment in p for p in result.problems), result.problems
    assert result.llm_calls == 2 and result.beliefs == []
    assert "problems_previous_answer" in json.loads(llm.calls[1][1])


@pytest.mark.parametrize("answer", ["no es json", json.dumps({"otra": 1}), json.dumps({"beliefs": "x"})])
def test_json_invalido_rechazado(db, answer) -> None:
    assert _run(db, FakeLLM([answer])).status == "rejected"


def test_reintento_corregido(db) -> None:
    llm = FakeLLM([_bad(lambda i: i[0].update(source_quote="inventada")), _good])
    result = _run(db, llm)
    assert result.status == "ok" and result.llm_calls == 2


def test_llm_que_falla(db) -> None:
    async def boom(*_a, **_k):
        raise RuntimeError("sin presupuesto")

    assert _run(db, boom).status == "error"


# ------------------------------------------------------------------ etiquetas para la conciliación
def _belief(key: str, posture: str, inputs: tuple[str, ...], **kw) -> DriverBelief:
    return DriverBelief(driver_key=key, must_believe=f"creer {key}", posture=posture, inputs=inputs, **kw)


def test_etiquetas_para_la_conciliacion() -> None:
    labels = labels_for_reconciliation(
        [
            _belief("a", "rechazamos", ("terminal_growth",), reason="10 % perpetuo no"),
            _belief("b", "abierta", ("growth",), closing_data="adopción real del 3T"),
            _belief("c", "aceptamos", ("growth",)),
            _belief("d", "aceptamos", ("margin",), reason="margen de pares"),
        ]
    )
    assert (labels["terminal_growth"].label, labels["terminal_growth"].reason) == (
        "rechazamos",
        "10 % perpetuo no",
    )
    assert labels["growth"].label == "abierta" and "juicios distintos" in labels["growth"].reason
    assert labels["margin"].label == "aceptamos"
    single_open = labels_for_reconciliation([_belief("b", "abierta", ("wacc",), closing_data="dato X")])
    assert single_open["wacc"].reason == "dato X"
