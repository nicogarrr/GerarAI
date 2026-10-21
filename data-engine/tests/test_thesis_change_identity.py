"""Agrupación de cambios de tesis por identidad atribuida (QA ASTS 21-oct-2026).

La misma noticia publicada en dos idiomas creaba dos cambios («Desde tu
última visita» los mostraba duplicados). Solo la identidad atribuida agrupa:
mismo evento, misma URL, mismo titular o traducción atribuida exacta. Las
fuentes absorbidas quedan revisables en ``tambien_en``; nada se borra.
"""

from app.services.thesis_change_identity import ChangeItem, group_change_items, identity_keys


def _item(orden: int, **kwargs) -> ChangeItem:
    base = dict(
        resumen=f"Cambio {orden}",
        direccion="neutral",
        requiere_revision=True,
        fecha="2026-10-21",
        orden=orden,
    )
    base.update(kwargs)
    return ChangeItem(**base)


def test_puente_traduccion_atribuida_agrupada_y_conserva_ambas_urls():
    es = _item(
        0,
        news_event_id=183312,
        fuente_url="https://news.google.com/rss/articles/CBMiES?oc=5",
        fuente_nombre="TradingView",
        titular_original="Datos clave: NASDAQ:ASTS: más de 3,000 celdas en EE. UU.",
    )
    en = _item(
        1,
        news_event_id=183191,
        fuente_url="https://news.google.com/rss/articles/CBMiEN?oc=5",
        fuente_nombre="TradingView",
        titular_original="Key facts: NASDAQ:ASTS 3,000+ U.S. Cells",
        traduccion_titular="Datos clave: NASDAQ:ASTS: más de 3,000 celdas en EE. UU.",
    )
    grouped = group_change_items([es, en])
    assert len(grouped) == 1
    assert grouped[0].fuente_url == es.fuente_url
    assert grouped[0].tambien_en == [
        {"url": en.fuente_url, "fuente": "TradingView", "fecha": "2026-10-21"}
    ]


def test_misma_url_con_parametros_distintos_agrupada():
    a = _item(0, fuente_url="https://example.com/news/1?utm_source=rss")
    b = _item(1, fuente_url="https://example.com/news/1")
    assert len(group_change_items([a, b])) == 1


def test_sin_identidad_atribuida_no_agrupa_aunque_se_parezcan():
    a = _item(0, fuente_url="https://a.example/1", titular_original="ASTS firma bonos convertibles")
    b = _item(1, fuente_url="https://b.example/2", titular_original="ASTS signs convertible notes")
    grouped = group_change_items([a, b])
    assert len(grouped) == 2


def test_sin_puente_de_evento_el_cambio_queda_intacto():
    a = _item(0)
    b = _item(1)
    grouped = group_change_items([a, b])
    assert len(grouped) == 2
    assert all(not item.tambien_en for item in grouped)


def test_el_representante_hereda_requiere_revision():
    a = _item(0, requiere_revision=False, fuente_url="https://example.com/x")
    b = _item(1, requiere_revision=True, fuente_url="https://example.com/x")
    grouped = group_change_items([a, b])
    assert len(grouped) == 1
    assert grouped[0].requiere_revision is True


def test_identity_keys_sin_evidencia_es_vacio():
    assert identity_keys(_item(0)) == set()
