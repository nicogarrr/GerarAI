"""Reglas de prosa de los validadores de tesis: tests autocontenidos.

Sin artefactos externos ni capturas privadas: todas las fixtures son
sinteticas e inline. El replay opcional con las respuestas reales del
ensayo run1 vive en test_offline_run1_replay.py.
"""
from types import SimpleNamespace

import pytest

from app.services.thesis_deep_narrative import (
    _URL_RE,
    _validate_sections,
    _visible_medio,
    fact_pack,
)
from app.services.thesis_news_narrative import validate_output

PROSA = (
    "El activo registra un contexto de cobertura mediatica amplia y los "
    "titulares disponibles describen un movimiento que aun requiere "
    "confirmacion documental por parte de los implicados."
)


def _headlines(ids=("news:1", "news:2", "news:3")):
    return [
        {"id": nid, "titulo": f"Titular sintetico {nid}", "tipo": "titular original",
         "medio": "Medio Sintetico", "fecha": "2026-10-20T08:00:00+00:00",
         "origen_fecha": "source", "url": f"https://example-{i}.test/pieza",
         "pendiente_actualizacion": False}
        for i, nid in enumerate(ids)
    ]


def _news_raw(texto_cambio):
    base = {"texto": PROSA, "evidence_ids": ["news:1"]}
    return {
        "cambio": {"texto": texto_cambio, "evidence_ids": ["news:1"]},
        "implicaciones": dict(base),
        "riesgos": {"texto": PROSA, "evidence_ids": ["news:2", "news:3"]},
    }


# ------------------------------------------------- regla de cantidades (news)

@pytest.mark.parametrize("frase", [
    "vincular el movimiento de un tercero con el activo",
    "la respuesta de un tercero ajeno al mercado",
    "Un tercero, segun el titular, reacciono despues",
    "la dependencia de un tercero quedo registrada",
    "interviene un tercero.",
])
def test_un_tercero_nominal_admitido(frase):
    """«un tercero» = tercero ajeno (sustantivo), no cantidad."""
    validate_output(_news_raw(PROSA + " Ademas, " + frase), _headlines())


@pytest.mark.parametrize("frase,regla", [
    ("un tercero de los ingresos", "cantidad_en_prosa_llm"),   # partitivo
    ("un tercero del total", "cantidad_en_prosa_llm"),         # partitivo
    ("un tercero de hecho", "cantidad_en_prosa_llm"),          # ambiguo: fail-closed
    ("paso del segundo al tercero", "cantidad_en_prosa_llm"),  # orden
    ("por tercer trimestre", "cantidad_en_prosa_llm"),         # ordinal apocope
    ("el tercero en su sector", "cantidad_en_prosa_llm"),      # articulo determinado
    ("un crecimiento del treinta por ciento", "cantidad_en_prosa_llm"),
    ("la mitad del mercado", "cantidad_en_prosa_llm"),
    ("subio 15 puntos", "cifra_en_prosa_llm"),
])
def test_cantidades_y_cifras_rechazadas(frase, regla):
    with pytest.raises(ValueError, match=regla):
        validate_output(_news_raw(PROSA + " Ademas, " + frase + " segun titulares."), _headlines())


def test_evidencia_desconocida_rechazada():
    raw = _news_raw(PROSA)
    raw["cambio"]["evidence_ids"] = ["news:999"]
    with pytest.raises(ValueError, match="evidencia_no_recibida"):
        validate_output(raw, _headlines())


# ------------------------------- presentacion del medio en el pack (deep)

@pytest.mark.parametrize("fuente,visible", [
    ("waterford-news.ie", "waterford-news ie"),        # con guion
    ("finance.yahoo.com", "finance yahoo com"),        # multi-etiqueta: componentes conservados
    ("www.elmundo.es", "elmundo es"),
    ("https://www.bbc.co.uk", "bbc co uk"),            # esquema retirado
    ("Yahoo Finance", "Yahoo Finance"),                # nombre humano: intacto
])
def test_visible_medio_reversible_sin_forma_de_host(fuente, visible):
    """Separacion de puntos: reversible, conserva componentes en orden,
    sin inferir marca ni recortar sufijos; nunca forma de localizador."""
    assert _visible_medio(fuente) == visible
    assert not _URL_RE.search(visible)


def test_fact_pack_no_expone_host_y_conserva_fuente():
    facts = fact_pack(
        company=SimpleNamespace(currency="USD", ticker="META", name="Meta Platforms"),
        valuation={}, long_term_model={}, hypothesis=None,
        news_items=[{"source_headline": "Titular de prueba", "source": "waterford-news.ie",
                     "date": "2026-07-13", "date_source": "gdelt_first_seen",
                     "url": "https://waterford-news.ie/pieza-real"}],
    )
    news_facts = [f for f in facts if "publicó" in f["texto"]]
    assert len(news_facts) == 1
    assert "waterford-news ie publicó" in news_facts[0]["texto"]
    assert not _URL_RE.search(news_facts[0]["texto"])
    assert news_facts[0]["fuente"] == "https://waterford-news.ie/pieza-real"


# ---------------------- regla URL / numericos / veredicto (deep, sintetico)

def _facts():
    return [
        {"id": "fA", "texto": "Hecho sintetico alfa.", "fuente": "Registro interno A."},
        {"id": "fB", "texto": "Hecho sintetico beta.", "fuente": "Registro interno B."},
        {"id": "fC", "texto": "Hecho sintetico gamma.", "fuente": "Registro interno C."},
    ]


def _parsed(extra_que_sabemos=""):
    def seccion(sid, titulo, texto):
        return {"id": sid, "titulo": titulo, "parrafos": [texto], "fact_ids": ["fA", "fB", "fC"]}

    cuerpo = PROSA + " " + PROSA + (" " + extra_que_sabemos if extra_que_sabemos else "")
    return {"secciones": [
        seccion("que_sabemos", "Hechos", cuerpo),
        seccion("como_se_construye", "Mecanica", PROSA + " " + PROSA),
        seccion("fuentes_y_anclaje", "Fuentes", PROSA + " " + PROSA),
        seccion("lo_que_no_sabemos", "Huecos", PROSA + " " + PROSA),
    ]}


def test_regla_url_prosa_limpia_valida():
    sections, rule = _validate_sections(_parsed(), _facts())
    assert rule is None
    assert any("Fuentes citadas:" in p for p in sections[0]["parrafos"])


@pytest.mark.parametrize("inyeccion", [
    "fuente: https://waterford-news.ie/articulo-real",
    "www.waterford-news.ie lo confirmo",
    "segun medionoincluido-example.com en su edicion de hoy",
    "la pieza waterford-news.ie/noticia/123 lo detalla",
    "el medio waterford-news.ie lo publico",   # nombre con forma de host: prohibicion absoluta
])
def test_hosts_y_urls_rechazados(inyeccion):
    sections, rule = _validate_sections(_parsed("El registro anade que " + inyeccion + " sin mas detalle verificado."), _facts())
    assert sections is None and rule == "url_detectada", inyeccion


def test_cifra_no_anclada_y_veredicto_rechazados():
    _, rule = _validate_sections(
        _parsed("El consenso externo situa el objetivo en 999.99 USD por accion segun analistas."), _facts())
    assert rule == "cifra_no_anclada"
    _, rule = _validate_sections(
        _parsed("Recomendamos comprar la accion en estos niveles de precio registrados."), _facts())
    assert rule == "lenguaje_veredicto"
