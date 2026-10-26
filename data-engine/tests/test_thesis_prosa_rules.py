"""Reglas de prosa de los validadores de tesis: tests autocontenidos.

Sin artefactos externos ni capturas privadas: todas las fixtures son
sinteticas e inline. El replay opcional con las respuestas reales del
ensayo run1 vive en test_offline_run1_replay.py.
"""
from types import SimpleNamespace

import pytest

from app.services.thesis_deep_narrative import (
    _URL_RE,
    _norm_number,
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


def test_deep_cifra_con_puntuacion_final_se_ancla() -> None:
    """La puntuación final arrastrada por la tokenización no rompe el anclaje.

    Caso run2 real: el modelo cerró una enumeración con «642.62,» y el
    validador rechazó la narrativa pese a que 642.62 era cifra del pack.
    """
    pack = _facts() + [{"id": "fD", "texto": "Precio: 642.62 USD. Escenario base: 567.34 USD.",
                        "fuente": "generica://mercado/precio"}]
    sections, rule = _validate_sections(
        _parsed("Base 567.34 USD; precio de referencia 642.62, según el pack."), pack)
    assert rule is None


def test_deep_cifra_no_anclada_con_puntuacion_final_sigue_rechazada() -> None:
    sections, rule = _validate_sections(
        _parsed("El precio era 999.99, cifra inventada."), _facts())
    assert rule == "cifra_no_anclada"


@pytest.mark.parametrize("token,esperado", [
    # aceptadas: cifra limpia o con UNA puntuación de cierre inequívoca
    ("642.62", "642.62"), ("642.62,", "642.62"), ("642.62.", "642.62"),
    ("-642.62,", "-642.62"), ("22,9%", "22.9"),
    ("1.234,56", "1234.56"), ("1.234", "1234"), ("22,9", "22.9"),
    ("-69,69", "-69.69"), ("2,1", "2.1"), ("642", "642"), ("642.", "642"),
    # rechazadas: separadores múltiples, % con separador interior o forma
    # malformada (basura no se normaliza; el % cierra el token y la
    # puntuación natural de la prosa queda fuera de él)
    ("642.62,,", None), ("642.62.,", None), ("642,,", None),
    ("22,9.%", None), ("22,9,%", None), ("642.62,%", None),
    ("642.62.5", None), ("1,234.56", None), ("1,234.56,", None),
    ("12.34.56", None), ("6.42.62", None), ("1.2.3", None),
])
def test_deep_normalizacion_matriz(token, esperado) -> None:
    """Matriz completa del normalizador: signos, %, puntuación simple vs
    múltiple y formas malformadas. «1,234.56» (en-US completo) se rechaza
    desde antes de run2; comportamiento preexistente fuera de alcance."""
    assert _norm_number(token) == esperado


def test_deep_porcentaje_con_puntuacion_natural_ancla() -> None:
    """«22,9%,» y «22,9 %.» tokenizan sin puntuación dentro del token."""
    pack = _facts() + [{"id": "fD", "texto": "Margen FCF: 22,9 %.",
                        "fuente": "generica://finanzas/margen"}]
    sections, rule = _validate_sections(_parsed("El margen fue 22,9%, según el pack."), pack)
    assert rule is None
    sections, rule = _validate_sections(_parsed("El margen fue 22,9 %. Luego sigue."), pack)
    assert rule is None


def test_deep_token_malformado_no_ancla_por_prefijo() -> None:
    """«642.62.5» tokeniza como UNA cifra malformada: no ancla aunque el pack
    contenga 642.62 (no hay aceptación por prefijo)."""
    pack = _facts() + [{"id": "fD", "texto": "Precio: 642.62 USD.",
                        "fuente": "generica://mercado/precio"}]
    sections, rule = _validate_sections(_parsed("El valor 642.62.5 puntos."), pack)
    assert rule == "cifra_no_anclada"


def test_news_ordinales_retoricos_siguen_rechazados_por_diseno() -> None:
    """Run2: «efectos de segundo orden» / «Un segundo riesgo» dispararon
    cantidad_en_prosa_llm. No es falso positivo léxico (como «un tercero»
    sustantivo): la prohibición ordinal es regla de diseño. El validador se
    mantiene; la composición se guía desde el prompt.
    """
    raw = _news_raw(PROSA)
    raw["implicaciones"] = {
        "texto": "El desplome en otro valor sugiere efectos de segundo orden.",
        "evidence_ids": ["news:1"],
    }
    raw["riesgos"] = {
        "texto": "Un segundo riesgo es la lectura editorial de los titulares.",
        "evidence_ids": ["news:2"],
    }
    with pytest.raises(ValueError, match="cantidad_en_prosa_llm"):
        validate_output(raw, _headlines())


def test_news_prompt_guia_ordinales() -> None:
    from app.services.thesis_news_narrative import build_request
    req = build_request("META", [{"id": "n1", "headline": "H", "source": "S", "url": "https://x", "snippet": None}])
    assert req.messages[0].role == "system"
    prompt = req.messages[0].content
    assert "efectos indirectos" in prompt
    assert "un riesgo adicional" in prompt


def _pack_con(*textos: str) -> list[dict]:
    """Pack sintético con fA..fC garantizados (citados por _parsed)."""
    base = list(textos) + ["Hecho sintético de relleno."] * (3 - len(textos))
    ids = ["fA", "fB", "fC", "fD"]
    return [{"id": ids[i], "texto": t, "fuente": "generica://registro"} for i, t in enumerate(base)]


def test_ambigua_copia_literal_ancla() -> None:
    """«0.021»↔«0.021» ancla: prueba copia de superficie, NO equivalencia de magnitud."""
    sections, rule = _validate_sections(
        _parsed("La ratio registrada fue 0.021 en el periodo."), _pack_con("Ratio: 0.021."))
    assert rule is None


def test_ambigua_con_puntuacion_de_cierre_ancla() -> None:
    sections, rule = _validate_sections(
        _parsed("Las ratios fueron 0.021, según el registro."), _pack_con("Ratio: 0.021."))
    assert rule is None


def test_ambigua_no_ancla_entero_canonico() -> None:
    """«0.021» del pack no ancla «21» de la prosa: equivalencia cruzada prohibida."""
    sections, rule = _validate_sections(
        _parsed("El conteo registrado fue 21 en el periodo."), _pack_con("Ratio: 0.021."))
    assert rule == "cifra_no_anclada"


def test_entero_no_ancla_superficie_ambigua() -> None:
    """«21» del pack no ancla «0.021» de la prosa (dirección inversa)."""
    sections, rule = _validate_sections(
        _parsed("La ratio registrada fue 0.021 en el periodo."), _pack_con("Conteo: 21."))
    assert rule == "cifra_no_anclada"


def test_explicito_coexistente_con_ambigua_sigue_anclando() -> None:
    """Pack con «0.021» Y «21»: el «21» explícito ancla por su hecho explícito."""
    sections, rule = _validate_sections(
        _parsed("El conteo registrado fue 21 en el periodo."), _pack_con("Ratio: 0.021.", "Conteo: 21."))
    assert rule is None


def test_ambigua_signo_y_porcentaje() -> None:
    pack = _pack_con("Variación: -0.021.", "Ratio: 0.021.")
    sections, rule = _validate_sections(_parsed("La variación fue -0.021 en el periodo."), pack)
    assert rule is None
    sections, rule = _validate_sections(_parsed("La variación fue 0.021 en el periodo."), _pack_con("Variación: -0.021."))
    assert rule == "cifra_no_anclada"
    sections, rule = _validate_sections(_parsed("El ratio fue 0.021% en el periodo."), _pack_con("Ratio: 0.021."))
    assert rule is None
    sections, rule = _validate_sections(_parsed("El ratio fue 0.021% en el periodo."), _pack_con("Conteo: 21 %."))
    assert rule == "cifra_no_anclada"


def test_ambigua_doble_separador_rechazada() -> None:
    sections, rule = _validate_sections(
        _parsed("La ratio fue 0.021,, en el periodo."), _pack_con("Ratio: 0.021."))
    assert rule == "cifra_no_anclada"
