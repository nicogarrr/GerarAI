"""«Mezcla de analistas»: rellena los huecos del modelo con las mejores firmas.

Feature aprobada por Nico (4-nov-2026: inferir los inputs que faltan, sin
números a mano). LLM falso y determinista; empresa sintética con marco de
suscripción (por etiqueta), nada por ticker. Cubre: datos completos = ni LLM ni
escritura, flag apagado, solo firmas que baten a sus pares, cita literal y
firma verificadas, solo huecos, mediana y rango, límites económicos,
precedencia frente a un dato oficial, idempotencia y fail-closed.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import DeclaredInputValue
from app.models.entities import Base, Company, Document, DocumentChunk, FinancialFact, NewsEvent, Tenant
from app.services import prompt_registry
from app.services.analyst_history_service import AnalystHistory, FirmScore, HorizonSummary
from app.services.declared_input_service import DeclaredInput, DeclaredInputService
from app.services.expert_team.analyst_blend import (
    AnalystAssumption,
    analyst_passages_tool,
    blend_assumptions,
    economic_limit_violation,
    qualifying_firms,
    run_analyst_blend,
)
from app.services.expert_team.models import RunContext, ToolOutput
from app.services.expert_team.roster import analyst_blend_expert, pipeline_experts

T1, T2 = 1, 2
NOTE_URL = "https://www.example-news.com/2026/10/firm-a-raises-target"
NOTE2_URL = "https://www.example-news.com/2026/10/firm-b-initiates"
PASSAGE_A = (
    "Firm A raised its price target to $60. Firm A models 160 million paying subscribers by 2033 "
    "and monthly ARPU of $1.50, with churn of 2% per month and a 10% perpetual growth rate."
)
PASSAGE_B = "Firm B initiated coverage with a $55 target, assuming 120 million subscribers by 2033."
PASSAGE_C = "Firm C (laggard) sees 400 million subscribers by 2033."


def _score(firm: str, rel: float | None, *, n: int = 8, small: bool = False) -> FirmScore:
    return FirmScore(
        firm=firm,
        samples=n,
        median_abs_error_pct=20.0,
        median_bias_pct=5.0,
        direction_hit_rate=0.6,
        relative_error=rel,
        peer_scored_samples=n,
        small_sample=small,
        last_date="2026-10-01",
        last_target=50.0,
    )


def _history(top: list[FirmScore] | None = None, *, status: str = "available") -> AnalystHistory:
    top = top if top is not None else [_score("Firm A", -6.0), _score("Firm B", -2.5), _score("Firm C", 4.0)]
    return AnalystHistory(
        symbol="SYNTH",
        status=status,  # type: ignore[arg-type]
        fetched_at=0,
        best_horizon="12m",
        horizons=[HorizonSummary(horizon="12m", months=12, matured_targets=40, top=top)],
    )


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
        doc = Document(
            tenant_id=T1,
            company_id=company.id,
            title="Analyst roundup",
            source_type="press",
            source_url=NOTE_URL,
            published_at=datetime(2026, 10, 20, tzinfo=UTC),
            metadata_={},
        )
        session.add(doc)
        session.flush()
        session.add_all(
            [
                DocumentChunk(tenant_id=T1, document_id=doc.id, chunk_index=0, text="Cover.", metadata_={}),
                DocumentChunk(tenant_id=T1, document_id=doc.id, chunk_index=1, text=PASSAGE_A, metadata_={}),
                DocumentChunk(tenant_id=T1, document_id=doc.id, chunk_index=2, text=PASSAGE_C, metadata_={}),
            ]
        )
        session.add(
            NewsEvent(
                tenant_id=T1,
                company_id=company.id,
                date=datetime.now(UTC).date(),
                title="Firm B initiates coverage",
                summary=PASSAGE_B,
                source="Example News",
                url=NOTE2_URL,
            )
        )
        session.flush()
        yield session


def _ctx(tenant: int = T1, ticker: str = "SYNTH") -> RunContext:
    return RunContext(tenant_id=tenant, ticker=ticker, mode="thesis")


def _ids(user: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for ev in json.loads(user)["evidence"]:
        url = ev["source"].get("url")
        if url and url not in out:
            out[url] = ev["id"]
    return out


def _good_items(ids: dict[str, str]) -> list[dict]:
    return [
        {
            "input_key": "subscribers",
            "segment_key": "",
            "firm": "Firm A",
            "value": 160_000_000,
            "unit": "subscribers",
            "citations": [ids[NOTE_URL]],
            "source_url": NOTE_URL,
            "source_quote": "Firm A models 160 million paying subscribers by 2033",
            "as_of": "2026-10-20",
        },
        {
            "input_key": "subscribers",
            "segment_key": "",
            "firm": "Firm B",
            "value": 120_000_000,
            "unit": "subscribers",
            "citations": [ids[NOTE2_URL]],
            "source_url": NOTE2_URL,
            "source_quote": "assuming 120 million subscribers by 2033",
            "as_of": "2026-10-25",
        },
        {
            "input_key": "monthly_arpu",
            "segment_key": "",
            "firm": "Firm A",
            "value": 1.5,
            "unit": "USD/subscriber/month",
            "citations": [ids[NOTE_URL]],
            "source_url": NOTE_URL,
            "source_quote": "monthly ARPU of $1.50",
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
    return json.dumps({"assumptions": _good_items(_ids(user))})


def _bad(mutator):
    def answer(user: str) -> str:
        items = _good_items(_ids(user))
        mutator(items)
        return json.dumps({"assumptions": items})

    return answer


def _run(db, llm, **kw):
    kw.setdefault("history", _history())
    return asyncio.run(
        run_analyst_blend(db, ctx=kw.pop("ctx", _ctx()), reasoner=llm, enabled=kw.pop("enabled", True), **kw)
    )


def _rows(db, tenant=T1):
    return DeclaredInputService().current(db, company_id=1, tenant_id=tenant)


# ------------------------------------------------------------------ registro
def test_rol_registrado_con_prompt_versionado() -> None:
    spec = analyst_blend_expert()
    assert [s.name for s in pipeline_experts()] == ["recopilador", "mezcla_analistas"]
    definition = prompt_registry.PROMPTS[spec.prompt_name]
    assert definition.version == "mezcla-analistas-v1"
    assert "huecos" in definition.text


# ------------------------------------------------------------------ firmas
def test_solo_cuentan_las_firmas_que_baten_a_sus_pares() -> None:
    history = _history(
        [
            _score("Firm B", -2.5),
            _score("Firm A", -6.0),
            _score("Firm C", 4.0),  # peor que sus pares
            _score("Firm D", -9.0, n=3, small=True),  # muestra pequeña
            _score("Firm E", None),  # sin pares
        ]
    )
    assert [f.firm for f in qualifying_firms(history)] == ["Firm A", "Firm B"]
    assert qualifying_firms(_history(status="unavailable")) == []
    assert qualifying_firms(None) == []


# ------------------------------------------------------------------ flag y datos completos
def test_flag_apagado_ni_llm_ni_escritura(db) -> None:
    llm = FakeLLM([_good])
    result = _run(db, llm, enabled=False)
    assert result.status == "disabled"
    assert llm.calls == [] and db.query(DeclaredInputValue).count() == 0


def test_flag_por_defecto_es_el_de_la_config(db, monkeypatch) -> None:
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "expert_team_enabled", False, raising=False)
    llm = FakeLLM([_good])
    result = asyncio.run(run_analyst_blend(db, ctx=_ctx(), reasoner=llm, history=_history()))
    assert result.status == "disabled" and llm.calls == []


def test_empresa_con_datos_completos_no_usa_analistas(db) -> None:
    company = db.get(Company, 1)
    for metric in ("subscribers", "monthly_arpu", "churn", "retention"):
        db.add(
            FinancialFact(
                tenant_id=T1,
                company_id=company.id,
                metric=metric,
                value=Decimal("1000"),
                unit="x",
                period="2025:FY",
                fiscal_year=2025,
                source_type="SEC",
            )
        )
    db.flush()
    llm = FakeLLM([_good])

    async def no_history(_symbol):  # pragma: no cover - no debe llamarse
        raise AssertionError("con datos completos no se consulta el ranking")

    result = _run(db, llm, history=None, load_history=no_history)
    assert result.status == "full_data"
    assert llm.calls == [] and db.query(DeclaredInputValue).count() == 0


def test_sin_firmas_que_cuenten_no_mezcla(db) -> None:
    llm = FakeLLM([_good])
    result = _run(db, llm, history=_history([_score("Firm C", 4.0)]))
    assert result.status == "no_firms"
    assert llm.calls == [] and db.query(DeclaredInputValue).count() == 0


def test_ranking_que_falla_no_mezcla(db) -> None:
    async def boom(_symbol):
        raise RuntimeError("yahoo caído")

    result = _run(db, FakeLLM([_good]), history=None, load_history=boom)
    assert result.status == "no_firms"
    assert db.query(DeclaredInputValue).count() == 0


# ------------------------------------------------------------------ evidencia
def test_evidencia_solo_de_las_firmas_que_cuentan_y_del_tenant(db) -> None:
    tool = analyst_passages_tool(db, ["Firm A", "Firm B"])
    out = asyncio.run(tool.fn(_ctx()))
    texts = [o.data["text"] for o in out]
    assert PASSAGE_A in texts and PASSAGE_B in texts
    assert PASSAGE_C not in texts  # la firma rezagada no entra
    assert asyncio.run(tool.fn(_ctx(T2))) == []


def test_fuente_extra_entra_como_evidencia(db) -> None:
    def notes(ctx, firms):
        return [
            ToolOutput(
                source={"table": "analyst_notes", "url": "https://n.example.com/1"}, data={"text": "x"}
            )
        ]

    out = asyncio.run(analyst_passages_tool(db, ["Firm A"], extra_sources=[notes]).fn(_ctx()))
    assert any(o.source.get("table") == "analyst_notes" for o in out)


def test_sin_evidencia_no_llama_al_modelo(db) -> None:
    llm = FakeLLM([_good])
    result = _run(db, llm, history=_history([_score("Firm Z", -3.0)]))
    assert result.status == "no_data" and llm.calls == []


# ------------------------------------------------------------------ salida válida
def test_mezcla_se_guarda_como_estimado_de_analistas(db) -> None:
    llm = FakeLLM([_good])
    result = _run(db, llm)
    assert result.status == "stored", result.problems
    assert result.stored == 2
    rows = _rows(db)
    subs = rows[("subscribers", "")]
    assert (subs.method, subs.status) == ("analyst", "estimado")
    assert float(subs.base) == 140_000_000  # mediana de 160 y 120
    assert (float(subs.low), float(subs.high)) == (120_000_000, 160_000_000)
    assert subs.analyst_firm == "Firm A, Firm B"  # por ranking
    assert subs.source_url == NOTE_URL and "160 million" in subs.source_quote
    assert subs.metadata_["metodo"] == "mezcla de analistas"
    assert [f["firma"] for f in subs.metadata_["firmas"]] == ["Firm A", "Firm B"]
    arpu = rows[("monthly_arpu", "")]
    assert float(arpu.base) == 1.5 and arpu.metadata_["agregado"] == "una firma"
    # Los huecos sin supuesto siguen siendo huecos; el otro tenant no ve nada.
    assert ("churn", "") not in rows
    assert _rows(db, T2) == {}
    system, user = llm.calls[0]
    payload = json.loads(user)
    assert {g["key"] for g in payload["gaps"]} == {"subscribers", "monthly_arpu", "churn", "retention"}
    assert [f["firm"] for f in payload["firms"]] == ["Firm A", "Firm B"]
    assert "assumptions" in system


def test_reejecutar_es_idempotente(db) -> None:
    _run(db, FakeLLM([_good]))
    # Ya cubiertos: la segunda corrida no ve esos huecos y no reescribe nada.
    again = _run(db, FakeLLM([json.dumps({"assumptions": []})]))
    assert again.status == "no_assumptions"
    assert db.query(DeclaredInputValue).count() == 2


def test_no_pisa_un_dato_oficial(db) -> None:
    company = db.get(Company, 1)
    service = DeclaredInputService()
    service.upsert(
        db,
        company=company,
        tenant_id=T1,
        item=DeclaredInput(
            input_key="subscribers",
            base=90_000_000,
            unit="subscribers",
            method="extract",
            source_url="https://www.sec.gov/x.htm",
            source_quote="90 million",
        ),
    )
    llm = FakeLLM([_bad(lambda items: None)])
    result = _run(db, llm)
    # «subscribers» ya no es hueco: si el modelo lo propone, se rechaza la respuesta.
    assert result.status == "rejected"
    assert any("no es un hueco" in p for p in result.problems)
    assert float(_rows(db)[("subscribers", "")].base) == 90_000_000


# ------------------------------------------------------------------ fail-closed
@pytest.mark.parametrize(
    ("mutator", "fragment"),
    [
        (lambda i: i[0].update(source_quote="Firm A models 300 million subscribers"), "cita no aparece"),
        (lambda i: i[0].update(source_url="https://otra.example.com/x"), "URL no es la de la evidencia"),
        (lambda i: i[0].update(citations=[]), "no cita evidencia"),
        (lambda i: i[0].update(citations=["ev-999"]), "no cita evidencia"),
        (lambda i: i[0].update(firm="Firm C"), "no está entre las mejor puntuadas"),
        (lambda i: i[1].update(firm="Firm A"), "firma no aparece en la evidencia"),
        (lambda i: i[0].update(input_key="wacc"), "no es un hueco"),
        (lambda i: i[0].update(value="mucho"), "no es un número"),
        (lambda i: i[2].update(unit="USD"), "unidad"),
        (lambda i: i.append(dict(i[0])), "repetido"),
    ],
)
def test_salida_invalida_no_escribe_nada(db, mutator, fragment) -> None:
    llm = FakeLLM([_bad(mutator)])
    result = _run(db, llm)
    assert result.status == "rejected"
    assert any(fragment in p for p in result.problems), result.problems
    assert result.llm_calls == 2
    assert "problems_previous_answer" in json.loads(llm.calls[1][1])
    assert db.query(DeclaredInputValue).count() == 0


@pytest.mark.parametrize("answer", ["no es json", json.dumps({"otra": 1}), json.dumps({"assumptions": "x"})])
def test_json_invalido_rechazado(db, answer) -> None:
    result = _run(db, FakeLLM([answer]))
    assert result.status == "rejected"
    assert db.query(DeclaredInputValue).count() == 0


def test_reintento_corregido_se_guarda(db) -> None:
    llm = FakeLLM([_bad(lambda i: i[0].update(source_quote="inventada")), _good])
    result = _run(db, llm)
    assert result.status == "stored" and result.llm_calls == 2


def test_llm_que_falla_no_escribe(db) -> None:
    async def boom(*_a, **_k):
        raise RuntimeError("sin presupuesto")

    result = _run(db, boom)
    assert result.status == "error"
    assert db.query(DeclaredInputValue).count() == 0


def test_empresa_desconocida(db) -> None:
    assert _run(db, FakeLLM([_good]), ctx=_ctx(ticker="NOPE")).status == "no_company"


# ------------------------------------------------------------------ mezcla y límites (puros)
def _a(firm, value, key="subscribers", unit="subscribers", **kw) -> AnalystAssumption:
    return AnalystAssumption(
        input_key=key,
        segment_key="",
        firm=firm,
        value=value,
        unit=unit,
        source_url=f"https://n.example.com/{firm}",
        source_quote="q",
        **kw,
    )


def test_mezcla_mediana_rango_y_orden_por_ranking() -> None:
    inputs, notes = blend_assumptions(
        [_a("B", 100.0), _a("A", 300.0, low=250.0), _a("C", 200.0, high=500.0)], ["A", "B", "C"]
    )
    assert notes == []
    (item,) = inputs
    assert (item.base, item.low, item.high) == (200.0, 100.0, 500.0)
    assert item.analyst_firm == "A, B, C" and item.source_url.endswith("/A")
    assert item.method == "analyst" and item.status == "estimado"


def test_unidades_distintas_no_se_mezclan() -> None:
    inputs, notes = blend_assumptions(
        [_a("A", 1.0, unit="subscribers"), _a("B", 1.0, unit="millions")], ["A", "B"]
    )
    assert inputs == [] and "unidades distintas" in notes[0]


@pytest.mark.parametrize(
    ("assumption", "violates"),
    [
        (_a("A", 0.10, key="terminal_growth", unit="ratio"), True),
        (_a("A", 0.03, key="terminal_growth", unit="ratio"), False),
        (_a("A", 0.0, key="segments.d2d.replacement_capex", unit="USD"), True),
        (_a("A", 5.0, key="subscribers"), False),
    ],
)
def test_limites_economicos(assumption, violates) -> None:
    assert (economic_limit_violation(assumption) is not None) is violates


def test_crecimiento_perpetuo_excesivo_se_descarta_y_se_dice(db) -> None:
    def answer(user: str) -> str:
        ids = _ids(user)
        items = _good_items(ids)
        items.append(
            {
                "input_key": "terminal_growth",
                "segment_key": "",
                "firm": "Firm A",
                "value": 0.10,
                "unit": "ratio",
                "citations": [ids[NOTE_URL]],
                "source_url": NOTE_URL,
                "source_quote": "a 10% perpetual growth rate",
            }
        )
        return json.dumps({"assumptions": items})

    result = _run(db, FakeLLM([answer]), extra_inputs=("terminal_growth",))
    assert result.status == "stored", result.problems
    assert len(result.discarded) == 1 and "PIB nominal" in result.discarded[0]
    assert ("terminal_growth", "") not in _rows(db)
    assert ("subscribers", "") in _rows(db)
