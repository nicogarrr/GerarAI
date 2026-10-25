"""Modo analisis: estructura completa y validada, o degradacion honesta a fragmentos."""

import asyncio
import copy

from app.services import knowledge_analysis
from app.services.knowledge_chat import ask_library, retrieve
from tests.test_knowledge_chat import Provider, setup_library

QUOTE = "Repurchases can add value at sensible prices."


def good(chunk_id: int) -> dict:
    def cited(text, **extra):
        return {"text": text, "chunk_id": chunk_id, "quote": QUOTE, **extra}

    return {
        "tesis": [
            cited("Las recompras crean valor a buen precio."),
            cited("El precio manda."),
            cited("Sin precio sensato no hay valor."),
        ],
        "error": cited("Pagar de más por recomprar destruye valor."),
        "escenarios": [
            {
                "nombre": "Precio razonable",
                "probabilidad": 50,
                "disparador": "La acción cotiza bajo su valor.",
            },
            {"nombre": "Precio alto", "probabilidad": 30, "disparador": "La acción cotiza sobre su valor."},
            {"nombre": "Sin caja", "probabilidad": 20, "disparador": "La empresa necesita el capital."},
        ],
        "modelos": [cited("Margen de seguridad.", nombre="Margen de seguridad")],
        "no_se": ["No sé cuál es el precio actual de ninguna acción."],
    }


def run(monkeypatch, payload=None, provider=None, **kwargs):
    monkeypatch.setenv("CAVAAI_ENABLE_VECTOR_SEARCH", "0")
    db = setup_library()
    chunk = retrieve(db, "repurchases", scope="letters", author="Buffett")[0][0][0]
    provider = provider or Provider(payload(chunk.id) if callable(payload) else payload)
    result = asyncio.run(
        ask_library(db, "repurchases", author="Buffett", mode="analisis", provider=provider, **kwargs)
    )
    return result, provider


def mutate(fn):
    def build(chunk_id):
        data = good(chunk_id)
        fn(data)
        return data

    return build


def test_analisis_valido_se_entrega_completo_con_citas_y_aviso(monkeypatch):
    result, provider = run(monkeypatch, good)
    assert result["status"] == "ok" and result["mode"] == "analisis" and result["answers"] == []
    analysis = result["analysis"]
    assert len(analysis["tesis"]) == 3 and len(analysis["escenarios"]) == 3
    assert sum(s["probabilidad"] for s in analysis["escenarios"]) == 100
    assert (
        analysis["tesis"][0]["citation"]["quote"] == QUOTE
        and analysis["tesis"][0]["citation"]["page_number"] == 8
    )
    assert analysis["modelos"][0]["nombre"] == "Margen de seguridad"
    assert (
        "No es consejo financiero" in analysis["aviso"]
        and "Estimación del modelo" in analysis["probabilidades"]
    )
    assert "EXACTAMENTE 3" in provider.request.messages[0].content


def test_el_modo_normal_no_cambia(monkeypatch):
    monkeypatch.setenv("CAVAAI_ENABLE_VECTOR_SEARCH", "0")
    result = asyncio.run(ask_library(setup_library(), "repurchases", author="Buffett", provider=Provider()))
    assert result["status"] == "ok" and "analysis" not in result and result["mode"] == "respuesta"


def check_degrada(result):
    assert result["status"] == "fragmentos" and "analysis" not in result
    assert "no está disponible" in result["message"] and "citados" not in result["message"]
    assert result["answers"] and all(a["text"] is None and a["citation"]["quote"] for a in result["answers"])


def test_modelo_caido_degrada_a_fragmentos_citados(monkeypatch):
    result, _ = run(monkeypatch, provider=Provider(fail=True))
    check_degrada(result)


def test_json_invalido_o_incompleto_degrada(monkeypatch):
    for bad in [{}, {"tesis": "x"}, [], {"answers": []}]:
        check_degrada(run(monkeypatch, bad)[0])


def test_cada_defecto_estructural_invalida_todo_el_analisis(monkeypatch):
    casos = {
        "dos tesis": lambda d: d["tesis"].pop(),
        "cuatro tesis": lambda d: d["tesis"].append(d["tesis"][0]),
        "probabilidades no suman 100": lambda d: d["escenarios"][0].update(probabilidad=51),
        "probabilidad como texto": lambda d: d["escenarios"][0].update(probabilidad="50"),
        "probabilidad booleana": lambda d: d["escenarios"][0].update(probabilidad=True),
        "probabilidad negativa": lambda d: d["escenarios"][0].update(probabilidad=-10),
        "dos escenarios": lambda d: d["escenarios"].pop(),
        "escenario sin disparador": lambda d: d["escenarios"][1].pop("disparador"),
        "sin error": lambda d: d.pop("error"),
        "sin modelos": lambda d: d.update(modelos=[]),
        "modelo sin nombre": lambda d: d["modelos"][0].pop("nombre"),
        "sin lo que no se": lambda d: d.update(no_se=[]),
        "no_se no es texto": lambda d: d.update(no_se=[5]),
    }
    for name, fn in casos.items():
        result, _ = run(monkeypatch, mutate(fn))
        assert result["status"] == "fragmentos", name
        check_degrada(result)


def test_cita_inventada_o_ajena_invalida_el_analisis(monkeypatch):
    for fn in [
        lambda d: d["tesis"][1].update(quote="Fabricated quote about repurchases"),
        lambda d: d["error"].update(chunk_id=99999),
        lambda d: d["modelos"][0].update(quote="x" * 10),
    ]:
        check_degrada(run(monkeypatch, mutate(fn))[0])


def test_cifras_solo_del_contexto(monkeypatch):
    casos = [
        lambda d: d["tesis"][0].update(text="Rentabilidad del 50 %"),  # cifra que no esta en su cita
        lambda d: d["escenarios"][0].update(disparador="Cae un 35 % el beneficio"),  # no esta en el contexto
        lambda d: d["no_se"].append("No sé si en 2031 habrá recompras"),
    ]
    for fn in casos:
        check_degrada(run(monkeypatch, mutate(fn))[0])


def test_sin_fragmentos_no_llama_al_modelo(monkeypatch):
    monkeypatch.setenv("CAVAAI_ENABLE_VECTOR_SEARCH", "0")
    provider = Provider()
    result = asyncio.run(
        ask_library(setup_library(), "satellites launch", mode="analisis", provider=provider)
    )
    assert result["status"] == "sin_datos" and provider.request is None


def test_validacion_no_muta_el_payload_del_modelo(monkeypatch):
    seen = {}

    def build(chunk_id):
        seen["data"] = good(chunk_id)
        seen["copy"] = copy.deepcopy(seen["data"])
        return seen["data"]

    run(monkeypatch, build)
    assert seen["data"] == seen["copy"]


def test_cita_de_solo_espacios_o_saltos_de_linea_no_es_cita_literal(monkeypatch):
    # Un chunk de PDF maquetado puede traer rachas largas de blanco: la "cita" vacia pasaria `in`.
    blanks = " " * 15 + "\n" * 15
    for quote in [blanks, " " * 40, "." * 30, "- " * 20]:
        db = setup_library()
        chunk = retrieve(db, "repurchases", scope="letters", author="Buffett")[0][0][0]
        chunk.content = chunk.content + "\n" + quote + "\nfin"
        db.commit()
        data = good(chunk.id)
        for part in [*data["tesis"], data["error"], *data["modelos"]]:
            part["quote"] = quote
        result = asyncio.run(
            ask_library(db, "repurchases", author="Buffett", mode="analisis", provider=Provider(data))
        )
        check_degrada(result)


def test_la_cita_se_guarda_sin_bordes_en_blanco(monkeypatch):
    result, _ = run(monkeypatch, mutate(lambda d: d["error"].update(quote="  " + QUOTE + "\n ")))
    assert result["analysis"]["error"]["citation"]["quote"] == QUOTE


def test_ruta_normal_tampoco_acepta_citas_en_blanco(monkeypatch):
    monkeypatch.setenv("CAVAAI_ENABLE_VECTOR_SEARCH", "0")
    db = setup_library()
    chunk = retrieve(db, "repurchases", scope="letters", author="Buffett")[0][0][0]
    chunk.content = chunk.content + "\n" + " " * 30 + "\nfin"
    db.commit()
    item = {"chunk_id": chunk.id, "quote": " " * 30, "text": "vacio"}
    result = asyncio.run(
        ask_library(db, "repurchases", author="Buffett", provider=Provider({"answers": [item]}))
    )
    assert result["status"] == "fragmentos" and all(a["text"] is None for a in result["answers"])


_SENT = "El margen de seguridad es\nla diferencia entre el precio  y el valor intrínseco.\nEs la clave de la inversión."


def test_clean_quote_literal_unchanged():
    quote = "la diferencia entre el precio  y el valor intrínseco."
    assert knowledge_analysis.clean_quote(quote, _SENT) == quote


def test_clean_quote_whitespace_collapse_returns_exact_source_span():
    got = knowledge_analysis.clean_quote("El margen de seguridad es la diferencia entre el precio y el valor", _SENT)
    assert got == "El margen de seguridad es\nla diferencia entre el precio  y el valor"
    assert got in _SENT


def test_clean_quote_still_rejects_non_literal_words():
    for bad in (
        "El margen de seguridad es ... la clave de la inversión.",
        "El margen de seguridad es la distancia entre el precio y el valor",
        "margen de seguridad",
        "   ",
    ):
        assert knowledge_analysis.clean_quote(bad, _SENT) is None


def test_clean_quote_rejects_cut_words_collapsed_path():
    sent = "El sobreprecio y el valor intrínseco es la clave real de todo esto"
    assert knowledge_analysis.clean_quote("precio y el valor intrínseco es la clave", sent) is None
    sent2 = "la diferencia entre el precio y el valorado hoy es alta"
    assert knowledge_analysis.clean_quote("la diferencia entre el precio y el valor", sent2) is None


def test_clean_quote_rejects_cut_words_literal_path():
    sent = "xx sobreprecio y el valor intrínseco es la clave real"
    assert knowledge_analysis.clean_quote("precio y el valor intrínseco es la clave", sent) is None
    assert knowledge_analysis.clean_quote("sobreprecio y el valor intrínseco es la clave", sent) is not None


def test_clean_quote_span_inflated_by_whitespace_is_rejected():
    sent = "uno" + " " * 1000 + "dos tres cuatro cinco seis siete ocho nueve"
    assert knowledge_analysis.clean_quote("uno dos tres cuatro cinco seis siete ocho nueve", sent) is None


def test_clean_quote_punctuation_edges_ok():
    sent = "dijo: «el margen de seguridad es clave», y siguio."
    assert knowledge_analysis.clean_quote("el margen de seguridad es clave", sent) == "el margen de seguridad es clave"
    assert knowledge_analysis.clean_quote("«el margen de seguridad es clave»", sent) == "«el margen de seguridad es clave»"
