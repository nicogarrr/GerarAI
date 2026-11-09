"""company_guidance (bordes): helpers puros (_amount, _period_end,
_explicit_periods, _period, _window, _published) y ramas de extract_guidance
que las frases reales no ejercitan: «per share» como marca de BPA, cifra sin
métrica, pasado entre métrica y cifra, cue fuera de la ventana, periodo
ambiguo, rango invertido, varios años sueltos con «annual» (ejercicio del
documento) y refresh con documento viejo o validación rechazada.

Sin red ni BD salvo los dos últimos tests (SQLite real, DeclaredInputService
real o con validate doblado por monkeypatch, que se restaura solo). Textos
sintéticos.
"""

from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, Document, DocumentChunk, Tenant
from app.services import company_guidance as cg
from app.services.company_guidance import extract_guidance

PUB = date(2026, 1, 15)


# --- helpers puros ---------------------------------------------------------


def test_amount_eps_no_aplica_escala():
    assert cg._amount("1.25", "billion", "eps") == Decimal("1.25")
    assert cg._amount("150", "million", "revenue") == Decimal("150000000")


def test_period_end_h1_es_30_de_junio():
    assert cg._period_end("h1_2026") == date(2026, 6, 30)
    assert cg._period_end("q3_2026") == date(2026, 9, 30)
    assert cg._period_end("fy2026") == date(2026, 12, 31)


def test_explicit_periods_medios_y_qn():
    assert cg._explicit_periods("second half of 2026") == [("h2_2026", 2026)]
    assert cg._explicit_periods("first half of fiscal year 2027") == [("h1_2027", 2027)]
    assert cg._explicit_periods("Q4 2026") == [("q4_2026", 2026)]
    assert cg._explicit_periods("fiscal 2027") == [("fy2027", 2027)]


def test_period_solo_periodos_pasados_es_resultado():
    assert cg._period("revenue was $10 billion in full year 2024", PUB) is None


def test_period_sin_ningun_periodo_devuelve_none():
    assert cg._period("we expect significant growth ahead of us", PUB) is None


def test_window_recorta_en_espacios_y_conserva_la_cifra():
    antes = " ".join(f"w{i:03d}" for i in range(60))
    despues = " ".join(f"z{i:03d}" for i in range(40))
    cifra = "EUR 5 million"
    sentence = f"{antes} {cifra} {despues}"
    start = len(antes) + 1
    window, pos = cg._window(sentence, start, start + len(cifra))
    # La cita siempre contiene la cifra exactamente en pos.
    assert window[pos : pos + len(cifra)] == cifra
    # Los bordes caen en palabras completas, no a mitad de token.
    assert window.split(" ")[0] in {f"w{i:03d}" for i in range(60)} | {cifra.split(" ")[0]}
    assert len(window) < len(sentence)


def test_published_acepta_date_plano_y_none():
    assert cg._published(SimpleNamespace(published_at=date(2026, 10, 1))) == date(2026, 10, 1)
    assert cg._published(SimpleNamespace(published_at=None)) is None
    assert cg._published(SimpleNamespace(published_at=datetime(2026, 10, 1, 9, 30))) == date(2026, 10, 1)


# --- extract_guidance: ramas que las frases reales no tocan -----------------


def test_per_share_marca_eps_sin_metrica_previa():
    items = extract_guidance("We expect full year 2026 earnings of $1.25 per diluted share.", published=PUB)
    assert len(items) == 1
    g = items[0]
    assert g.input_key == "guidance.eps.fy2026"
    assert g.metric == "eps"
    assert g.period == "fy2026"
    assert g.year == 2026
    assert g.low is None
    assert g.base == Decimal("1.25")
    assert g.high is None
    assert g.currency == "USD"
    assert g.period_read == "explicito"
    assert "$1.25" in g.quote


def test_per_share_conserva_la_posicion_de_la_metrica_previa():
    items = extract_guidance("We expect EPS of $1.30 per share for full year 2026.", published=PUB)
    assert len(items) == 1
    assert items[0].metric == "eps"
    assert items[0].base == Decimal("1.30")


def test_cifra_con_cue_pero_sin_metrica_no_es_guia():
    assert (
        extract_guidance(
            "We expect to invest approximately $5 billion during the remainder of the year.",
            published=PUB,
        )
        == []
    )


def test_verbo_en_pasado_entre_metrica_y_cifra_no_es_guia():
    assert extract_guidance("We expect revenue grew to $5 billion in full year 2026.", published=PUB) == []


def test_cue_fuera_de_la_ventana_no_es_guia():
    relleno = "across all of our reporting segments and geographies " * 5
    sentence = f"We expect {relleno}revenue of $5 billion in full year 2026."
    assert extract_guidance(sentence, published=PUB) == []


def test_periodo_explicito_ambiguo_no_es_guia():
    assert (
        extract_guidance(
            "We expect Q2 2026 and Q3 2026 revenue of approximately $5 billion.",
            published=PUB,
        )
        == []
    )


def test_rango_invertido_no_es_guia():
    assert (
        extract_guidance(
            "We expect full year 2026 revenue of $76 billion to $73 billion.",
            published=PUB,
        )
        == []
    )


def test_varios_anos_sueltos_con_annual_es_el_ejercicio_del_documento():
    items = extract_guidance(
        "We expect annual revenue growth of $5 billion in 2026 and 2027.",
        published=PUB,
    )
    assert len(items) == 1
    g = items[0]
    assert g.metric == "revenue"
    assert g.period == "fy2026"
    assert g.year == 2026
    assert g.base == Decimal("5000000000")
    assert g.period_read == "ejercicio_del_documento"


# --- refresh_company_guidance: descartes ------------------------------------


def _db_con_documento(published_at, texto):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    tenant = Tenant(external_id="cg-test", name="CG")
    session.add(tenant)
    session.flush()
    session.info["tenant_id"] = tenant.id
    company = Company(
        ticker="CGT",
        name="Guidance Co",
        exchange="NASDAQ",
        currency="USD",
        sector="Technology",
        industry="Software",
        company_type="holding",
        valuation_model="unassigned",
        special_sources=[],
        special_risks=[],
        factor_tags=[],
    )
    session.add(company)
    session.flush()
    document = Document(
        company_id=company.id,
        title="Nota de resultados",
        source_type="SEC",
        storage_uri=None,
        published_at=published_at,
    )
    session.add(document)
    session.flush()
    session.add(DocumentChunk(document_id=document.id, chunk_index=0, text=texto))
    session.commit()
    return session, tenant, company


def test_refresh_ignora_documento_mas_viejo_que_la_ventana():
    session, tenant, company = _db_con_documento(
        datetime(2024, 1, 1, 12, 0),
        "On track to achieve full year 2026 revenue guidance of $150.0 million to $200.0 million.",
    )
    try:
        result = cg.refresh_company_guidance(session, company, tenant.id, today=date(2026, 11, 9))
        assert result == {"documents": 1, "guidance": []}
    finally:
        session.close()


def test_refresh_descarta_lo_que_no_valida(monkeypatch):
    from app.services.declared_input_service import DeclaredInputService

    monkeypatch.setattr(DeclaredInputService, "validate", lambda self, item: "rechazo forzado")
    session, tenant, company = _db_con_documento(
        datetime(2026, 10, 1, 12, 0),
        "On track to achieve full year 2026 revenue guidance of $150.0 million to $200.0 million.",
    )
    try:
        result = cg.refresh_company_guidance(session, company, tenant.id, today=date(2026, 11, 9))
        assert result == {"documents": 1, "guidance": []}
    finally:
        session.close()
