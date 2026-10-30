"""Narrativa extensa de la tesis REDACTADA por el modelo configurado (OpenCode Go).

A diferencia del selector de plantillas de `thesis_narrative_llm.py` (el modelo
solo elegia ids, 200 tokens), aqui el modelo SI escribe la explicacion larga
que pide el dueno: que significa cada cifra, que supuestos la sostienen, de que
fuente sale y que no sabemos. El anclaje es por construccion:

- El paquete de hechos lo monta el codigo con las relaciones cifra-campo-
  unidad-periodo ya verificadas (mismas plantillas deterministicas de base).
- La salida se valida fail-closed: ninguna cifra ni URL que no este en el
  paquete, secciones obligatorias, gaps explicitos siempre, sin veredictos de
  compra/venta (tesis provisional explicativa, no recomendacion publicable).
- El RAG NO se vuelca: el paquete solo expone titulo y localizador de cada
  documento (nunca el texto del chunk), asi el modelo no puede transcribir
  prosa de terceros ni filtrar contenido interno como si fuera analisis.
- Toda llamada registra consumo y el modelo ejecutado (traza real vs fallback)
  para que el despliegue pueda verificar que la tesis usa el modelo Go
  configurado y no otro.

Cualquier fallo (flag, proveedor, presupuesto, red, JSON o validacion) deja la
narrativa existente intacta: esta capa nunca empeora la capa determinista.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.llm import (
    LLMRequest,
    Message,
    ResponseFormat,
    parse_json_response,
)
from app.llm.thesis_go import create_thesis_narrative_provider
from app.models.entities import Company, Document, FinancialFact
from app.services.async_bridge import run_from_any_context
from app.services.budget import BudgetController
from app.services.framework_terms_es import framework_term_es
from app.services.memo_text_es import date_es, percent_es
from app.services.number_format import format_compact_es
from app.services.prompt_registry import get_prompt
from app.services.text_clip import clip_words
from app.services.thesis_narrative_llm import _source_locator
from app.valuation.engines.base import margin_of_safety_reference

logger = logging.getLogger(__name__)

# Secciones cerradas: el modelo elige contenido, no estructura nueva.
SECTION_IDS = (
    "que_sabemos",
    "como_se_construye",
    "fuentes_y_anclaje",
    "lo_que_no_sabemos",
)
_MANDATORY_IDS = frozenset({"que_sabemos", "fuentes_y_anclaje", "lo_que_no_sabemos"})

# Nota de reintento por regla rechazada: acota la correccion pedida al
# modelo SIN relajar ninguna validacion. Nunca incluye salidas del modelo,
# hechos del paquete ni datos del tenant.
_RETRY_NOTES = {
    "sin_secciones": "Devuelve un objeto JSON con la clave secciones.",
    "seccion_invalida": (
        "Usa solo ids de seccion del contrato, sin repetir, con titulo breve "
        "y entre 1 y 6 parrafos por seccion."
    ),
    "fact_ids_invalidos": (
        "Cada seccion debe declarar fact_ids no vacios que existan en el "
        "paquete de hechos."
    ),
    "parrafo_invalido": "Cada parrafo debe tener entre 40 y 2000 caracteres.",
    "url_detectada": "No escribas ninguna URL ni dominio.",
    "lenguaje_veredicto": (
        "No uses lenguaje de veredicto (comprar, vender, recomendar): la "
        "tesis es explicativa y provisional."
    ),
    "markup_detectado": "Responde en texto plano, sin markdown ni HTML.",
    "cifra_no_anclada": (
        "No escribas ninguna cifra que no aparezca exactamente en un hecho "
        "del paquete: ni redondeos, ni derivadas, ni ordinales."
    ),
    "obligatorias_ausentes": (
        "Incluye todas las secciones obligatorias del contrato."
    ),
    "orden_indebido": (
        "Respeta el orden del contrato: que_sabemos primero y "
        "lo_que_no_sabemos la ultima."
    ),
    "longitud_total": (
        "La explicacion completa debe tener entre 800 y 20000 caracteres: "
        "desarrolla cada seccion con mas detalle anclado."
    ),
    "anclaje_insuficiente": (
        "Cita en conjunto al menos 3 hechos distintos del paquete."
    ),
    "json_no_parseable": "Responde solo con JSON valido, sin texto adicional.",
    "respuesta_degradada": "Responde completo, sin cortar la salida.",
}


_OUTPUT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "secciones": {
            "type": "array",
            "minItems": 3,
            "maxItems": 4,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["id", "titulo", "parrafos", "fact_ids"],
                "properties": {
                    "id": {"type": "string", "enum": list(SECTION_IDS)},
                    "titulo": {"type": "string"},
                    "parrafos": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 6,
                        "items": {"type": "string"},
                    },
                    "fact_ids": {
                        "type": "array",
                        "minItems": 1,
                        "items": {"type": "string"},
                    },
                },
            },
        }
    },
    "required": ["secciones"],
}

_DISCLAIMER_SECTION = {
    "titulo": "Salvedad",
    "parrafos": [
        "Esto no es recomendación de inversión. Es una explicación provisional "
        "de las cifras, supuestos y fuentes registradas en esta tesis, con los "
        "huecos de datos indicados: contrasta las fuentes y haz tu propio "
        "análisis antes de decidir."
    ],
}

_URL_RE = re.compile(
    r"(?:[a-z][a-z0-9+.-]*://|www\.)[^\s<>\"'\[\]()]+|"
    r"\b(?:[a-z0-9-]+\.)+[a-z]{2,}(?:/[^\s<>\"'\[\]()]*)?",
    re.IGNORECASE,
)
_NUMBER_RE = re.compile(r"-?\d[\d.,]*%?")
_MARKUP_RE = re.compile(r"<[a-zA-Z/][^>]*>|^#{1,6}\s|\*\*[^*]+\*\*", re.MULTILINE)
# Enteros triviales (conteos, ordinales, secciones): no son cifras de mercado.
_TRIVIAL_INTS = {str(n) for n in range(0, 13)}
# El modelo no decide recomendaciones: la tesis es explicativa y provisional.
_VERDICT_RE = re.compile(
    r"\b(comprar|vender|sobreponderar|infraponderar|recomendamos|recomendacion de (compra|venta))\b",
    re.IGNORECASE,
)

# Equivalencias demostradas de presentacion (no cambian el contenido):
# **negrita**, __negrita__, `codigo`, encabezados ATX y etiquetas HTML.
_MD_EM_RE = re.compile(r"\*\*([^*]+)\*\*|__([^_]+)__|`([^`]+)`")
_MD_HEADER_RE = re.compile(r"^#{1,6}\s+", re.MULTILINE)
_HTML_TAG_RE = re.compile(r"<[a-zA-Z/][^>]*>")


def _effort(section: str, explicit: str | None) -> str | None:
    """Valor explicito del env si existe; si no, la tabla por seccion."""
    if explicit is not None and explicit.strip():
        return explicit.strip()
    return get_settings().reasoning_effort_for(section)


def _strip_markup(text: str) -> str:
    """Quita marcadores de presentacion dejando el texto interior intacto.

    Equivalencia demostrada: «**cifra**» y «cifra» son el mismo contenido; la
    capa de render ya la posee el codigo. Las comprobaciones de URL y
    veredicto se hacen SIEMPRE sobre el texto original, asi que un enlace o
    un veredicto escondido en una etiqueta sigue rechazando el parrafo.
    """
    out = _MD_HEADER_RE.sub("", text)
    out = _MD_EM_RE.sub(lambda m: next(g for g in m.groups() if g is not None), out)
    out = _HTML_TAG_RE.sub("", out)
    return re.sub(r"[ \t]{2,}", " ", out).strip()


def _norm_number(token: str) -> str | None:
    """Normaliza una cifra a forma canonica para comparar pack vs salida.

    Acepta formato es-ES (1.234,56) y en-US (1234.56): el modelo copia la
    cifra tal cual aparece en el hecho y ambas superficies deben casar.
    """
    t = _surface_key(token)
    if not t:
        return None
    neg = t.startswith("-")
    t = t.lstrip("+-")
    # Miles es-ES: 1.234 o 1.234.567 con decimales tras coma opcionales.
    if re.fullmatch(r"\d{1,3}(\.\d{3})+(,\d+)?", t):
        t = t.replace(".", "")
    t = t.replace(",", ".")
    try:
        d = Decimal(t).normalize()
    except InvalidOperation:
        return None
    return ("-" if neg else "") + format(d, "f")


def _surface_key(token: str) -> str | None:
    """Superficie limpia de un token: sin % ni UNA puntuación de cierre.

    El % cierra el token: la puntuación natural de la prosa queda fuera
    («22,9%.» tokeniza «22,9%»). Un separador antes del % («22,9.%») es token
    malformado, no puntuación de cierre: no se arregla el interior. Fuera del
    %, una única puntuación de cierre («642.62,» al final de una enumeración)
    nunca es parte de la cifra; «642.62,,» o «642.62.,» son basura tipográfica
    y se conservan para que el normalizador las rechace.
    """
    t = token.strip()
    if t.endswith("%"):
        t = t[:-1].strip()
    elif len(t) >= 2 and t[-1] in ".," and t[-2].isdigit():
        t = t[:-1]
    return t or None


# Un solo punto seguido de exactamente 3 dígitos, sin coma: «0.021», «1.250».
# Es la única superficie con doble lectura (miles es-ES vs decimal de 3
# cifras); «1.234.567» o «1.234,56» no la tienen.
_AMBIGUOUS_SURFACE_RE = re.compile(r"^-?\d{1,3}\.\d{3}$")


def _allowed_numbers(facts: list[dict]) -> tuple[set[str], set[str]]:
    """(canónicas no ambiguas, superficies ambiguas literales del pack).

    Una superficie ambigua nunca aporta su canónica: «0.021» en el pack no
    ancla «21» en la prosa ni al revés. Solo ancla por igualdad literal de
    superficie, que prueba COPIA de la superficie, no equivalencia de
    magnitud. Las formas explícitas («21») siguen aportando su canónica aun
    cuando coexistan con una ambigua.
    """
    allowed = set(_TRIVIAL_INTS)
    surfaces: set[str] = set()
    for fact in facts:
        # Texto y fuente: el modelo ve ambos en el paquete y puede citar los
        # dos («sección 13 del memo»), asi que ambos anclan cifras permitidas.
        for field in (fact["texto"], fact["fuente"]):
            for match in _NUMBER_RE.findall(field):
                surface = _surface_key(match)
                if surface and _AMBIGUOUS_SURFACE_RE.match(surface):
                    surfaces.add(surface)
                    continue
                norm = _norm_number(match)
                if norm is not None:
                    allowed.add(norm)
    return allowed, surfaces


def _fact_id(n: int) -> str:
    """Identificador de hecho SIN dígitos: fA, fB, ..., fZ, fAA, ...

    El id viaja al prompt y el modelo lo copia a veces en la prosa; con
    dígitos («f15») esa copia caía en cifra_no_anclada. Con letras no hay
    token numérico que copiar y la validación no cambia.
    """
    letters = ""
    while n > 0:
        n, rem = divmod(n - 1, 26)
        letters = chr(ord("A") + rem) + letters
    return "f" + letters


def _visible_fuente(fuente: str) -> str:
    """Localizador visible para el modelo: NUNCA con URL/host.

    El localizador real (con URL) lo conserva el código para las citas que
    inserta; el modelo no necesita ver dominios y, si los ve, los copia a la
    prosa (rechazo url_detectada medido 2026-10-26, host del paquete).
    """
    if _URL_RE.search(fuente):
        # Un titular o una URL acreditan publicación/registro, NO veracidad:
        # la palabra "verificada" aquí se coló a la narrativa como claim falso.
        return (
            "Fuente registrada por el código (el localizador completo lo "
            "inserta la capa de citas); acredita publicación, no veracidad."
        )
    return fuente


#: Conjunto cerrado de métricas de fundamentales que entran en el paquete,
#: con su etiqueta (misma tabla que thesis_service._METRIC_LABELS_ES; se
#: duplica aquí para no crear un ciclo de importación tesis<->narrativa).
_FUNDAMENTAL_LABELS: dict[str, str] = {
    "revenue": "Ingresos",
    "free_cash_flow": "Flujo de caja libre",
    "fcf_margin": "Margen de FCF",
    "revenue_growth": "Crecimiento de ingresos",
    "operating_cash_flow": "Flujo de caja operativo",
    "capital_expenditure": "Gasto de capital (CapEx)",
    "net_debt": "Deuda neta",
    "shares_diluted": "Acciones diluidas",
    "cash_and_equivalents": "Efectivo y equivalentes",
    "total_debt": "Deuda total",
}

#: Etiquetas de drivers del marco con dato (claves conocidas; el resto se
#: muestra como clave entre comillas, nunca traducida a una frase inventada).
_DRIVER_LABELS_ES: dict[str, str] = {
    "ad_impressions": "impresiones publicitarias",
    "price_per_ad": "precio por anuncio",
    "daily_active_people": "personas activas al día",
    "family_arpu": "ingreso medio por usuario de la familia de apps",
    "operating_margin": "margen operativo",
    "capex": "gasto de capital",
}


def _fact_source_locator(fact: FinancialFact) -> str:
    """Localizador real del hecho financiero: URL del documento fuente si el
    registro la tiene (un id de fact NO sustituye la URL), si no, etiqueta."""
    # nosemgrep: gerarai-broad-except-pass -- localizador opcional de la sesion; nunca rompe el paquete
    try:
        from sqlalchemy.orm import object_session

        session = object_session(fact)
        if session is not None and fact.source_id is not None:
            document = session.get(Document, fact.source_id)
            if document is not None and document.source_url:
                return document.source_url
    except Exception:  # noqa: BLE001 - el localizador nunca rompe el paquete
        pass
    return f"Registro interno de datos financieros ({fact.source_type})."


_METRIC_RECORD_RE = re.compile(r"^[A-Za-z_]*Metric #\d+:\s*")
_DEFINITION_SUFFIX_RE = re.compile(r";\s*definition=\S+\s*$")


def _assumption_basis_text(entry: dict) -> str:
    """Base legible del supuesto: la fórmula registrada SIN identificadores
    técnicos internos (clase del cálculo, nº de registro), y la marca
    explícita «sin base documentada externa» cuando el supuesto es política
    del modelo (distinto de «no existe el parámetro»: el valor sí existe)."""
    basis = str((entry or {}).get("basis") or "").strip()
    basis = _METRIC_RECORD_RE.sub("", basis)
    basis = _DEFINITION_SUFFIX_RE.sub("", basis).strip()
    if (entry or {}).get("source_type") == "model_policy":
        suffix = "política del modelo, sin base documentada externa"
        return f"{basis} ({suffix})" if basis else suffix
    return basis or "política del motor"


def _visible_medio(source: str) -> str:
    """Nombre del medio sin forma de localizador, solo para el prompt.

    Representación legible y reversible: se retira el esquema y el
    prefijo "www." y cada punto se separa con un espacio, conservando
    TODOS los componentes del nombre en orden (sin inferir marca ni
    recortar sufijos): "waterford-news.ie" -> "waterford-news ie",
    "finance.yahoo.com" -> "finance yahoo com". La prohibición de
    host/URL en prosa se mantiene absoluta y la fuente real no cambia:
    las citas del resultado las inserta el código desde fact["fuente"].
    """
    visible = source.strip()
    visible = re.sub(r"^[a-z][a-z0-9+.-]*://", "", visible, flags=re.IGNORECASE)
    visible = re.sub(r"^www\.", "", visible, flags=re.IGNORECASE)
    return visible.replace(".", " ")


def fact_pack(
    company: Company,
    valuation: dict,
    long_term_model: dict,
    hypothesis: str | None,
    news_items: list[dict],
    filing_items: list[dict] | None = None,
    rag_context: list[dict] | None = None,
    financial_facts: list[FinancialFact] | None = None,
    fact_locators: dict[int, str] | None = None,
    ownership_facts: list[tuple[str, str]] | None = None,
) -> list[dict]:
    """Paquete deterministico de hechos citables: la unica materia del modelo.

    Cada entrada es {"id", "texto", "fuente"}; el texto lleva la cifra con su
    campo, unidad y periodo, y la fuente es un localizador verificable. El RAG
    aporta SOLO titulo + localizador: su prosa nunca entra en el prompt.
    """
    facts: list[dict] = []

    def add(texto: str, fuente: str) -> None:
        facts.append({"id": _fact_id(len(facts) + 1), "texto": texto, "fuente": fuente})

    currency = company.currency or "USD"
    status = valuation.get("status")
    price = valuation.get("current_price")
    base = valuation.get("base_value")
    mos = valuation.get("margin_of_safety")
    internal = "Motor de valoración interno (sección 13 del memo)."
    # Referencia honesta del precio: con fecha de cierre si el paquete la
    # trae; sin ella no se afirma actualidad («precio actual» sería falso).
    raw_as_of = str(((long_term_model or {}).get("trace") or {}).get("market_as_of") or "")[:10]
    # Solo una fecha ISO valida referencia el cierre; una malformada equivale
    # a ausente (nunca se inventa ni se asume el dia de hoy).
    try:
        _parsed_as_of = datetime.fromisoformat(raw_as_of).date() if raw_as_of else None
    except ValueError:
        _parsed_as_of = None
    if _parsed_as_of is not None:
        price_ref = (
            f"último precio registrado de {company.ticker} al {date_es(raw_as_of)}"
        )
    else:
        price_ref = (
            f"último precio registrado de {company.ticker} "
            "(fecha de cierre no disponible en este paquete)"
        )

    if status:
        add(
            f"Estado de la valoración de {company.ticker}: {status} "
            "(provisional-explicativa; no es un veredicto publicable).",
            internal,
        )
    if price is not None:
        add(f"{price_ref[0].upper() + price_ref[1:]}: {price:.2f} {currency}.", internal)
    if base is not None:
        add(f"Escenario base del modelo: {base:.2f} {currency} por acción.", internal)
    bear = valuation.get("bear_value")
    bull = valuation.get("bull_value")
    expected = valuation.get("expected_value")
    if bear is not None:
        add(f"Escenario pesimista (bear): {bear:.2f} {currency} por acción.", internal)
    if bull is not None:
        add(f"Escenario optimista (bull): {bull:.2f} {currency} por acción.", internal)
    if expected is not None:
        add(f"Valor esperado del modelo: {expected:.2f} {currency} por acción.", internal)
    if mos is not None and price is not None and base is not None and base > 0:
        ref_label, ref_value = margin_of_safety_reference(valuation) or ("escenario base", base)
        add(
            f"Margen de seguridad: {percent_es(mos)} "
            f"({ref_label} de {ref_value:.2f} {currency} frente al precio).",
            internal,
        )
    growth = (valuation.get("reverse_dcf") or {}).get("required_revenue_growth")
    if growth is not None:
        add(
            "Con los supuestos de este DCF inverso, ese precio registrado exigiría "
            f"un crecimiento de ingresos del {percent_es(growth)} anual.",
            internal,
        )
    missing = list(valuation.get("missing_inputs") or [])
    if missing:
        add(
            "Inputs de valoración ausentes: " + ", ".join(missing) + ".",
            "Sección 21 del memo (datos pendientes).",
        )
    framework = (long_term_model or {}).get("framework") or {}
    if framework.get("label"):
        add(
            f"Marco de análisis de la empresa: {framework.get('label')}. "
            f"Pregunta primaria: {framework.get('primary_question')}.",
            "Clasificador interno de marcos (company_framework).",
        )
    mandatory_missing = list((long_term_model or {}).get("missing_mandatory_drivers") or [])
    if mandatory_missing:
        # Etiquetas en español (nunca la clave interna, que el LLM repetiría
        # tal cual) y aclaración de que no bloquean la valoración.
        labels = [
            _DRIVER_LABELS_ES.get(key) or framework_term_es(key) or key.replace("_", " ")
            for key in mandatory_missing
        ]
        add(
            "Datos operativos del marco sin dato (no figuran en el XBRL; no bloquean "
            "la valoración, que proyecta con el crecimiento histórico): "
            + ", ".join(labels)
            + ".",
            "Motor fundamental de largo plazo.",
        )

    # Fundamentales reportados (snapshot): existen en el punto de llamada y
    # sin ellos la narrativa declara huecos FALSOS (medido 2026-10-26: la
    # tesis dijo "no se detallan flujos, tasa, terminal" existiendo).
    present = [
        fact
        for metric in _FUNDAMENTAL_LABELS
        for fact in (financial_facts or [])
        if fact.metric == metric
    ]
    if present:
        add(
            "Bloque de fundamentales: cada cifra declara su métrica, unidad, "
            "periodo y si es dato reportado o cifra derivada; cifras de "
            "periodos distintos NO son comparables entre sí.",
            "Registro interno de datos financieros.",
        )
        for fact in present:
            label = _FUNDAMENTAL_LABELS[fact.metric]
            if fact.metric in {"fcf_margin", "revenue_growth"} and fact.unit in {
                "decimal",
                "ratio",
            }:
                valor = percent_es(float(fact.value))
            else:
                compact = format_compact_es(fact.value) or str(fact.value)
                valor = (
                    f"{compact} {fact.unit}"
                    if fact.unit and len(fact.unit) == 3 and fact.unit.isupper()
                    else compact
                )
            reported = getattr(fact, "is_reported", None)
            if reported is True:
                # Reportado != contenido verificado: la fuente acredita
                # publicacion/registro, nunca veracidad.
                origen = (
                    f"dato reportado (fuente {fact.source_type}; "
                    "la fuente acredita publicación, no veracidad)"
                )
            elif reported is False:
                # Derivada por ingesta de partidas reportadas: no es un dato
                # reportado y no se presenta con la misma etiqueta de fuente.
                origen = (
                    f"cifra derivada de partidas {fact.source_type}; "
                    "no es un dato reportado"
                )
            else:
                # Estado desconocido: no se convierte ni en reportado ni en
                # derivado.
                origen = (
                    f"estado de reporte no disponible "
                    f"(fuente registrada: {fact.source_type})"
                )
            add(
                f"{label} de {company.ticker}: {valor} "
                f"(periodo {fact.period}; {origen}).",
                _fact_source_locator(fact),
            )



    # Supuestos del motor (bloque "assumptions" del modelo fundamental): NO
    # son datos realizados ni fuentes externas; el texto lo dice explícito.
    # Forma real verificada contra el objeto persistido (2026-10-26):
    # long_term_model["assumptions"][key] = {value, unit, source_type, basis,
    # source_fact_ids, confidence}; horizon_years y as_of_period al mismo nivel.
    assumptions = (long_term_model or {}).get("assumptions") or {}
    if assumptions:
        parts = []
        if (assumptions.get("revenue_growth") or {}).get("value") is not None:
            parts.append(
                "crecimiento de ingresos del "
                + percent_es(assumptions["revenue_growth"]["value"])
                + " anual (base: "
                + _assumption_basis_text(assumptions["revenue_growth"])
                + ")"
            )
        if (assumptions.get("fcf_margin") or {}).get("value") is not None:
            parts.append(
                "margen FCF del "
                + percent_es(assumptions["fcf_margin"]["value"])
                + " (base: "
                + _assumption_basis_text(assumptions["fcf_margin"])
                + "; otra base y otro periodo que el margen FCF registrado de "
                "un año concreto: no son la misma cifra)"
            )
        if (assumptions.get("wacc") or {}).get("value") is not None:
            parts.append(
                "tasa de descuento (WACC) del "
                + percent_es(assumptions["wacc"]["value"])
                + " (base: "
                + _assumption_basis_text(assumptions["wacc"])
                + ")"
            )
        if (assumptions.get("terminal_growth") or {}).get("value") is not None:
            parts.append(
                "crecimiento terminal del "
                + percent_es(assumptions["terminal_growth"]["value"])
                + " ("
                + _assumption_basis_text(assumptions["terminal_growth"])
                + ")"
            )
        horizon = (long_term_model or {}).get("horizon_years")
        if horizon:
            parts.append(f"horizonte de proyección de {int(horizon)} años")
        as_of = (long_term_model or {}).get("as_of_period")
        if as_of:
            parts.append(f"datos de corte {as_of}")
        if parts:
            add(
                "Supuestos del motor de valoración (supuestos del modelo, no "
                "datos realizados ni fuentes externas): " + ", ".join(parts) + ".",
                "Motor fundamental de largo plazo.",
            )
        # URLs reales de los supuestos (wacc/terminal) van SOLO al localizador
        # (cita del código): nunca al texto que ve el modelo.
        for key in ("wacc", "terminal_growth"):
            urls = (assumptions.get(key) or {}).get("source_urls") or []
            if urls:
                add(
                    f"El motor registró una fuente externa para el supuesto "
                    f"«{key}»; su registro no implica verificación de su contenido.",
                    urls[0],
                )

    # Reverse DCF: valor resuelto y estado (supuestos del motor). Forma real:
    # {required_revenue_growth, market_price, solved_value_per_share,
    # out_of_bounds, status, trace} — sin fcf_margin a primer nivel.
    reverse = valuation.get("reverse_dcf") or {}
    solved = reverse.get("solved_value_per_share")
    if solved is not None:
        add(
            f"A ese precio registrado, el DCF inverso resuelve un valor de {solved:.2f} "
            f"{currency} por acción (salida del motor con sus supuestos).",
            internal,
        )
    if reverse.get("out_of_bounds"):
        add(
            "El DCF inverso quedó fuera de rango con los supuestos actuales: "
            "el crecimiento exigido no es resoluble dentro de los límites del motor.",
            internal,
        )

    # Drivers del marco CON dato (los sin dato ya se declaran como huecos).
    sourced = [
        driver
        for driver in (long_term_model or {}).get("driver_model") or []
        if driver.get("status") == "sourced" and driver.get("value") is not None
    ][:4]
    for driver in sourced:
        label = _DRIVER_LABELS_ES.get(driver.get("key") or "", f'driver "{driver.get("key")}"')
        ids = driver.get("source_fact_ids") or []
        locator = (fact_locators or {}).get(ids[0]) if ids else None
        valor = format_compact_es(driver["value"]) or str(driver["value"])
        unit = driver.get("unit") or ""
        period = driver.get("period") or "periodo no disponible"
        add(
            f"Driver del marco con dato registrado — {label}: {valor}"
            + (f" {unit}" if unit and unit != "unknown" else "")
            + f" (periodo {period}).",
            locator or "Registro interno de datos financieros.",
        )
    if hypothesis:
        add(
            f"Hipótesis de trabajo registrada (interpretación, no hecho): {hypothesis}",
            "Registro interno de la tesis.",
        )
    for item in list(news_items or [])[:5]:
        headline = str(item.get("source_headline") or "").strip()
        source = _visible_medio(str(item.get("source") or "").strip())
        if not headline or not source:
            continue
        day = date_es(str(item.get("date") or "")[:10])
        date_source = item.get("date_source")
        if day and date_source == "source":
            texto = f'{source} publicó el {day} "{clip_words(headline, 160)}".'
        elif day and date_source == "gdelt_first_seen":
            texto = f'{source} publicó "{clip_words(headline, 160)}", visto en GDELT el {day}.'
        elif day:
            texto = f'{source} publicó "{clip_words(headline, 160)}" (fecha de ingesta: {day}).'
        else:
            texto = f'{source} publicó "{clip_words(headline, 160)}".'
        add(texto, _source_locator(item))
    # Conexion 10b: resumen de insiders (Form 4) y fondos 13F ya persistidos,
    # con cifras deterministas y su fuente SEC (texto propio, no de terceros).
    for texto, fuente in list(ownership_facts or [])[:2]:
        add(texto, fuente)
    for item in list(filing_items or [])[:3]:
        add(
            f"Filing {item.get('form') or 'formulario no disponible'}, "
            f"fecha {item.get('filing_date') or 'no disponible'}. "
            "Su disponibilidad no implica verificación de su contenido.",
            _source_locator(item),
        )
    for item in list(rag_context or [])[:5]:
        # Solo titulo + localizador: el texto del chunk NO entra en el prompt,
        # para que el modelo no pueda volcar prosa de terceros como analisis.
        title = str(item.get("title") or "Sin título").strip()
        if item.get("type") == "knowledge_chunk":
            locator = f"Biblioteca {item.get('knowledge_document_id')}"
            texto = f"Documento de doctrina de inversión disponible: «{title}» (no es un dato financiero de esta empresa)."
        else:
            locator = f"Documento {item.get('document_id')}"
            texto = f"Documento disponible: «{title}» (contenido no verificado)."
        url_locator = _source_locator(item)
        add(texto, url_locator if url_locator != "URL no disponible" else locator)
    return facts



def _validate_sections(
    parsed, facts: list[dict]
) -> tuple[list[dict] | None, str | None]:
    """Fail-closed: (secciones con citas del codigo, None) o (None, regla).

    La regla devuelta es un codigo corto sin contenido del modelo ni del
    paquete de hechos: sirve para log y para la nota de reintento.
    """
    if not isinstance(parsed, dict):
        return None, "sin_secciones"
    raw = parsed.get("secciones")
    if not isinstance(raw, list) or not raw:
        return None, "sin_secciones"
    fact_ids = {fact["id"] for fact in facts}
    allowed, ambiguas = _allowed_numbers(facts)
    seen: set[str] = set()
    validated: list[dict] = []
    total_chars = 0
    for item in raw:
        if not isinstance(item, dict):
            return None, "seccion_invalida"
        sid = item.get("id")
        titulo = item.get("titulo")
        parrafos = item.get("parrafos")
        cited = item.get("fact_ids")
        if sid not in SECTION_IDS or sid in seen:
            return None, "seccion_invalida"
        seen.add(sid)
        if not isinstance(titulo, str) or not titulo.strip() or len(titulo) > 120:
            return None, "seccion_invalida"
        if not isinstance(parrafos, list) or not 1 <= len(parrafos) <= 6:
            return None, "seccion_invalida"
        if not isinstance(cited, list) or not cited or any(c not in fact_ids for c in cited):
            return None, "fact_ids_invalidos"
        clean: list[str] = []
        for parrafo in parrafos:
            if not isinstance(parrafo, str):
                return None, "parrafo_invalido"
            original = parrafo.strip()
            # URL y veredicto sobre el ORIGINAL: la normalizacion de markup
            # nunca puede esconder un enlace ni un veredicto.
            if _URL_RE.search(original):
                return None, "url_detectada"
            if _VERDICT_RE.search(original):
                return None, "lenguaje_veredicto"
            text = _strip_markup(original)
            if not 40 <= len(text) <= 2000:
                return None, "parrafo_invalido"
            if _MARKUP_RE.search(text):
                return None, "markup_detectado"
            for match in _NUMBER_RE.findall(text):
                surface = _surface_key(match)
                if surface and _AMBIGUOUS_SURFACE_RE.match(surface):
                    # Superficie ambigua: solo ancla su copia literal en el
                    # pack; jamás por equivalencia canónica cruzada.
                    if surface not in ambiguas:
                        return None, "cifra_no_anclada"
                    continue
                norm = _norm_number(match)
                if norm is None or norm not in allowed:
                    # Cifra no anclada al paquete: posible alucinacion.
                    return None, "cifra_no_anclada"
            clean.append(text)
            total_chars += len(text)
        validated.append({"id": sid, "titulo": titulo.strip(), "parrafos": clean, "fact_ids": cited})
    if not _MANDATORY_IDS.issubset(seen):
        return None, "obligatorias_ausentes"
    ids_order = [s["id"] for s in validated]
    if ids_order[0] != "que_sabemos" or ids_order[-1] != "lo_que_no_sabemos":
        return None, "orden_indebido"
    # Narrativa extensa de verdad: un selector de plantillas no llega a esto.
    if not 800 <= total_chars <= 20000:
        return None, "longitud_total"
    # Al menos 3 hechos distintos citados en total: explicacion anclada, no prosa libre.
    cited_all = {c for s in validated for c in s["fact_ids"]}
    if len(cited_all) < 3:
        return None, "anclaje_insuficiente"
    # Las citas las pone el codigo (localizadores verificables), nunca el modelo.
    locators = {fact["id"]: fact["fuente"] for fact in facts}
    for section in validated:
        seen_locators = list(dict.fromkeys(locators[c] for c in section["fact_ids"]))
        section["parrafos"].append("Fuentes citadas: " + " · ".join(seen_locators[:6]))
        del section["id"]
        del section["fact_ids"]
    return [*validated, dict(_DISCLAIMER_SECTION)], None


_PROMPT = get_prompt("thesis_deep_narrative", allow_remote=False)
_SYSTEM = _PROMPT.text


def _prompt():
    """i18n B: resuelve el prompt en el idioma activo de la peticion.

    La constante de modulo queda en espanol (los tests la fijan); cada
    llamada pasa por ``get_prompt`` para heredar el idioma del scope.
    """
    return get_prompt("thesis_deep_narrative", allow_remote=False)



def _build_request(facts: list[dict], extra_note: str | None = None) -> LLMRequest:
    visible = [
        {"id": fact["id"], "texto": fact["texto"], "fuente": _visible_fuente(fact["fuente"])}
        for fact in facts
    ]
    user: dict = {"hechos": visible}
    if extra_note:
        user["nota"] = extra_note
    return LLMRequest(
        messages=[
            Message("system", _prompt().text),
            Message("user", json.dumps(user, ensure_ascii=False)),
        ],
        task="deep_thesis",
        temperature=0.2,
        # Con 4000 el razonamiento agotaba el tope (por eso iba en "none").
        # Medido 2026-10-27 con el modelo real: low usa 2-5,6k tokens de
        # salida (razonamiento incluido), high hasta 12,8k. 16000 deja sitio.
        max_tokens=16000,
        # Esfuerzo de la tabla por seccion (tesis_profunda); un valor
        # explicito en THESIS_DEEP_NARRATIVE_REASONING_EFFORT sigue ganando.
        reasoning_effort=_effort("tesis_profunda", get_settings().thesis_deep_narrative_reasoning_effort),
        response_format=ResponseFormat.json_schema(
            _OUTPUT_SCHEMA, name="thesis_deep_narrative"
        ),
        metadata=_prompt().trace_metadata(),
    )


def _resolve_fact_locators(db: Session, long_term_model: dict) -> dict[int, str]:
    """fact_id -> URL real del documento fuente (o etiqueta interna).

    Un id de financial_fact NO sustituye la URL recuperada del registro.
    """
    ids: list[int] = []
    for driver in (long_term_model or {}).get("driver_model") or []:
        ids.extend(driver.get("source_fact_ids") or [])
    if not ids:
        return {}
    locators: dict[int, str] = {}
    try:
        for fact in db.query(FinancialFact).filter(FinancialFact.id.in_(ids)).all():
            url = None
            if fact.source_id is not None:
                document = db.get(Document, fact.source_id)
                url = document.source_url if document is not None else None
            locators[fact.id] = url or f"Registro interno de datos financieros ({fact.source_type})."
    except Exception:  # noqa: BLE001 - sin localizador real, etiqueta interna
        return {}
    return locators


def maybe_deep_narrative(
    db: Session,
    company: Company,
    valuation: dict,
    long_term_model: dict,
    hypothesis: str | None,
    news_items: list[dict] | None,
    *,
    provider=None,
    filing_items: list[dict] | None = None,
    rag_context: list[dict] | None = None,
    financial_facts: list[FinancialFact] | None = None,
    ownership_facts: list[tuple[str, str]] | None = None,
) -> dict | None:
    """Narrativa extensa redactada por el modelo configurado, o None.

    Devuelve {"sections", "model", "provider"}: el modelo ejecutado queda en
    la traza para verificar que la tesis uso el modelo Go configurado y no un
    fallback. Fail-closed en todo: flag "0", proveedor ausente, presupuesto
    agotado, error de red, JSON invalido o validacion fallida devuelven None y
    la tesis conserva solo la narrativa determinista/de noticias.
    """
    # Activada por defecto (decision del dueno: narrativa real, no selector de
    # plantillas); THESIS_DEEP_NARRATIVE_LLM_ENABLED=0 la apaga sin desplegar.
    if os.getenv("THESIS_DEEP_NARRATIVE_LLM_ENABLED") == "0":
        return None
    facts = fact_pack(
        company, valuation, long_term_model, hypothesis,
        list(news_items or []), filing_items, rag_context,
        financial_facts=financial_facts,
        fact_locators=_resolve_fact_locators(db, long_term_model),
        ownership_facts=ownership_facts,
    )
    if len(facts) < 3:
        # Sin minimo de hechos anclados no hay explicacion honesta que redactar.
        return None
    try:
        provider = provider or create_thesis_narrative_provider()
        budget = BudgetController()
    except Exception:  # noqa: BLE001 - config rota: sin narrativa extensa
        return None
    if provider.name == "disabled":
        return None
    try:
        # Una llamada de hasta 4000 tokens de salida; margen conservador.
        if not budget.can_spend(db, 0.15):
            return None
    except Exception:  # noqa: BLE001 - sin contexto de tenant, falla cerrado
        return None

    def _record(response) -> None:
        try:
            budget.record(
                db,
                response.model,
                "thesis_deep_narrative",
                budget.estimate_cost_eur(
                    response.model,
                    response.usage.input_tokens,
                    response.usage.output_tokens,
                ),
                response.usage.total_tokens,
                commit=False,
            )
            # SessionLocal tiene autoflush=False: sin flush, el can_spend de la
            # siguiente llamada LLM del mismo generate no veria este consumo.
            db.flush()
        except Exception:  # noqa: BLE001 - el registro contable no decide el contenido
            logger.warning("budget_record_failed: el gasto LLM de esta narrativa no quedo contabilizado", exc_info=True)

    response = None
    last_reason: str | None = None
    for attempt in range(2):
        note = None
        if attempt == 1:
            specific = _RETRY_NOTES.get(last_reason or "")
            note = (
                "Tu respuesta anterior fue rechazada por validación. "
                + (specific + " " if specific else "")
                + "Responde solo con hechos del paquete."
            )
        request = _build_request(facts, note)
        try:
            response = run_from_any_context(provider.complete(request))
        except Exception as exc:  # noqa: BLE001 - el fallo del proveedor no degrada la tesis
            logger.warning(
                "narrativa extensa: fallo del proveedor (%s), sin narrativa",
                type(exc).__name__,
            )
            return None
        _record(response)
        if getattr(response, "degraded", False):
            # Respuesta degradada del proveedor (warning, truncado, filtro):
            # no se publica como narrativa de tesis; un reintento y fuera.
            last_reason = "respuesta_degradada"
            logger.warning(
                "narrativa extensa: rechazada (%s) intento %s modelo=%s fallbacks=%s",
                last_reason,
                attempt + 1,
                response.model,
                list(getattr(response, "fallback_trail", ()) or ()),
            )
            continue
        try:
            parsed = parse_json_response(response.text)
        except Exception:  # noqa: BLE001 - JSON invalido: un reintento y fuera
            last_reason = "json_no_parseable"
            logger.warning(
                "narrativa extensa: rechazada (%s) intento %s modelo=%s fallbacks=%s",
                last_reason,
                attempt + 1,
                response.model,
                list(getattr(response, "fallback_trail", ()) or ()),
            )
            continue
        sections, reason = _validate_sections(parsed, facts)
        if sections is None:
            last_reason = reason
            logger.warning(
                "narrativa extensa: rechazada (%s) intento %s modelo=%s fallbacks=%s",
                reason,
                attempt + 1,
                response.model,
                list(getattr(response, "fallback_trail", ()) or ()),
            )
            continue
        requested_model = None
        try:
            requested_model = provider.model_router.resolve(request)
        except Exception:  # noqa: BLE001 - la traza nunca rompe la narrativa
            requested_model = None
        # Traza honesta: modelo PEDIDO por la ruta vs modelo EJECUTADO real
        # (si el adaptador cayo a su fallback, response.model lo delata) y
        # cadena de fallos previos. Nunca se declara Go si ejecuto otro.
        return {
            "sections": sections,
            "model": response.model,
            "requested_model": requested_model,
            "fallback_trail": list(getattr(response, "fallback_trail", ()) or ()),
            "provider": getattr(response, "provider", None) or getattr(provider, "name", "unknown"),
        }
    return None


def is_sin_datos(sections) -> bool:
    """True si las secciones son el marcador «Sin datos» de la capa de noticias."""
    return (
        isinstance(sections, list)
        and len(sections) == 1
        and isinstance(sections[0], dict)
        and sections[0].get("parrafos") == ["Sin datos"]
    )
