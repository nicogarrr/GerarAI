"""ThesisService professional-field contract tests.

The thesis is the product's centerpiece: hypothesis, invalidation
criteria, catalysts, rating, confidence and executive summary must be
derived deterministically from model data - never invented - and must
degrade to honest "en formacion" states when inputs are missing.
"""

from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, Company
from app.services.thesis_service import ThesisService


def _company() -> Company:
    return Company(
        ticker="AAPL", name="Apple", exchange="NASDAQ", currency="USD",
        sector="Tech", industry="Tech", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )


# -- confidence score -----------------------------------------------------------

def test_confidence_score_ladder():
    """Orden fail-closed y sensibilidad a la evidencia (F7): nada de cuatro
    constantes identicas para todas las versiones."""
    service = ThesisService()
    backed = [{"material": True, "source_id": 1}]
    unsupported = [{"material": True, "source_id": None}]
    insufficient = service._confidence_score({"status": "insufficient_data"}, {"f": 1}, backed)
    no_facts = service._confidence_score({"status": "ok"}, {}, backed)
    not_publishable = service._confidence_score({"publishable": False}, {"f": 1}, backed)
    publishable = service._confidence_score({"publishable": True}, {"f": 1}, backed)
    assert insufficient < no_facts < not_publishable < publishable
    # La cobertura de afirmaciones mueve la cifra dentro del mismo estado.
    assert service._confidence_score({"publishable": False}, {"f": 1}, unsupported) < not_publishable
    # Los inputs pendientes penalizan.
    assert (
        service._confidence_score({"publishable": True, "missing_inputs": ["a", "b"]}, {"f": 1}, backed)
        < publishable
    )
    # Rango 0-100 siempre.
    assert 0 <= service._confidence_score({"status": "insufficient_data", "missing_inputs": ["x"] * 50}, {}, unsupported) <= 100


# -- hypothesis -------------------------------------------------------------------

def test_hypothesis_honest_when_inputs_missing():
    service = ThesisService()
    text = service._hypothesis(_company(), {"current_price": None})
    assert "faltan datos" in text
    assert "Hipótesis en formación" in text


def test_hypothesis_below_base_with_reverse_dcf():
    service = ThesisService()
    valuation = {
        "current_price": 150.0,
        "base_value": 200.0,
        "margin_of_safety": 0.25,
        "reverse_dcf": {"required_revenue_growth": 0.082},
    }
    text = service._hypothesis(_company(), valuation)
    assert "150.00" in text and "200.00" in text
    # MoS = base/price - 1: se nombra explicitamente, sin distancia precio/base.
    assert "margen de seguridad del 25,0 %" in text
    assert "por debajo" not in text
    assert "8,2 % anual" in text
    assert "Apple" in text


def test_hypothesis_above_base_without_growth():
    service = ThesisService()
    valuation = {
        "current_price": 250.0,
        "base_value": 200.0,
        "margin_of_safety": -0.25,
    }
    text = service._hypothesis(_company(), valuation)
    assert "margen de seguridad del -25,0 %" in text
    assert "por encima" not in text
    assert "reverse DCF" not in text


def test_hypothesis_no_false_price_base_distance():
    # F341: con precio 336.56 y base 106.85 (MoS = -0.68), la distancia real
    # precio/base es ~215%: afirmar "68% por encima" era falso.
    service = ThesisService()
    valuation = {
        "current_price": 336.56,
        "base_value": 106.85,
        "margin_of_safety": -0.68,
    }
    text = service._hypothesis(_company(), valuation)
    assert "margen de seguridad del -68,0 %" in text
    assert "68,0 % por encima" not in text
    assert "215%" not in text


# -- catalysts ---------------------------------------------------------------------

def test_catalysts_only_from_dated_earnings():
    service = ThesisService()
    evidence = {
        "sources": {
            "earnings": {
                "status": "ok",
                "next_date": "2026-10-29",
                "time": "amc",
                "eps_forecast": 1.6,
            }
        }
    }
    catalysts = service._catalysts(evidence)
    assert len(catalysts) == 1
    assert catalysts[0]["date"] == "2026-10-29"
    assert catalysts[0]["source"] == "earnings_calendar"
    assert catalysts[0]["time"] == "amc"
    assert catalysts[0]["eps_forecast"] == 1.6
    # Undated or failed earnings never produce a catalyst.
    assert service._catalysts({"sources": {"earnings": {"status": "error"}}}) == []
    assert service._catalysts({}) == []


# -- invalidation criteria ----------------------------------------------------------

def test_invalidation_criteria_from_model_data():
    service = ThesisService()
    valuation = {
        "margin_of_safety": 0.2,
        "base_value": 200.0,
        "reverse_dcf": {"required_revenue_growth": 0.08},
        "moat": {"moats": [{"type": "switching_costs", "trend": "declining"}]},
    }
    criteria = service._invalidation_criteria(_company(), valuation)
    assert len(criteria) == 3
    assert any("200.00" in c for c in criteria)
    assert any("8,0 % anual" in c for c in criteria)
    assert any("switching_costs" in c for c in criteria)


def test_invalidation_criteria_honest_fallback():
    service = ThesisService()
    criteria = service._invalidation_criteria(_company(), {})
    assert criteria == [
        "Tesis en formación: sin criterios automáticos hasta completar la valoración."
    ]


# -- scenario probabilities ------------------------------------------------------------

def test_scenario_probabilities_extracted_or_none():
    service = ThesisService()
    model = {
        "scenarios": {
            "bear": {"probability": 0.2},
            "base": {"probability": 0.55},
            "bull": {"probability": 0.25},
            "junk": {"no_probability": True},
        }
    }
    assert service._scenario_probabilities(model) == {
        "bear": 0.2, "base": 0.55, "bull": 0.25,
    }
    assert service._scenario_probabilities({}) is None
    assert service._scenario_probabilities({"scenarios": {"x": {}}}) is None


# -- rating -------------------------------------------------------------------------

def test_rating_matrix():
    service = ThesisService()
    assert service._rating(0.5, True, "insufficient_data") == "insufficient_data"
    assert service._rating(0.5, False, "ok") == "blocked"
    assert service._rating(None, True, "ok") == "incomplete_price"
    assert service._rating(0.31, True, "ok") == "attractive"
    assert service._rating(-0.21, True, "ok") == "expensive"
    assert service._rating(0.0, True, "ok") == "watch"


# -- card summary (executive_summary de la tarjeta) ------------------------------------

def test_card_summary_insufficient_data_es_honesto():
    service = ThesisService()
    valuation = {
        "status": "insufficient_data",
        "missing_inputs": ["revenue", "shares"],
        "trace": {"engine": "dcf_v2"},
    }
    text = service._card_summary(_company(), valuation, "hipotesis")
    assert "no publicable todavía" in text
    assert "Ingresos, shares" in text
    assert "NOT PUBLISHABLE" not in text


def test_card_summary_insufficient_excluye_presente_excluido():
    """Matiz auditor: la tarjeta no pide como ausente un dato presente-excluido
    por periodo; lo explica aparte. Gating intacto (missing_inputs no cambia)."""
    service = ThesisService()
    valuation = {
        "status": "insufficient_data",
        "missing_inputs": ["revenue", "shares_diluted", "wacc"],
        "excluded_inputs": [
            {"metric": "shares_diluted", "period": "2025-12-31:FY", "reason": "period_mismatch"}
        ],
        "trace": {"engine": "dcf_v2"},
    }
    text = service._card_summary(_company(), valuation, "hipotesis")
    assert "no publicable todavía" in text
    assert "Ingresos, wacc" in text
    assert "faltan Ingresos, shares diluted" not in text
    assert "ya los tenemos" in text
    assert "desalineación de periodos" in text
    assert "shares" in text  # explicado como presente-excluido, no pedido
    # gating: missing_inputs sigue bloqueando internamente
    assert valuation["missing_inputs"] == ["revenue", "shares_diluted", "wacc"]


def test_card_summary_partial_es_indicativo():
    service = ThesisService()
    valuation = {"status": "partial", "missing_inputs": ["beta"], "trace": {"engine": "dcf_v2"}}
    text = service._card_summary(_company(), valuation, "hipotesis")
    assert text.startswith("hipotesis Faltan")
    assert "beta" in text


def _fecha_es(iso: str) -> str:
    """Esperado es-ES independiente del SUT: tabla de meses propia del test."""
    meses = ("enero", "febrero", "marzo", "abril", "mayo", "junio",
             "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre")
    y, m, d = (int(part) for part in iso[:10].split("-"))
    return f"{d} de {meses[m - 1]} de {y}"

def test_card_summary_anade_titulares_verbatim_con_atribucion():
    # Un titular demuestra que el medio lo publico, no que sea cierto: la
    # tarjeta cita verbatim SOLO el titular original (source_headline), con
    # medio y fecha etiquetada por procedencia.
    service = ThesisService()
    valuation = {"status": "ok", "trace": {"engine": "dcf_v2"}}
    today = datetime.now(UTC).date().isoformat()
    today_es = _fecha_es(today)
    news = [
        {"title": "META Meta presenta Muse (resumen interno)",
         "source_headline": "Meta presenta Muse, su nuevo modelo",
         "source": "TechCrunch", "date": today, "date_source": "source"},
        {"title": "RKLB retrasa (resumen interno)",
         "source_headline": "RKLB retrasa su lanzamiento",
         "source": "SpaceNews", "date": today, "date_source": "source"},
        {"title": "Tercero fuera del top-2", "source_headline": "Tercero",
         "source": "X", "date": today, "date_source": "source"},
    ]
    text = service._card_summary(_company(), valuation, "hipotesis", news)
    assert text.startswith("hipotesis Titulares recientes: ")
    assert f'"Meta presenta Muse, su nuevo modelo" (TechCrunch, publicado el {today_es})' in text
    assert f'"RKLB retrasa su lanzamiento" (SpaceNews, publicado el {today_es})' in text
    assert "Tercero" not in text


def test_card_summary_sin_titular_original_no_atribuye_cita():
    # title es un resumen compuesto por la app: NUNCA se entrecomilla ni se
    # presenta como titular del medio.
    service = ThesisService()
    valuation = {"status": "ok", "trace": {"engine": "dcf_v2"}}
    news = [
        {"title": "Resumen compuesto por la app", "source": "GDELT",
         "date": "2026-09-20", "date_source": "gdelt_first_seen"},
    ]
    text = service._card_summary(_company(), valuation, "hipotesis", news)
    assert "Noticias relevantes: Resumen compuesto por la app (GDELT, visto en GDELT el 20 de septiembre de 2026)." in text
    assert '"Resumen' not in text
    assert "Titulares" not in text


def test_card_summary_fecha_antigua_no_dice_recientes():
    # "Recientes" solo se afirma con una fecha de publicacion real dentro de
    # la ventana; el top por materialidad sin limite de edad no es "reciente".
    service = ThesisService()
    valuation = {"status": "ok", "trace": {"engine": "dcf_v2"}}
    news = [
        {"source_headline": "Titular viejo pero material", "title": "t",
         "source": "Reuters", "date": "2020-01-15", "date_source": "source"},
    ]
    text = service._card_summary(_company(), valuation, "hipotesis", news)
    assert "Titulares materiales destacados: " in text
    assert "recientes" not in text
    assert "publicado el 15 de enero de 2020" in text
    assert "2020-01-15" not in text


def test_card_summary_grupo_mixto_no_dice_recientes():
    # Un titular viejo entre dos citados contamina la etiqueta del grupo:
    # no se puede llamar "recientes" al conjunto.
    service = ThesisService()
    valuation = {"status": "ok", "trace": {"engine": "dcf_v2"}}
    today = datetime.now(UTC).date().isoformat()
    news = [
        {"source_headline": "Fresco", "title": "t1", "source": "A",
         "date": today, "date_source": "source"},
        {"source_headline": "Viejo", "title": "t2", "source": "B",
         "date": "2019-05-01", "date_source": "source"},
    ]
    text = service._card_summary(_company(), valuation, "hipotesis", news)
    assert "Titulares materiales destacados: " in text
    assert "recientes" not in text


def test_card_summary_fecha_futura_no_es_reciente():
    service = ThesisService()
    valuation = {"status": "ok", "trace": {"engine": "dcf_v2"}}
    news = [
        {"source_headline": "Del futuro", "title": "t", "source": "X",
         "date": "2999-01-01", "date_source": "source"},
    ]
    text = service._card_summary(_company(), valuation, "hipotesis", news)
    assert "recientes" not in text
    assert "Titulares materiales destacados: " in text


def test_card_summary_fecha_sin_procedencia_no_se_imprime_desnuda():
    service = ThesisService()
    valuation = {"status": "ok", "trace": {"engine": "dcf_v2"}}
    news = [{"source_headline": "H", "title": "t", "source": "X", "date": "2026-09-20"}]
    text = service._card_summary(_company(), valuation, "hipotesis", news)
    assert '"H" (X)' in text
    assert "2026-09-20" not in text


def test_card_summary_sin_noticias_no_inventa():
    service = ThesisService()
    valuation = {"status": "ok", "trace": {"engine": "dcf_v2"}}
    assert service._card_summary(_company(), valuation, "hipotesis") == "hipotesis"
    assert service._card_summary(_company(), valuation, "hipotesis", []) == "hipotesis"


def test_card_summary_titular_largo_se_trunca_y_sin_fecha_no_fabrica():
    service = ThesisService()
    valuation = {"status": "ok", "trace": {"engine": "dcf_v2"}}
    news = [{"source_headline": "A" * 200, "title": "t", "source": "", "date": None}]
    text = service._card_summary(_company(), valuation, "hipotesis", news)
    assert '...' in text
    assert "A" * 141 not in text
    assert "(" not in text.split("Titulares materiales destacados: ")[1]


# -- card summary (tarjeta "Ultima tesis") ---------------------------------------

def test_card_summary_is_readable_spanish_hypothesis():
    service = ThesisService()
    valuation = {
        "status": "ok",
        "current_price": 336.56,
        "base_value": 106.85,
        "margin_of_safety": -0.68,
        "reverse_dcf": {"required_revenue_growth": 0.35},
    }
    hypothesis = service._hypothesis(_company(), valuation)
    summary = service._card_summary(_company(), valuation, hypothesis)
    assert summary == hypothesis
    assert "margen de seguridad del -68,0 %" in summary
    assert "bucket" not in summary  # la jerga de motor no va a la tarjeta


def test_card_summary_insufficient_data_honest_spanish():
    service = ThesisService()
    valuation = {"status": "insufficient_data", "missing_inputs": ["revenue", "fcf"]}
    summary = service._card_summary(_company(), valuation, "hipotesis")
    assert "no publicable" in summary
    assert "Ingresos, fcf" in summary
    assert "NOT PUBLISHABLE" not in summary


def test_card_summary_partial_keeps_hypothesis_plus_caveat():
    service = ThesisService()
    valuation = {"status": "partial", "missing_inputs": ["shares_diluted"]}
    summary = service._card_summary(_company(), valuation, "Hipotesis X.")
    assert summary.startswith("Hipotesis X.")
    # La etiqueta de indicativa la lleva la hipotesis; aqui queda la lista.
    assert "Faltan Acciones diluidas" in summary


# -- fingerprint: las noticias nuevas son evidencia material -------------------------

def test_fingerprint_cambia_con_noticias_nuevas():
    # Una noticia nueva sin cambio de facts DEBE cambiar el fingerprint:
    # generate() crea una nueva version en generacion normal, no solo con
    # force_new_version.
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.info["tenant_id"] = "tenant-test"
        company = _company()
        db.add(company)
        db.commit()
        service = ThesisService()
        fp_sin = service._input_fingerprint(db, company, {}, {}, [])
        news = [{"id": 1, "title": "resumen interno",
                 "source_headline": "Meta presenta Muse", "date": "2026-09-25"}]
        fp_con = service._input_fingerprint(db, company, {}, {}, news)
        assert fp_con != fp_sin
        # La identidad importa, no el recuento: otra noticia distinta tambien
        # cambia el fingerprint.
        otra = [{"id": 2, "title": "resumen interno 2",
                 "source_headline": "Otro titular", "date": "2026-09-26"}]
        assert service._input_fingerprint(db, company, {}, {}, otra) != fp_con


def test_fingerprint_cambia_con_provenance_sin_variar_facts():
    # Una correccion de fecha (ingested_at_fallback -> source), de medio o de
    # titular mas alla del char 120 cambia la cita mostrada: debe cambiar el
    # fingerprint aunque facts, id y fecha sean identicos.
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.info["tenant_id"] = "tenant-test"
        company = _company()
        db.add(company)
        db.commit()
        service = ThesisService()
        base_news = [{"id": 7, "title": "r", "source_headline": "Titular",
                      "date": "2026-09-25", "date_source": "ingested_at_fallback",
                      "source": "GDELT", "url": "https://e.com/a"}]
        fp_base = service._input_fingerprint(db, company, {}, {}, base_news)
        for mutacion in (
            {"date_source": "source"},
            {"source": "Reuters"},
            {"url": "https://e.com/b"},
            {"source_headline": "Titular con cola distinta mas alla del char 120"},
        ):
            variante = [dict(base_news[0], **mutacion)]
            assert service._input_fingerprint(db, company, {}, {}, variante) != fp_base


def test_fingerprint_cambia_con_render_version(monkeypatch):
    # F341 aterrizaje: la redaccion de la hipotesis ES la salida. Con inputs
    # identicos pero PROMPT_VERSION distinto, el fingerprint debe cambiar o
    # generate() seguiria devolviendo la redaccion vieja ("68% por encima").
    from app.services import thesis_service

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.info["tenant_id"] = "tenant-test"
        company = _company()
        db.add(company)
        db.commit()
        service = ThesisService()
        fp_v3 = service._input_fingerprint(db, company, {}, {}, [])
        monkeypatch.setattr(thesis_service, "PROMPT_VERSION", "thesis-render-v2")
        fp_v2 = service._input_fingerprint(db, company, {}, {}, [])
        assert fp_v3 != fp_v2


def test_hypothesis_has_currency_cents_and_tenth_percent():
    service = ThesisService()
    text = service._hypothesis(_company(), {
        "current_price": 343.46, "base_value": 120.55,
        "margin_of_safety": -0.649,
        "currency": "USD",
    })
    assert "$343.46" in text and "$120.55" in text
    assert "-64,9 %" in text


def test_margin_claim_is_percent_not_decimal():
    from decimal import Decimal

    from app.models import FinancialFact
    from app.services.thesis_service import _metric_claim_statement

    fact = FinancialFact(metric="fcf_margin", value=Decimal("0.237"), unit="decimal", period="2026")
    assert "23,7 %" in _metric_claim_statement("AAPL", "fcf_margin", fact)
