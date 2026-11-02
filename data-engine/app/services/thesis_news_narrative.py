"""Narrativa libre INFERIDA desde noticias persistidas, bajo demanda y a EUR 0.

No valida que una inferencia sea cierta: exige atribucion a noticias recibidas,
idioma limpio y ausencia total de cifras/enlaces en la prosa del modelo. Un fallo deja "Sin datos".
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.llm import LLMRequest, Message, ResponseFormat, parse_json_response
from app.llm.errors import ProviderDisabledError, ProviderHTTPError, ProviderTransportError
from app.llm.thesis_go import create_thesis_narrative_provider
from app.models.entities import Company, NewsEvent
from app.services.async_bridge import run_from_any_context
from app.services.budget import BudgetController
from app.services.llm_output_guard import complete_guarded, inspect_text
from app.services.llm_proposal_runner import paid_model_risk
from app.services.llm_proposal_service import _TransientRetryProvider
from app.services.prompt_registry import get_prompt
from app.services.thesis_narrative_common import narrative_reasoning_effort as _effort

logger = logging.getLogger(__name__)
NETWORK_TIMEOUT_SECONDS = 60
SECTION_TITLES = {
    "cambio": "Lo que cambió",
    "implicaciones": "Qué puede implicar para la tesis",
    "riesgos": "Qué falta confirmar",
}
# Sin cifras en prosa: los hechos cuantitativos los copia exclusivamente el código.
_WORD_NUMBER = re.compile(
    r"\b(?:cero|un[oa]?|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez|once|doce|"
    r"trece|catorce|quince|dieci\w+|veinti\w+|veinte|treinta|cuarenta|cincuenta|"
    r"sesenta|setenta|ochenta|noventa|cien|ciento|\w+cient[oa]s|mil|millar(?:es)?|millones?|billones?|"
    r"trillones?|mitad|doble|triple|cuádruple|cuatrocient[oa]s?|quinient[oa]s?|"
    r"seiscient[oa]s?|setecient[oa]s?|ochocient[oa]s?|novecient[oa]s?|por ciento|"
    r"primero|segundo|tercero|tercer|cuarto|quinto|sexto|séptimo|octavo|noveno|décimo|"
    r"centésimo|mitades|tercios|cuartos|cientos|miles|decenas?|docenas?|"
    r"centenas?|centenares|centenar|millares|billón|millón|trillón)\b", re.IGNORECASE,
)
# «un tercero» como sustantivo (un tercero ajeno), sin complemento partitivo,
# no expresa cantidad. «un tercero de los ingresos» (partitivo), «el tercero»
# o «del segundo al tercero» (orden) siguen rechazándose.
_TERCERO_NOMINAL_RE = re.compile(r"\bun\s+(tercero)\b(?!\s+de[l]?\b)", re.IGNORECASE)
_URL = re.compile(
    r"(?:[a-z][a-z0-9+.-]*://|www\.)[^\s<>\"'\[\]()]+|"
    r"\b(?:[a-z0-9-]+\.)+[a-z]{2,}(?:/[^\s<>\"'\[\]()]*)?", re.IGNORECASE,
)
_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": list(SECTION_TITLES),
    "properties": {
        key: {
            "type": "object", "additionalProperties": False,
            "required": ["texto", "evidence_ids"],
            "properties": {
                "texto": {"type": "string"},
                "evidence_ids": {"type": "array", "minItems": 1, "items": {"type": "string"}},
            },
        } for key in SECTION_TITLES
    },
}
_PROMPT = get_prompt("thesis_news_narrative", allow_remote=False)
_SYSTEM = _PROMPT.text


def _prompt():
    """i18n B: resuelve el prompt en el idioma activo de la peticion.

    La constante de modulo queda en espanol (los tests la fijan); cada
    llamada pasa por ``get_prompt`` para heredar el idioma del scope.
    """
    return get_prompt("thesis_news_narrative", allow_remote=False)



_AGGREGATOR_HOSTS = ("news.google.com", "google.com")


def _canonical_url(url: str | None) -> str | None:
    """URL de la fuente; un redirect de Google News no es la fuente: N/D."""
    if not url:
        return None
    host = (urlsplit(url).hostname or "").lower()
    if host in _AGGREGATOR_HOSTS or host.endswith(".google.com"):
        return None
    return url


def sin_datos() -> list[dict]:
    return [{"titulo": "Análisis narrativo", "parrafos": ["Sin datos"]}]


_RAZONES_COMPENDIO = {
    "flag": "la narrativa con modelo está apagada por configuración",
    "provider": "el proveedor de modelo no está disponible (desactivado, sin clave o modelo no gratuito)",
    "budget": "no hay presupuesto de modelo disponible",
    "error": "el modelo de lenguaje no está disponible ahora mismo: error del proveedor o respuesta rechazada",
}


def compendio_factual(items: list[dict], now: datetime, razon: str | None = None) -> list[dict]:
    """Enumeración factual de la evidencia reciente cuando la narrativa LLM
    está apagada por configuración (THESIS_NARRATIVE_LLM_ENABLED != "1").
    NO es análisis: lista titulares reales con fecha, medio y enlace, y lo
    dice. Nunca sustituye a la narrativa LLM ni se presenta como tal.
    """
    headlines = news_context(list(items or []), now)
    if not headlines:
        return sin_datos()
    parrafos = [
        "Compendio factual de evidencia reciente: enumeración de titulares "
        "con fecha y fuente, sin análisis ("
        + _RAZONES_COMPENDIO.get(razon or "", "el modelo de lenguaje no está disponible en esta generación")
        + "). No es una interpretación.",
    ]
    for row in headlines:
        fecha = str(row.get("fecha") or "")[:10] or "fecha no disponible"
        linea = f"- {row['titulo']} ({row['medio']}, {fecha}"
        if row.get("origen_fecha") and row["origen_fecha"] != "no verificado":
            linea += f", fecha: {row['origen_fecha']}"
        linea += ")"
        if row.get("url"):
            linea += f" {row['url']}"
        parrafos.append(linea)
    return [{"titulo": "Compendio factual de evidencia (sin análisis automático)", "parrafos": parrafos}]


def news_context(items: list[dict], now: datetime) -> list[dict]:
    """Copias acotadas del pipeline NewsEvent; sin noticias futuras/obsoletas."""
    now = now.replace(tzinfo=UTC) if now.tzinfo is None else now.astimezone(UTC)
    rows = []
    seen = set()
    for item in items:
        if not isinstance(item, dict) or item.get("id") is None:
            continue
        try:
            at = datetime.fromisoformat(str(item.get("date")))
            at = at.replace(tzinfo=UTC) if at.tzinfo is None else at.astimezone(UTC)
        except (TypeError, ValueError):
            continue
        if not timedelta(0) <= now - at <= timedelta(days=14):
            continue
        original = item.get("source_headline")
        title = original or item.get("title")
        if not isinstance(title, str) or not title.strip():
            continue
        identifier = f"news:{item['id']}"
        if identifier in seen:
            continue
        seen.add(identifier)
        url = item.get("url")
        try:
            parsed = urlsplit(url) if isinstance(url, str) else None
            if not parsed or parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
                url = None
        except ValueError:
            url = None
        rows.append({
            "id": identifier, "titulo": title.strip()[:500],
            "tipo": "titular original" if original else "resumen del pipeline, no cita literal",
            "medio": str(item.get("source") or "Medio no disponible")[:120],
            "fecha": at.isoformat(), "origen_fecha": item.get("date_source") or "no verificado",
            "url": url, "pendiente_actualizacion": bool(item.get("requires_update")),
        })
    return sorted(rows, key=lambda row: row["fecha"], reverse=True)[:8]


def build_request(ticker: str, headlines: list[dict]) -> LLMRequest:
    return LLMRequest(
        messages=[Message("system", _prompt().text), Message("user", json.dumps(
            {"ticker": ticker, "noticias": headlines}, ensure_ascii=False,
        ))],
        # Con 1600 el razonamiento agotaba el tope (finish=length): 6000 deja
        # sitio al razonamiento de la tabla por seccion (tesis_noticias).
        task="main_financial_analysis", temperature=0.2, max_tokens=6000,
        reasoning_effort=_effort("tesis_noticias", get_settings().thesis_news_narrative_reasoning_effort),
        response_format=ResponseFormat.json_schema(_SCHEMA, name="thesis_news_narrative"),
        metadata=_prompt().trace_metadata(),
    )


def validate_output(raw: dict, headlines: list[dict]) -> list[dict]:
    """Rechaza cifras/URLs en TODA prosa del modelo, incluso las recibidas.

    No basta pertenencia literal: reasignar una cifra a otra métrica es inventar
    un hecho. Por eso solo el código copia titulares completos como evidencia.
    """
    if not isinstance(raw, dict) or set(raw) != set(SECTION_TITLES):
        raise ValueError("estructura_invalida")
    by_id = {h["id"]: h for h in headlines}
    sections = []
    for key, title in SECTION_TITLES.items():
        entry = raw[key]
        if not isinstance(entry, dict) or set(entry) != {"texto", "evidence_ids"}:
            raise ValueError("seccion_invalida")
        text, ids = entry["texto"], entry["evidence_ids"]
        if not isinstance(text, str) or not 40 <= len(text.strip()) <= 2400 or inspect_text(text):
            raise ValueError("texto_invalido")
        if any(char in text for char in "<>[]`\\"):
            raise ValueError("formato_invalido")
        if not isinstance(ids, list) or not ids or any(not isinstance(i, str) or i not in by_id for i in ids):
            raise ValueError("evidencia_no_recibida")
        if len(ids) != len(set(ids)):
            raise ValueError("evidencia_duplicada")
        cited = [by_id[i] for i in ids]
        # No bag-of-numbers ni excepción para URLs. Incluso la cifra literal
        # recibida puede reasignarse a otra métrica: fallo cerrado antes de citar.
        if any(char.isnumeric() for char in text) or any(char in text for char in "%‰"):
            raise ValueError("cifra_en_prosa_llm")
        if _URL.search(text):
            raise ValueError("url_en_prosa_llm")
        # Artículos 'un/una/uno' no expresan por sí solos una cifra. El resto
        # de cantidades reconocibles se rechaza aunque exista en el titular.
        nominal_spans = [m.span(1) for m in _TERCERO_NOMINAL_RE.finditer(text)]
        quantities = set()
        for match in _WORD_NUMBER.finditer(text):
            word = match.group(0).lower()
            if word in {"un", "una", "uno"}:
                continue
            if word == "tercero" and any(match.span() == span for span in nominal_spans):
                continue
            quantities.add(word)
        if quantities:
            raise ValueError("cantidad_en_prosa_llm")
        citations = [
            f"Evidencia {n}: {h['titulo']}. Medio: {h['medio']}. "
            f"Fecha registrada: {h['fecha']} ({h['origen_fecha']}). "
            f"Fuente: {_canonical_url(h['url']) or 'N/D (enlace original no disponible)'}."
            for n, h in enumerate(cited, start=1)
        ]
        sections.append({"titulo": title, "parrafos": [text.strip(), *citations]})
    sections.append({"titulo": "Alcance", "parrafos": [
        "Inferencia a partir de noticias, no recomendación de inversión. "
        "Los titulares acreditan publicación, no veracidad; las fechas registradas pueden ser de ingesta."
    ]})
    return sections


def maybe_news_narrative_sections(db, company, news_items, *, provider=None, now=None) -> list[dict]:
    """Invocado solo al generar una versión de tesis. Sin scheduler ni modelo de pago."""
    if os.getenv("THESIS_NARRATIVE_LLM_ENABLED") != "1":
        return compendio_factual(news_items, now or datetime.now(UTC), "flag")
    try:
        # Nunca finaliza ni mueve la transacción del llamador: lectura y
        # presupuesto usan sesiones cortas propias (otra conexión) y la red solo
        # recibe escalares. Si el llamador ya tiene transacción abierta, su
        # conexión queda retenida (sin tocar) durante la llamada, acotada a
        # NETWORK_TIMEOUT_SECONDS.
        headlines = news_context(list(news_items or []), now or datetime.now(UTC))
        if not headlines:
            return sin_datos()
        request = build_request(company.ticker, headlines)
        provider = provider or create_thesis_narrative_provider()
        if provider.name == "disabled" or paid_model_risk(provider, request=request):
            # Modelo no disponible NO es ausencia de evidencia: compendio
            # factual (fuentes explícitas, sin LLM, EUR 0) en vez de «Sin datos».
            return compendio_factual(list(news_items or []), now or datetime.now(UTC), "provider")
        budget = BudgetController()
        responses = []

        def allowed():
            if not isinstance(db, Session):  # dobles de prueba
                return budget.can_spend(db, 0)
            with Session(bind=db.get_bind()) as short:
                short.info.update(db.info)
                return budget.can_spend(short, 0)

        if not allowed():
            return compendio_factual(list(news_items or []), now or datetime.now(UTC), "budget")

        async def complete():
            # Únicamente escalares y proveedor en el puente. Ninguna Session.
            guarded = await complete_guarded(
                _TransientRetryProvider(provider), request,
                source="thesis_news_narrative", on_response=responses.append,
            )
            return validate_output(parse_json_response(guarded.response.text), headlines)

        async def bounded():
            return await asyncio.wait_for(complete(), timeout=NETWORK_TIMEOUT_SECONDS)

        try:
            return run_from_any_context(bounded(), timeout=NETWORK_TIMEOUT_SECONDS + 15)
        finally:
            # Red terminada o cancelada. Contabilidad independiente y breve,
            # sin commits parciales de los datos de tesis.
            for response in responses:
                if isinstance(db, Session):
                    with Session(bind=db.get_bind()) as short:
                        short.info.update(db.info)
                        budget.record(short, response.model, "thesis_news_narrative", 0,
                                      response.usage.total_tokens, commit=False)
                        short.commit()
                else:
                    budget.record(db, response.model, "thesis_news_narrative", 0,
                                  response.usage.total_tokens, commit=False)
                    db.flush()
    except (ProviderHTTPError, ProviderTransportError, ProviderDisabledError) as exc:
        # SOLO indisponibilidad del proveedor (HTTP 429/5xx/401/403, timeout
        # de transporte, proveedor deshabilitado): la evidencia EXISTE y
        # «Sin datos» mentiría. Compendio factual extractivo (sin LLM, EUR 0)
        # que declara la indisponibilidad del análisis automático SIN
        # diagnosticar la causa (el copy nunca afirma cuota/auth: 429 no es
        # el único origen posible y el status es diagnóstico interno, en log).
        # Log con whitelist tipada, JAMAS str(exc) genérico: un mensaje de
        # proveedor podría volcar URL/token/body/contenido de la fuente.
        if isinstance(exc, ProviderHTTPError):
            detalle = f"HTTP {exc.status_code}"
        elif isinstance(exc, ProviderTransportError):
            detalle = f"transport {exc.reason} attempts={exc.attempts}"
        else:
            detalle = "disabled"
        logger.warning("Narrativa de noticias: %s %s; compendio factual",
                       type(exc).__name__, detalle)
        return compendio_factual(list(news_items or []), now or datetime.now(UTC), "error")
    except Exception as exc:  # noqa: BLE001 - upstream inestable nunca rompe la tesis
        # Salida LLM rechazada (cifras inventadas, URLs, JSON inválido,
        # inyección) y cualquier otro fallo: FAIL-CLOSED como antes.
        logger.warning("Narrativa de noticias: %s; Sin datos", type(exc).__name__)
        return sin_datos()


def prepare_news_narrative(db: Session, ticker: str, *, provider=None, now=None) -> list[dict]:
    """Snapshot de escalares antes de abrir el savepoint de generación.

    La transacción del llamador, si existe, no se toca: se lee con una sesión
    corta independiente (solo datos ya persistidos) y se cierra antes de
    presupuesto/LLM.

    Con el flag LLM apagado NO hay llamada ni presupuesto, pero la tesis si
    conserva el compendio factual rotulado (titulares reales con fecha y
    fuente, declarado como enumeracion SIN analisis): «Sin datos» queda
    reservado a cuando tampoco hay evidencia que enumerar. El compendio
    nunca se presenta como narrativa del modelo.
    """
    try:
        with Session(bind=db.get_bind()) as short:
            short.info.update(db.info)
            company = short.scalar(select(Company).where(Company.ticker == ticker.upper()))
            if company is None:
                return sin_datos()
            company_copy = SimpleNamespace(ticker=company.ticker)
            now_utc = now or datetime.now(UTC)
            # Sin fecha en SQL (None) ni futuras: ambas consumirian huecos del
            # limite y news_context las descarta despues. 40 filas de margen
            # (como evidence: MAX_NEWS_ITEMS * 8) para que filas invalidas no
            # dejen el compendio vacio habiendo evidencia valida.
            rows = short.scalars(
                select(NewsEvent)
                .where(NewsEvent.company_id == company.id)
                .where(NewsEvent.date.is_not(None))
                .where(NewsEvent.date <= now_utc)
                .order_by(NewsEvent.date.desc())
                .limit(40)
            ).all()
            # Defensivo como _collect_news: una fila envenenada (fecha None,
            # metadata no dict) nunca tira TODO el snapshot a «Sin datos».
            items = []
            for row in rows:
                try:
                    metadata = row.metadata_ if isinstance(row.metadata_, dict) else {}
                    items.append({
                        "id": row.id, "title": row.title,
                        "date": row.date.isoformat() if row.date else None,
                        "source": row.source, "url": row.url,
                        "source_headline": metadata.get("source_headline"),
                        "date_source": metadata.get("date_source"),
                        "requires_update": row.requires_update})
                except Exception:  # noqa: BLE001 - se salta la fila, no el snapshot
                    continue
        return maybe_news_narrative_sections(db, company_copy, items, provider=provider, now=now)
    except Exception as exc:  # noqa: BLE001 - preflight no bloquea persistencia
        logger.warning("Snapshot de narrativa: %s; Sin datos", type(exc).__name__)
        return sin_datos()
