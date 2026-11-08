"""Reglas de agrupación de historias (news_story_cluster) fijadas con casos
límite y negativos. El índice ya tiene su test de equivalencia; aquí se fija
el criterio documentado en el módulo: ventana de 48 h, mínimo de tokens de
firma, umbrales Jaccard/contención y la vía de tokens distintivos."""

from datetime import UTC, datetime, timedelta

from app.models import Company
from app.models.entities import NewsEvent
from app.services.news_headline_translation import fingerprint, original_headline
from app.services.news_story_cluster import (
    CONTAINMENT_MIN,
    JACCARD_MIN,
    WINDOW,
    _company_tokens,
    distinctive,
    event_signature,
    exact_key,
    same_story,
    signature,
)

NOW = datetime(2026, 11, 8, 12, tzinfo=UTC)


def _sig(*tokens: str) -> set[str]:
    return set(tokens)


class TestSameStoryVentana:
    def test_dentro_de_la_ventana_agrupa(self):
        sig = _sig("fotovoltaica", "desplome", "aranceles")
        assert same_story(sig, sig, NOW, NOW - (WINDOW - timedelta(minutes=1)))

    def test_fuera_de_la_ventana_no_agrupa_aunque_la_firma_sea_identica(self):
        sig = _sig("fotovoltaica", "desplome", "aranceles")
        assert not same_story(sig, sig, NOW, NOW - (WINDOW + timedelta(minutes=1)))


class TestSameStoryFirmaMinima:
    def test_firma_de_dos_tokens_identica_no_agrupa(self):
        # Titulares de una o dos palabras: la regla de solape no aplica aunque
        # Jaccard sea 1.0 (los agrupa exact_key, no same_story).
        sig = _sig("merger", "chip")
        assert not same_story(sig, sig, NOW, NOW)

    def test_firma_de_tres_tokens_identica_agrupa(self):
        sig = _sig("merger", "chip", "rally")
        assert same_story(sig, sig, NOW, NOW)


class TestSameStoryUmbrales:
    def test_jaccard_en_el_umbral_agrupa(self):
        # 2 compartidos / 4 unión = 0.50 exacto.
        assert same_story(_sig("aa", "bb", "cc"), _sig("aa", "bb", "dd"), NOW, NOW)

    def test_por_debajo_de_todos_los_umbrales_no_agrupa(self):
        # Jaccard 2/7 ~= 0.29, contención 2/4 = 0.50, sin distintivos compartidos.
        assert not same_story(
            _sig("w01", "w02", "w03", "w04"),
            _sig("w01", "w02", "w05", "w06", "w07"),
            NOW,
            NOW,
        )

    def test_contencion_en_el_umbral_agrupa(self):
        # 13 compartidos / firma menor de 20 = 0.65 exacto; Jaccard 13/32 < 0.50.
        shared = {f"s{i:02d}" for i in range(13)}
        sig_a = shared | {f"a{i:02d}" for i in range(12)}
        sig_b = shared | {f"b{i:02d}" for i in range(7)}
        assert len(sig_a & sig_b) / len(sig_a | sig_b) < JACCARD_MIN
        assert same_story(sig_a, sig_b, NOW, NOW)

    def test_contencion_justo_por_debajo_no_agrupa(self):
        # 12/20 = 0.60 < 0.65 y Jaccard 12/31 < 0.50, sin distintivos.
        shared = {f"s{i:02d}" for i in range(12)}
        sig_a = shared | {f"a{i:02d}" for i in range(12)}
        sig_b = shared | {f"b{i:02d}" for i in range(7)}
        assert len(sig_a & sig_b) / min(len(sig_a), len(sig_b)) < CONTAINMENT_MIN
        assert not same_story(sig_a, sig_b, NOW, NOW)

    def test_dos_distintivos_compartidos_agrupan_con_solape_bajo(self):
        # Jaccard 2/10 y contención 2/5, pero dos tokens raros compartidos.
        sig_a = _sig("fotovoltaica", "desplome", "w01", "w02", "w03")
        sig_b = _sig("fotovoltaica", "desplome", "w04", "w05", "w06", "w07", "w08")
        assert same_story(sig_a, sig_b, NOW, NOW)

    def test_un_solo_distintivo_compartido_no_basta(self):
        sig_a = _sig("fotovoltaica", "w01", "w02", "w03", "w04")
        sig_b = _sig("fotovoltaica", "w05", "w06", "w07", "w08", "w09", "w10")
        assert not same_story(sig_a, sig_b, NOW, NOW)

    def test_sin_tokens_compartidos_no_agrupa(self):
        assert not same_story(
            _sig("fotovoltaica", "desplome", "aranceles"),
            _sig("chip", "rally", "guidance"),
            NOW,
            NOW,
        )


class TestSignature:
    def test_quita_stopwords_en_ambos_idiomas_y_el_ticker(self):
        company_tokens = _company_tokens("TSLA", None)
        sig = signature("TSLA and the market cae tras los resultados", company_tokens)
        assert "tsla" not in sig
        assert "and" not in sig and "the" not in sig
        assert "tras" not in sig and "los" not in sig
        assert "cae" in sig

    def test_el_vocabulario_financiero_generico_se_queda_en_la_firma(self):
        # Lo filtra distinctive(), no signature(): forma parte del solape.
        sig = signature("Earnings results guidance", set())
        assert sig == {"earnings", "results", "guidance"}

    def test_pliega_tildes_y_descarta_tokens_de_un_caracter(self):
        sig = signature("Acción y inversión a largo plazo", set())
        assert "accion" in sig
        assert "inversion" in sig
        assert "y" not in sig and "a" not in sig

    def test_tokens_de_empresa_incluyen_el_nombre_completo(self):
        company = Company(ticker="MTSF", name="Mundo Torres Solar")
        company_tokens = _company_tokens(company.ticker, company)
        sig = signature("Mundo Torres anuncia una ampliación fotovoltaica", company_tokens)
        # Todos los tokens del nombre de la empresa salen de la firma.
        assert "mundo" not in sig and "torres" not in sig and "solar" not in sig
        assert "ampliacion" in sig and "fotovoltaica" in sig


class TestDistinctive:
    def test_solo_alfabeticos_largos_fuera_del_vocabulario_generico(self):
        tokens = _sig("fotovoltaica", "earnings", "resultados", "q32026", "corto")
        assert distinctive(tokens) == {"fotovoltaica"}

    def test_el_generico_financiero_no_distingue_aunque_sea_largo(self):
        assert distinctive(_sig("resultados", "trimestral", "recomendacion")) == set()


class TestExactKey:
    def test_insensible_a_mayusculas_tildes_y_signos(self):
        assert exact_key("¡Tesla Cae un 3%!") == exact_key("tesla   cae un 3%")

    def test_colapsa_espacios_y_descarta_lo_no_alfanumerico(self):
        assert exact_key("  Nvidia  —  resultados  ") == "nvidia resultados"


def _event(title: str, translation: str | None = None) -> NewsEvent:
    metadata: dict = {"connector": "rss", "date_source": "source"}
    if translation is not None:
        metadata["headline_translation"] = {
            "fingerprint": fingerprint(title),
            "status": "translated",
            "text": translation,
        }
    return NewsEvent(
        tenant_id=1,
        company_id=None,
        title=title,
        source="rss",
        url="https://example.com/1",
        date=NOW,
        metadata_=metadata,
    )


class TestEventSignature:
    def test_une_titular_original_y_traduccion_cacheada(self):
        event = _event(
            "Microsoft announces fotovoltaica partnership in Seville",
            "Microsoft anuncia una alianza fotovoltaica en Sevilla",
        )
        sig = event_signature(event, None)
        # Tokens de los dos idiomas: la firma no queda en un solo idioma.
        assert "announces" in sig and "alianza" in sig
        assert "fotovoltaica" in sig

    def test_traduccion_con_huella_obsoleta_se_ignora(self):
        event = _event("Microsoft announces fotovoltaica partnership", "texto traducido")
        event.metadata_["headline_translation"]["fingerprint"] = "0" * 64
        sig = event_signature(event, None)
        assert "traducido" not in sig
        assert "announces" in sig

    def test_sin_traduccion_usa_el_titular_original(self):
        event = _event("Solo titular original disponible")
        assert original_headline(event) == "Solo titular original disponible"
        sig = event_signature(event, None)
        assert "titular" in sig and "original" in sig
