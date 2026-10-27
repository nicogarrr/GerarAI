"""Tests hermeticos de los 6 gates Jev (sin red, sin key real).

Estrategia: se sustituye ``app.services.jev_gates.build_client`` por un
stub en memoria (mapping pregunta -> (label, confianza)) y el LLM principal
por providers contadores. Cada test verifica que, cuando Jev dice X, la
llamada LLM/escritura pesada se ahorra; y que sin key todo sigue igual que
antes (regresion a comportamiento actual).
"""

import asyncio
import json
from decimal import Decimal
from unittest.mock import Mock, patch

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.core.database import Base
from app.llm.base import LLMProvider
from app.llm.contracts import LLMRequest, LLMResponse, Message, Usage
from app.llm.routing import TaskModelRouter
from app.models import Claim, Company, Document, DocumentChunk, NewsEvent, ThesisChange
from app.schemas import ChatResponse
from app.services import jev_gates
from app.services.chat_service import ChatService
from app.services.chat_synthesis_service import SECTION_ORDER, ChatSynthesisService
from app.services.claim_intelligence_service import ClaimIntelligenceService
from app.services.kpi_extraction_service import KPIExtractionService
from app.services.news_service import NewsService
from app.services.thesis_debate_service import debate_thesis

# ---------------------------------------------------------------- stubs Jev


class _JevDecision:
    def __init__(self, label: str, confidence: float = 0.9):
        self.label = label
        self.confidence = confidence
        self.probabilities = {}
        self.model = "jev-stub"
        self.latency_s = 0.001


class _StubJevClient:
    """Stub hermetico de JevDecisionClient (classify + systemone)."""

    def __init__(self, mapping: dict):
        self.mapping = dict(mapping)
        self.calls: list = []

    async def classify(self, text, name=None, instructions=None, criteria=None, model=None):
        self.calls.append(name)
        label, conf = self.mapping.get(name, ("", 0.0))
        return _JevDecision(label, conf)

    async def systemone(self, state, questions, model=None):
        self.calls.append(("systemone", len(questions)))
        per_chunk = self.mapping.get("systemone", ("noise", 0.9))
        answers = {}
        for question in questions:
            if isinstance(per_chunk, dict):
                label, conf = per_chunk.get(question, ("noise", 0.9))
            else:
                label, conf = per_chunk
            answers[question] = {"choice": label, "confidence": conf, "probabilities": {}}
        return {"answers": answers, "model": "jev-stub"}


@pytest.fixture(autouse=True)
def _sin_jev_por_defecto(monkeypatch):
    """Hermetico por defecto: ningun gate toca red aunque haya key en .env."""
    monkeypatch.setattr(jev_gates, "credit_status", lambda: {"status": "activo"})
    monkeypatch.setattr(jev_gates, "build_client", lambda: None)
    import app.services.jev_triage_service as triage

    monkeypatch.setattr(triage, "build_client", lambda: None)


def _stub_jev(monkeypatch, mapping: dict) -> _StubJevClient:
    stub = _StubJevClient(mapping)
    monkeypatch.setattr(jev_gates, "build_client", lambda: stub)
    return stub


# ------------------------------------------------------- providers contadores


class ScriptedProvider(LLMProvider):
    """Respuestas guionizadas en orden; cuenta llamadas LLM."""

    name = "scripted-test-provider"

    def __init__(self, script: list[str]):
        super().__init__(
            model_router=TaskModelRouter(default_model="test-model"),
            timeout_seconds=1,
            max_retries=0,
        )
        self.script = list(script)
        self.calls = 0

    async def complete(self, request: LLMRequest) -> LLMResponse:
        self.calls += 1
        text = self.script[min(self.calls - 1, len(self.script) - 1)]
        return LLMResponse(
            message=Message("assistant", text),
            usage=Usage(10, 10, 20),
            model="test-model",
            provider=self.name,
            request_id="test-request",
        )


class CountingJsonProvider(LLMProvider):
    """Responde un JSON fijo; cuenta llamadas LLM."""

    name = "counting-json-provider"

    def __init__(self, payload):
        super().__init__(
            model_router=TaskModelRouter(default_model="test-model"),
            timeout_seconds=1,
            max_retries=0,
        )
        self._payload = payload
        self.calls = 0
        self.last_request = None

    async def complete(self, request: LLMRequest) -> LLMResponse:
        self.calls += 1
        self.last_request = request
        payload = self._payload(request) if callable(self._payload) else self._payload
        return LLMResponse(
            message=Message("assistant", json.dumps(payload)),
            usage=Usage(100, 50, 150),
            model="test-model",
            provider=self.name,
            request_id="test-request",
        )


def _company(ticker: str) -> Company:
    return Company(
        ticker=ticker,
        name=f"{ticker} Test",
        exchange="TEST",
        currency="USD",
        sector="Test",
        industry="Test",
        company_type="standard",
        valuation_model="standard_dcf",
        special_sources=[],
        special_risks=[],
        factor_tags=[],
    )


def _memdb():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


# ------------------------------------------------- (1) gate debate_worthwhile

_BULL = "Caso alcista: crecimiento de margenes y recompra de acciones."
_BEAR = "Caso bajista: riesgo de deuda elevada y competencia intensa."
_JUDGE = "VEREDICTO: bearish | La deuda pesa mas que el crecimiento."


def test_1_gate_clear_cut_ahorra_3_llm(monkeypatch):
    stub = _stub_jev(monkeypatch, {"debate_worthwhile": ("clear_cut", 0.92)})
    provider = ScriptedProvider([_BULL, _BEAR, _JUDGE])
    result = asyncio.run(debate_thesis("SAN", "El banco gano 2.000 millones.", provider=provider))
    assert result["llm_calls"] == 0
    assert provider.calls == 0  # 3 llamadas LLM ahorradas
    assert stub.calls == ["debate_worthwhile"]  # 1 llamada Jev
    assert result["verdict"] in {"bullish", "bearish", "neutral"}
    assert result["jev_gate"]["skipped_llm"] is True


def test_1_gate_contestable_sigue_debate(monkeypatch):
    stub = _stub_jev(
        monkeypatch,
        {"debate_worthwhile": ("contestable", 0.9), "verdict": ("bearish", 0.88)},
    )
    provider = ScriptedProvider([_BULL, _BEAR])
    result = asyncio.run(debate_thesis("SAN", "Tesis disputada.", provider=provider))
    assert provider.calls == 2  # bull + bear; el juez es Jev (5)
    assert result["verdict"] == "bearish"


def test_1_sin_key_debate_igual_que_antes():
    provider = ScriptedProvider([_BULL, _BEAR, _JUDGE])
    result = asyncio.run(debate_thesis("SAN", "Tesis de prueba.", provider=provider))
    assert result["llm_calls"] == 3
    assert provider.calls == 3
    assert result["verdict"] == "bearish"
    assert result["jev_gate"] is None and result["jev_judge"] is None


def test_1_maybe_attach_debate_respeta_gate(monkeypatch):
    stub = _stub_jev(monkeypatch, {"debate_worthwhile": ("clear_cut", 0.9)})
    provider = ScriptedProvider([_BULL, _BEAR, _JUDGE])
    svc = ChatSynthesisService(provider)
    baseline = ChatResponse(answer="El banco gano 2.000 millones.", sources=[])
    asyncio.run(svc._maybe_attach_debate(baseline, "SAN", True))
    assert baseline.llm_trace["thesis_debate"]["skipped"] is True
    assert provider.calls == 0  # debate LLM (3) ahorrado en el chat
    assert stub.calls == ["debate_worthwhile"]


def test_1_maybe_attach_debate_sin_doble_gate(monkeypatch):
    stub = _stub_jev(
        monkeypatch,
        {"debate_worthwhile": ("contestable", 0.9), "verdict": ("bullish", 0.8)},
    )
    provider = ScriptedProvider([_BULL, _BEAR])
    svc = ChatSynthesisService(provider)
    baseline = ChatResponse(answer="Tesis disputada sobre margenes.", sources=[])
    asyncio.run(svc._maybe_attach_debate(baseline, "SAN", True))
    assert baseline.llm_trace["thesis_debate"]["verdict"] == "bullish"
    assert provider.calls == 2
    assert stub.calls == ["debate_worthwhile", "verdict"]  # gate 1 vez, sin duplicar


# ------------------------------------------------------ (2) pre-filtro KPI

_KPI_TEXT = "Penetration reached 12.5% in FY2025."


def _kpi_db(chunk_text: str):
    engine = _memdb()
    with Session(engine) as db:
        company = _company("ASTS")
        company.company_type = "space_telecom_pre_fcf"
        company.factor_tags = ["space", "telecom"]
        db.add(company)
        db.flush()
        document = Document(company_id=company.id, title="FY2025 update", source_type="company_ir")
        db.add(document)
        db.flush()
        chunk = DocumentChunk(document_id=document.id, chunk_index=0, text=chunk_text)
        db.add(chunk)
        db.commit()
        ids = (company.id, document.id, chunk.id)
    return engine, ids


def _kpi_payload(chunk_id: int) -> dict:
    return {
        "observations": [
            {
                "metric_key": "penetration",
                "raw_label": "Penetration",
                "raw_value": "12.5%",
                "raw_unit": "percent",
                "period": "FY2025",
                "fiscal_year": 2025,
                "fiscal_quarter": "FY",
                "chunk_id": chunk_id,
                "quote": _KPI_TEXT,
                "confidence": 0.95,
            }
        ]
    }


def test_2_prefiltro_todo_ruido_ahorra_llm(monkeypatch):
    stub = _stub_jev(monkeypatch, {"systemone": ("noise", 0.93)})
    engine, (_, document_id, _) = _kpi_db("General market commentary with no figures at all.")
    provider = CountingJsonProvider({"observations": []})
    with Session(engine) as db:
        document = db.get(Document, document_id)
        result = asyncio.run(KPIExtractionService(provider).extract_document(db, document))
    assert result == []
    assert provider.calls == 0  # 1 llamada LLM ahorrada
    assert stub.calls == [("systemone", 1)]  # 1 llamada Jev


def test_2_prefiltro_con_senal_llama_llm(monkeypatch):
    _stub_jev(monkeypatch, {"systemone": ("signal", 0.9)})
    engine, (_, document_id, chunk_id) = _kpi_db(_KPI_TEXT)
    provider = CountingJsonProvider(lambda req: _kpi_payload(chunk_id))
    with Session(engine) as db:
        document = db.get(Document, document_id)
        result = asyncio.run(KPIExtractionService(provider).extract_document(db, document))
    assert len(result) == 1
    assert provider.calls == 1


def test_2_sin_key_extraccion_igual_que_antes():
    engine, (_, document_id, chunk_id) = _kpi_db(_KPI_TEXT)
    provider = CountingJsonProvider(lambda req: _kpi_payload(chunk_id))
    with Session(engine) as db:
        document = db.get(Document, document_id)
        result = asyncio.run(KPIExtractionService(provider).extract_document(db, document))
    assert len(result) == 1
    assert provider.calls == 1


# ---------------------------------------------------------- (3) news_action

# news_relevance.company_is_central: la empresa debe citarse >= 3 veces (el ticker
# inicial no cuenta); si no, requires_update baja a False por "mencion de pasada".
_NEWS_TEXT = (
    "TST fraud investigation, trading halted amid SEC probe into accounting. "
    "TST said it received a subpoena. TST shares fell sharply after the halt. "
    "Analysts said TST may restate results."
)


def _news_db():
    engine = _memdb()
    with Session(engine) as db:
        db.add(_company("TST"))
        db.commit()
    return engine


def _news_counts(db) -> tuple[int, int]:
    news = db.scalar(select(func.count()).select_from(NewsEvent)) or 0
    changes = db.scalar(select(func.count()).select_from(ThesisChange)) or 0
    return news, changes


def test_3_duplicado_via_ligera_sin_thesis_change_ni_scan(monkeypatch):
    _stub_jev(monkeypatch, {"news_action": ("duplicate", 0.91)})
    engine = _news_db()
    svc = NewsService()
    scan = Mock()
    with patch.object(svc.claim_intelligence, "scan_text", scan):
        with Session(engine) as db:
            resp = svc._analyze_news(db, _NEWS_TEXT, "feed", None)
            db.commit()
        with Session(engine) as db:
            news, changes = _news_counts(db)
    assert resp.requires_update is False  # via completa daria True (fraud -> 10)
    assert scan.call_count == 0  # claim scan ahorrado
    assert changes == 0  # ThesisChange/review ahorrados
    assert news == 1  # el evento queda en el tracker
    assert any("jev_news_action(duplicate" in r for r in resp.materiality_reasons)


def test_3_ruido_baja_confianza_via_completa(monkeypatch):
    _stub_jev(monkeypatch, {"news_action": ("noise", 0.50)})
    engine = _news_db()
    svc = NewsService()
    scan = Mock()
    with patch.object(svc.claim_intelligence, "scan_text", scan):
        with Session(engine) as db:
            resp = svc._analyze_news(db, _NEWS_TEXT, "feed", None)
            db.commit()
    assert resp.requires_update is True  # umbral 0.85 no alcanzado
    assert scan.call_count == 1


def test_3_sin_key_analisis_igual_que_antes():
    engine = _news_db()
    svc = NewsService()
    scan = Mock()
    with patch.object(svc.claim_intelligence, "scan_text", scan):
        with Session(engine) as db:
            resp = svc._analyze_news(db, _NEWS_TEXT, "feed", None)
            db.commit()
        with Session(engine) as db:
            _, changes = _news_counts(db)
    assert resp.requires_update is True
    assert scan.call_count == 1
    assert changes == 1
    assert not any("jev_news_action" in r for r in resp.materiality_reasons)


# ------------------------------------------------------- (4) fast-path chat

_CHAT_QUESTION = "What was the closing price of TST yesterday?"


def _chat_payload() -> dict:
    return {
        "sections": [{"key": key, "body": "test body", "citations": []} for key in SECTION_ORDER],
        "confidence": 0.8,
        "insufficient_data": True,
        "answer": "Respuesta natural en prosa.",
    }


def test_4_fast_path_ahorra_sintesis_llm(monkeypatch):
    _stub_jev(monkeypatch, {"chat_needs_llm": ("baseline_ok", 0.9)})
    engine = _memdb()
    provider = CountingJsonProvider(_chat_payload())
    with Session(engine) as db:
        resp = asyncio.run(ChatService(provider).answer(db, _CHAT_QUESTION, "company", "AAPL"))
    assert provider.calls == 0  # 1 llamada LLM ahorrada
    assert resp.model == "deterministic"
    assert resp.llm_trace.get("fast_path") is True


def test_4_needs_llm_sintetiza(monkeypatch):
    _stub_jev(monkeypatch, {"chat_needs_llm": ("needs_llm", 0.9)})
    engine = _memdb()
    provider = CountingJsonProvider(_chat_payload())
    with Session(engine) as db:
        resp = asyncio.run(ChatService(provider).answer(db, _CHAT_QUESTION, "company", "AAPL"))
    assert provider.calls == 1
    assert resp.model == "test-model"


def test_4_sin_ticker_va_a_sintesis_general_en_espanol():
    # Sin ticker el gate jev no aplica: la pregunta general siempre la
    # responde el LLM en prosa natural (chat-general-v4), nunca el template.
    engine = _memdb()
    provider = CountingJsonProvider(_chat_payload())
    with Session(engine) as db:
        resp = asyncio.run(
            ChatService(provider).answer(db, "Cuéntame algo interesante sobre Madrid", "portfolio", None)
        )
    assert provider.calls == 1
    assert resp.prompt_version == "chat-general-v4"


def test_4b_financiero_sin_fuentes_rechaza_respuesta_no_etiquetada():
    # Updated owner rule: inference is permitted; unlabelled output is not.
    engine = _memdb()
    provider = CountingJsonProvider(_chat_payload())
    with Session(engine) as db:
        resp = asyncio.run(ChatService(provider).answer(db, _CHAT_QUESTION, "portfolio", None))
    assert provider.calls == 1
    assert resp.model == "fallback"


# ------------------------------------------------------------ (5) juez Jev


def test_5_juez_jev_reemplaza_3a_llamada(monkeypatch):
    stub = _stub_jev(
        monkeypatch,
        {"debate_worthwhile": ("contestable", 0.9), "verdict": ("bearish", 0.88)},
    )
    provider = ScriptedProvider([_BULL, _BEAR, _JUDGE])
    result = asyncio.run(debate_thesis("SAN", "Tesis disputada.", provider=provider))
    assert result["llm_calls"] == 2
    assert provider.calls == 2  # 3ª llamada LLM (juez) ahorrada
    assert stub.calls == ["debate_worthwhile", "verdict"]  # 1 llamada Jev de juez
    assert result["verdict"] == "bearish"
    assert result["jev_judge"] == {"label": "bearish", "confidence": 0.88}


def test_5_juez_jev_falla_degrada_a_juez_llm(monkeypatch):
    _stub_jev(monkeypatch, {"debate_worthwhile": ("contestable", 0.9), "verdict": ("", 0.0)})
    provider = ScriptedProvider([_BULL, _BEAR, _JUDGE])
    result = asyncio.run(debate_thesis("SAN", "Tesis disputada.", provider=provider))
    assert result["llm_calls"] == 3  # juez LLM como siempre
    assert provider.calls == 3
    assert result["verdict"] == "bearish"
    assert result["jev_judge"] is None


# ------------------------------------------------------ (6) claim_relation

_CLAIM_TEXT = "Revenue grew 10 percent year over year in the third quarter."
_CANDIDATE_WEAK = "The company announced a new office opening in Berlin next spring."
_CANDIDATE_RELATED = "Third-quarter revenue was up 10% compared with the same quarter a year earlier."


def _claim() -> Claim:
    return Claim(company_id=1, statement=_CLAIM_TEXT)


def test_6_uncertain_jev_escala_la_duda(monkeypatch):
    """Jev puede resolver un par hacia una relacion NEGATIVA si el veredicto es fuerte.

    No puede fabricar confirmacion: promoting to ``supported`` still requires the
    deterministic similarity gate, because ``supported`` is the only status that
    takes a claim out of the "UNVERIFIED CLAIM" section of the chat.
    """
    stub = _stub_jev(monkeypatch, {"claim_relation": ("contradicted", 0.92)})
    result = ClaimIntelligenceService().classify_relation(
        claim=_claim(), candidate=_CANDIDATE_RELATED, similarity=0.52
    )
    assert result.relation == "contradicted"
    assert result.confidence == 0.92
    assert "Jev" in result.rationale
    assert stub.calls == ["claim_relation"]  # 1 llamada Jev


def test_6_jev_no_promueve_un_par_no_relacionado(monkeypatch):
    """Un par sin relacion no se vuelve `supported` porque lo diga el LLM.

    "Revenue grew 10 percent year over year" frente a "the company announced a
    new office opening in Berlin" no comparten ninguna afirmacion. Este test
    exigia que un veredicto Jev de 0,82 los uniera y marcara el claim como
    `supported`, que es como un claim no verificado salia de la seccion
    UNVERIFIED CLAIM del chat.
    """
    _stub_jev(monkeypatch, {"claim_relation": ("supported", 0.99)})
    result = ClaimIntelligenceService().classify_relation(
        claim=_claim(), candidate=_CANDIDATE_WEAK, similarity=0.25
    )
    assert result.relation == "uncertain"


def test_6_jev_no_promueve_a_supported_por_encima_del_umbral_de_similitud(monkeypatch):
    """Aunque este seguro, Jev no confirma un par por debajo del umbral."""
    _stub_jev(monkeypatch, {"claim_relation": ("supported", 0.99)})
    result = ClaimIntelligenceService().classify_relation(
        claim=_claim(), candidate=_CANDIDATE_RELATED, similarity=0.52
    )
    assert result.relation == "uncertain"


def test_6_jev_con_confianza_no_finita_se_ignora(monkeypatch):
    """`NaN` no puede convertirse en confianza 1.0."""
    _stub_jev(monkeypatch, {"claim_relation": ("contradicted", float("nan"))})
    result = ClaimIntelligenceService().classify_relation(
        claim=_claim(), candidate=_CANDIDATE_RELATED, similarity=0.52
    )
    assert result.relation == "uncertain"


def test_6_jev_con_veredicto_debil_se_ignora(monkeypatch):
    """Por debajo del umbral, el veredicto LLM no se adopta."""
    _stub_jev(monkeypatch, {"claim_relation": ("contradicted", 0.60)})
    result = ClaimIntelligenceService().classify_relation(
        claim=_claim(), candidate=_CANDIDATE_RELATED, similarity=0.52
    )
    assert result.relation == "uncertain"


def test_6_uncertain_sin_key_sigue_uncertain():
    result = ClaimIntelligenceService().classify_relation(
        claim=_claim(), candidate=_CANDIDATE_WEAK, similarity=0.25
    )
    assert result.relation == "uncertain"


def test_6_rama_fuerte_no_llama_jev(monkeypatch):
    stub = _stub_jev(monkeypatch, {"claim_relation": ("contradicted", 0.9)})
    result = ClaimIntelligenceService().classify_relation(
        claim=_claim(), candidate=_CLAIM_TEXT, similarity=0.99
    )
    assert result.relation == "supported"  # determinista, sin Jev
    assert stub.calls == []  # Jev solo en ramo uncertain


def test_6_opt_out_use_jev_false(monkeypatch):
    stub = _stub_jev(monkeypatch, {"claim_relation": ("supported", 0.9)})
    result = ClaimIntelligenceService().classify_relation(
        claim=_claim(), candidate=_CANDIDATE_WEAK, similarity=0.25, use_jev=False
    )
    assert result.relation == "uncertain"
    assert stub.calls == []
    assert Decimal(str(result.confidence))  # confianza determinista intacta
