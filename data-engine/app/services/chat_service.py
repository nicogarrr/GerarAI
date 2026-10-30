import asyncio
import os
import re
from datetime import date
from decimal import Decimal

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.llm.base import LLMProvider
from app.llm.chat_provider import create_chat_llm_provider
from app.llm.errors import ProviderTransportError
from app.llm.interactive_deadline import bounded_chat, remaining_seconds
from app.models import (
    CashBalance,
    Claim,
    Company,
    Document,
    DocumentChunk,
    EvidenceSuggestion,
    FinancialFact,
    MarketPrice,
    NewsEvent,
    Position,
    ResearchSession,
    ThesisSection,
    ThesisVersion,
)
from app.schemas import ChatPageContext, ChatResponse, ChatTurn
from app.services.brain_service import (
    LEADING_GREETING_RE,
    SMALL_TALK_RE,
    ResolvedPageContext,
    resolve_page_context,
    small_talk_answer,
)
from app.services.chat_synthesis_service import ChatSynthesisService
from app.services.claim_scope import latest_thesis_version, live_claims
from app.services.company_resolver import resolve_company
from app.services.library_context import company_library_context, retrieve_library_context
from app.services.memory_service import MemoryService, remember_note
from app.services.portfolio_fx_service import PortfolioFXService
from app.services.position_value import position_base_value
from app.services.source_hierarchy_service import source_tier_key
from app.services.thesis_publication_gate import archived_thesis_notice, thesis_withheld_reason

# Los nombres son los que persiste la ingesta (financial_ingestion_service):
# el efectivo se guarda como "cash_and_equivalents"; pedir "cash" aqui dejaba
# ese hueco siempre sin cubrir ("Faltan entradas: cash") con el dato ya en DB.
KEY_FACT_METRICS = [
    "revenue",
    "free_cash_flow",
    "operating_cash_flow",
    "net_income",
    "net_debt",
    "cash_and_equivalents",
    "total_debt",
    "shares_diluted",
]

# Estados y ratings de tesis: la respuesta visible nunca muestra la clave
# interna en ingles ("estado insufficient_data"); lo desconocido se omite.
_THESIS_STATUS_ES = {
    "draft": "borrador",
    "final": "final",
    "published": "publicada",
    "approved": "aprobada",
    "changes_requested": "cambios solicitados",
    "draft_failed_audit": "borrador (auditoría no superada)",
    "active": "activa",
    "review": "en revisión",
    "archived": "archivada",
    "stale": "desactualizada",
    "insufficient_data": "datos insuficientes",
}
_THESIS_RATING_ES = {
    "buy": "compra",
    "overweight": "sobreponderar",
    "outperform": "mejor que el mercado",
    "accumulate": "acumular",
    "add": "añadir",
    "hold": "mantener",
    "sell": "venta",
    "underweight": "infraponderar",
    "underperform": "peor que el mercado",
    "exit": "salir",
    "watch": "seguimiento",
    "reduce": "reducir",
    "insufficient_data": "datos insuficientes",
}

_METRIC_LABELS_ES = {
    "revenue": "ingresos",
    "free_cash_flow": "flujo de caja libre",
    "operating_cash_flow": "flujo de caja operativo",
    "net_income": "beneficio neto",
    "net_debt": "deuda neta",
    "cash_and_equivalents": "efectivo y equivalentes",
    "total_debt": "deuda total",
    "shares_diluted": "acciones diluidas",
    "market_cap": "capitalización bursátil",
}

_MONTHS_ES = (
    "ene", "feb", "mar", "abr", "may", "jun",
    "jul", "ago", "sep", "oct", "nov", "dic",
)


def _fmt_number_es(number: float, digits: int = 2) -> str:
    """1.234.567,89 al estilo es-ES (puntos de miles, coma decimal)."""
    text = f"{number:,.{digits}f}".rstrip("0").rstrip(".")
    return text.replace(",", "").replace(".", ",").replace("", ".")


def _fmt_money_es(number: float, digits: int = 2) -> str:
    """Importe con decimales fijos en es-ES: 7.933,60 (no se recortan ceros)."""
    text = f"{number:,.{digits}f}"
    return text.replace(",", " ").replace(".", ",").replace(" ", ".")


def _currency_display(currency: str) -> str:
    return "€" if currency == "EUR" else currency


def _price_display(value: Decimal | int | float, currency: str | None) -> str:
    # Preserve small quotes instead of rounding a real nonzero price to zero.
    magnitude = abs(Decimal(str(value)))
    digits = max(2, -magnitude.adjusted() + 3) if 0 < magnitude < 1 else 2
    text = f"{value:,.{digits}f}"
    if currency == "USD":
        return f"${text}"
    text = text.replace(",", "\x07").replace(".", ",").replace("\x07", ".")
    if not currency or not currency.strip():
        return f"{text} (divisa no declarada)"
    return f"{text} {'€' if currency == 'EUR' else currency}"


def _fmt_value_es(value: float | None, unit: str | None) -> str:
    """Cifra legible: -71,5 millones USD / 1,14 mil millones USD / 300 acciones."""
    if value is None:
        return "sin dato"
    sign = "-" if value < 0 else ""
    magnitude = abs(value)
    if unit == "shares":
        suffix = " acciones"
    elif unit and unit != "decimal":
        suffix = f" {unit}"
    else:
        suffix = ""
    if magnitude >= 1e9:
        rendered = f"{_fmt_number_es(magnitude / 1e9)} mil millones"
    elif magnitude >= 1e6:
        rendered = f"{_fmt_number_es(magnitude / 1e6)} millones"
    elif magnitude >= 1e3:
        rendered = f"{_fmt_number_es(magnitude / 1e3)} mil"
    else:
        rendered = _fmt_number_es(magnitude)
    return f"{sign}{rendered}{suffix}"


def _fmt_period_es(period: str | None, fiscal_year: int | None = None,
                   fiscal_quarter: str | None = None) -> str:
    """'2025-12-31:FY' -> 'ejercicio 2025'; '2025-09-30:Q3' -> 'Q3 2025'."""
    text = (period or "").strip()
    match = re.match(r"^(\d{4})-\d{2}-\d{2}:(FY|Q[1-4])$", text)
    if match:
        year, quarter = match.groups()
        return f"ejercicio {year}" if quarter == "FY" else f"{quarter} {year}"
    if fiscal_year:
        if fiscal_quarter and fiscal_quarter != "FY":
            return f"{fiscal_quarter} {fiscal_year}"
        return f"ejercicio {fiscal_year}"
    return text or "periodo sin fecha"


def _savings_scale_label(year: int) -> str:
    """Última escala del ahorro verificada: 2025 (Ley 7/2024).

    Para años posteriores se reutiliza y se dice, sin afirmar que sea la
    vigente de ese año.
    """
    if year <= 2025:
        return f"escala del ahorro {year}"
    return f"escala del ahorro de 2025 (la última verificada; la de {year} no está confirmada)"


def _fmt_date_es(iso_date: str | None) -> str:
    """'2026-10-16' -> '16 oct 2026'."""
    text = (iso_date or "").strip()
    match = re.match(r"^(\d{4})-(\d{2})-(\d{2})(?:[T ].*)?$", text)
    if not match:
        return text or "sin fecha"
    year, month, day = match.groups()
    month_index = int(month) - 1
    if not 0 <= month_index < 12:
        return text
    return f"{int(day)} {_MONTHS_ES[month_index]} {year}"


_INLINE_REF_RE = re.compile(r"\[([a-z_]+:[^\]\s]+)\]")


def _prune_sources(
    sources: list[dict], sections: list[dict], answer: str
) -> list[dict]:
    """Fuentes visibles: solo las que la respuesta USA de verdad.

    Se conserva una fuente si alguna seccion la cita (lista de citas o
    referencia inline ``[tipo:id]`` en el cuerpo), si es el precio mostrado
    en la prosa o si es una noticia cuyo titular aparece en la respuesta.
    Las afirmaciones (claim) se conservan siempre: son el estado vivo y
    auditado de la tesis (acotado a 8 por la recuperacion), cada una lleva
    su estado visible y de ellas se computa la respuesta (avisos de
    pendientes/contradichas y acciones propuestas). Y con cada afirmacion
    viaja su evidencia: la cadena de veracidad afirmacion -> evidencia no
    se puede cortar, sin ella la afirmacion parece respaldarse en nada.
    La evidencia huerfana (de una afirmacion que ya no esta en la lista)
    si se poda.
    El resto (recuperadas "por si acaso") no se adjunta: ensenarlas sugiere
    un respaldo que la respuesta no tiene. Ademas se deduplican por tipo y
    titulo normalizado (cuatro chunks del mismo documento son una fuente).
    """
    cited: set[str] = set()
    for section in sections:
        for citation in section.get("citations") or []:
            cited.add(str(citation))
        for ref in _INLINE_REF_RE.findall(section.get("body") or ""):
            cited.add(ref)
    answer_plain = " ".join((answer or "").lower().split())
    kept: list[dict] = []
    seen: set[tuple[str, str]] = set()
    kept_claim_ids: set = set()
    for source in sources:
        kind = str(source.get("type"))
        key = f"{kind}:{source.get('id')}"
        keep = key in cited
        if not keep and kind == "claim":
            # Las afirmaciones vivas son el libro mayor auditado de la
            # tesis: la respuesta se computa sobre ellas (avisos de
            # pendientes/contradichas, acciones propuestas) y cada una
            # declara su propio estado, asi que mostrarlas nunca sugiere
            # un respaldo que no existe.
            keep = True
        if not keep and kind == "claim_evidence":
            # Las evidencias siguen a su afirmacion en `sources`; si la
            # afirmacion se conserva, su evidencia tambien (va citada por
            # transitividad: la respuesta muestra la afirmacion).
            keep = source.get("claim_id") in kept_claim_ids
        if not keep and kind == "market_price":
            keep = True
        if not keep and kind == "news_event":
            title = " ".join(str(source.get("title") or "").lower().split())
            keep = bool(title) and (title in answer_plain or _short(title, 110).lower() in answer_plain)
        if not keep:
            continue
        dedupe_key = (kind, " ".join(str(source.get("title") or "").lower().split()))
        if kind == "document_chunk":
            # Cada pasaje citado es evidencia distinta (empleados en un sitio,
            # MAPCs en otro): deduplicar por titulo dejaba al LLM solo el
            # primer pasaje del 10-K.
            dedupe_key = (kind, str(source.get("id")))
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        if kind == "claim":
            kept_claim_ids.add(source.get("id"))
        kept.append(source)
    return kept


# Mercados de EE. UU. donde un emisor presenta ante la SEC. OTC queda fuera:
# muchos valores OTC son extranjeros (p. ej. KRKNF, canadiense) y solo cuentan
# si la ficha trae CIK.
_SEC_EXCHANGES = frozenset({
    "NYSE", "NASDAQ", "AMEX", "NYSE AMERICAN", "NYSEAMERICAN", "NYSE ARCA", "NYSEARCA",
    "ARCA", "BATS", "CBOE", "NMS", "NGM", "NCM", "NASDAQGS", "NASDAQGM", "NASDAQCM",
})


def files_with_sec(company: Company) -> bool:
    """¿Tiene sentido pedir hechos a la SEC para esta empresa?

    Sí con CIK. Sin CIK, solo si cotiza en una bolsa de EE. UU. y el ticker no
    lleva sufijo de mercado extranjero (CGEO.L, SAN.MC). La SEC no cubre la
    Bolsa de Londres: decirle a alguien que ingiera datos SEC de CGEO.L es un
    consejo imposible (prueba real, 27-oct).
    """
    if (company.cik or "").strip():
        return True
    ticker = (company.ticker or "").upper()
    if "." in ticker:
        return False
    return (company.exchange or "").strip().upper() in _SEC_EXCHANGES


def primary_sources_hint(company: Company) -> str:
    if files_with_sec(company):
        return "ingiere sus fuentes primarias (SEC/FMP)"
    market = (company.exchange or "").strip() or "su mercado"
    return (
        f"la SEC no cubre {market}, así que sus fuentes son FMP y los informes "
        "anuales de la propia empresa: ingiérelos desde su ficha"
    )


def _news_headline_line(news: list[NewsEvent]) -> str | None:
    """Titulares recientes en una frase; None si no hay ninguno con texto.

    Sin duplicados (mismo titular normalizado) y sin truncar: el titular va
    entero, como mucho los dos mas recientes.
    """
    dated = sorted(
        (event for event in news if event.date),
        key=lambda event: event.date, reverse=True,
    )
    seen_titles: set[str] = set()
    headlines = []
    for event in dated or news:
        title = " ".join((event.title or "").split())
        key = title.lower()
        if not title or key in seen_titles:
            continue
        seen_titles.add(key)
        headlines.append(f"'{title}' ({_fmt_date_es(event.date.isoformat())})")
        if len(headlines) == 2:
            break
    if not headlines:
        return None
    return "Últimas noticias guardadas: " + "; ".join(headlines) + "."


def _natural_company_answer(
    *,
    company: Company,
    facts: list[FinancialFact],
    thesis: ThesisVersion | None,
    news: list[NewsEvent],
    missing_metrics: list[str],
    claims: list[Claim],
    contradiction_claims: list[Claim],
    price_line: str | None,
    memory_notes: list[str] | None = None,
    market_cap_fact: FinancialFact | None = None,
    question: str = "",
    thesis_withheld: str | None = None,
) -> str:
    """Respuesta visible: prosa natural en castellano.

    La estructura HECHO/CALCULO/... sigue en `sections` (panel plegado con
    sus citas); lo que lee el usuario de un vistazo es esto. Nada de IDs de
    fuente, siglas de seccion ni titulares en ingles en el cuerpo: el detalle
    queda plegado.
    """
    parts: list[str] = []
    thesis_line: str | None = None
    if price_line:
        parts.append(price_line)
    if market_cap_fact is not None and market_cap_fact.value is not None:
        parts.append(
            "Capitalización bursátil: "
            f"{_fmt_value_es(_decimal_to_float(market_cap_fact.value), market_cap_fact.unit)} "
            f"({_fmt_period_es(market_cap_fact.period, market_cap_fact.fiscal_year, market_cap_fact.fiscal_quarter)}, "
            f"{market_cap_fact.source_type or 'fuente almacenada'})."
        )
    focus_metrics = _question_metrics(question)
    if focus_metrics:
        facts = sorted(facts, key=lambda f: f.metric not in focus_metrics)
    if facts:
        rendered = "; ".join(
            f"{_METRIC_LABELS_ES.get(fact.metric, fact.metric)} "
            f"{_fmt_value_es(_decimal_to_float(fact.value), fact.unit)} "
            f"({_fmt_period_es(fact.period, fact.fiscal_year, fact.fiscal_quarter)}, "
            f"{fact.source_type or 'fuente almacenada'})"
            for fact in facts[:5]
        )
        parts.append(f"Datos almacenados: {rendered}.")
    else:
        parts.append(
            f"Todavía no tengo hechos financieros fiables almacenados para "
            f"{company.ticker}; {primary_sources_hint(company)} y te respondo con cifras."
        )
    if thesis and thesis_withheld:
        thesis_line = archived_thesis_notice(thesis, thesis_withheld)
        parts.append(thesis_line)
    elif thesis:
        detalles = []
        estado = _THESIS_STATUS_ES.get((thesis.status or "").strip())
        rating_es = _THESIS_RATING_ES.get((thesis.rating or "").strip())
        if estado:
            detalles.append(f"estado {estado}")
        if rating_es:
            detalles.append(f"rating {rating_es}")
        thesis_line = (
            f"Tengo guardada la tesis v{thesis.version}"
            + (f" ({', '.join(detalles)})." if detalles else ".")
        )
        parts.append(thesis_line)
    seen_notes: set[str] = set()
    for content in (memory_notes or [])[:3]:
        note = _short(content, 180)
        key = " ".join(note.lower().split())
        if key in seen_notes:
            continue
        seen_notes.add(key)
        parts.append(f"De tus notas guardadas: '{note}'.")
    if news:
        line = _news_headline_line(news)
        if line is not None:
            parts.append(line)
    if contradiction_claims:
        parts.append(
            f"Hay {len(contradiction_claims)} afirmaciones contradichas o "
            f"desactualizadas que conviene revisar."
        )
    elif any(claim.status == "unverified" for claim in claims):
        parts.append("Hay afirmaciones pendientes de verificar.")
    if missing_metrics:
        labels = ", ".join(_METRIC_LABELS_ES.get(m, m) for m in missing_metrics)
        parts.append(f"Aun faltan datos almacenados de: {labels}.")
    lead = _answer_lead(
        question, company=company, facts=facts, thesis=thesis, thesis_line=thesis_line,
        thesis_withheld=thesis_withheld,
        news=news, claims=claims, contradiction_claims=contradiction_claims,
        price_line=price_line, focus_metrics=focus_metrics,
    )
    if lead:
        parts = [lead, *[p for p in parts if not lead.startswith(p)]]
    if re.search(r"comp[aá]r|\bvs\.?\b|versus|frente a|respecto a", (question or "").lower()):
        parts.insert(
            1 if lead else 0,
            f"No puedo comparar dos empresas en una misma respuesta: te contesto solo sobre "
            f"{company.ticker}. Pregunta por la otra empresa por separado.",
        )
    return "\n\n".join(parts)


_METRIC_KEYWORDS = (
    (r"ingres|ventas|factur", ("revenue",)),
    (r"benefici|ganancia|resultado", ("net_income",)),
    (r"flujo de caja|caja libre|\bfcf\b", ("free_cash_flow", "operating_cash_flow")),
    (r"deuda", ("net_debt", "total_debt")),
    (r"efectivo|liquidez|\bcaja\b", ("cash_and_equivalents",)),
    (r"acciones diluidas|n[uú]mero de acciones", ("shares_diluted",)),
    (r"capitalizaci|market cap", ("market_cap",)),
)


def _question_metrics(question: str) -> set[str]:
    text = (question or "").lower()
    found: set[str] = set()
    for pattern, metrics in _METRIC_KEYWORDS:
        if re.search(pattern, text):
            found.update(metrics)
    return found


def _answer_lead(
    question: str, *, company: Company, facts: list[FinancialFact], thesis: ThesisVersion | None,
    thesis_line: str | None, news: list[NewsEvent], claims: list[Claim],
    contradiction_claims: list[Claim], price_line: str | None, focus_metrics: set[str],
    thesis_withheld: str | None = None,
) -> str | None:
    """Primera frase que contesta lo preguntado con lo que hay guardado; nunca inventa.

    Sin intención reconocida no hay lead y la respuesta queda como el resumen
    habitual. Con intención reconocida y sin dato guardado, lo dice.
    """
    text = (question or "").lower()
    if not text.strip():
        return None
    ticker = company.ticker
    if re.search(r"riesgo", text):
        bits = []
        if contradiction_claims:
            bits.append(f"{len(contradiction_claims)} afirmaciones contradichas o desactualizadas")
        pending = sum(1 for c in claims if c.status == "unverified")
        if pending:
            bits.append(f"{pending} afirmaciones pendientes de verificar")
        if thesis is not None and not thesis_withheld and thesis.valuation_risk_score:
            bits.append(f"riesgo de valoración {thesis.valuation_risk_score}/100 en la tesis v{thesis.version}")
        if bits:
            return f"Sobre los riesgos de {ticker}, lo guardado señala: " + "; ".join(bits) + "."
        return f"No tengo riesgos documentados guardados de {ticker}."
    if re.search(
        r"tesis|valoraci|valor intr[ií]nseco|valor justo|valor esperado|margen de seguridad|rating|"
        r"infravalor|sobrevalor",
        text,
    ):
        if thesis is None or thesis_line is None:
            return f"No tengo ninguna tesis guardada de {ticker}."
        if thesis_withheld:
            return thesis_line
        summary = " ".join((thesis.executive_summary or "").split())
        draft_note = (
            " Es un borrador: cualquier rango de valor que aparezca es indicativo, no un valor intrínseco final."
            if (thesis.status or "").strip() != "published" else ""
        )
        return thesis_line + draft_note + (f" Resumen: {_short(summary, 320)}" if summary else "")
    if focus_metrics:
        wanted = [f for f in facts if f.metric in focus_metrics]
        if not wanted:
            labels = ", ".join(sorted(_METRIC_LABELS_ES.get(m, m) for m in focus_metrics))
            return f"No tengo guardado ese dato de {ticker} ({labels})."
        f = wanted[0]
        return (f"{_METRIC_LABELS_ES.get(f.metric, f.metric).capitalize()} de {ticker}: "
                f"{_fmt_value_es(_decimal_to_float(f.value), f.unit)} "
                f"({_fmt_period_es(f.period, f.fiscal_year, f.fiscal_quarter)}, {f.source_type or 'fuente almacenada'}).")
    if re.search(r"precio|cotiza|cotizaci", text) and price_line:
        return price_line
    if re.search(r"noticia|titular|novedad", text):
        if not news:
            return f"No tengo noticias guardadas de {ticker}."
        # Se contesta primero lo preguntado: la misma frase que cierra el
        # resumen, que el llamador desduplica (lead.startswith(part)).
        line = _news_headline_line(news)
        if line is not None:
            return line
    return None


_GENERATED_SUMMARY_RE = re.compile(r"^Generated from (.+?) source\.?$")


def _human_evidence_title(summary: str | None, limit: int = 140) -> str:
    """Titulo visible de una evidencia: nunca la plantilla interna en ingles."""
    text = (summary or "").strip()
    match = _GENERATED_SUMMARY_RE.match(text)
    if match:
        return f"Generado desde la fuente {match.group(1)}"
    return _short(text, limit)


def _decimal_to_float(value: Decimal | int | float | None) -> float | None:
    if value is None:
        return None
    return float(value)


def _short(text: str, limit: int = 420) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    # Corte en el ultimo espacio: un titular nunca se trunca a mitad de palabra.
    cut = compact[: limit - 1].rsplit(" ", 1)[0]
    return f"{cut}…"



# Saludos y marca viven en el cerebro común (brain_service). Alias
# compatibles para los tests que los importaban de aquí.
_SMALL_TALK_RE = SMALL_TALK_RE
_small_talk_answer = small_talk_answer


_COMMON_WORD_TICKERS = frozenset(
    {"META", "NOW", "IT", "ON", "CAT", "ALL", "ARE", "KEY", "LOW", "FAST", "WELL", "A", "BIG", "GOOD", "ES"}
)
# Palabra previa que convierte la palabra comun en un sustantivo ("mi meta").
_DETERMINERS = frozenset(
    {"mi", "mis", "tu", "tus", "su", "sus", "la", "las", "el", "un", "una", "esta", "esa", "otra",
     "nuestra", "my", "your", "our", "the", "a", "this", "that", "his", "her", "their"}
)
_COMPANY_CUE_RE = re.compile(
    r"(?i)\b(tesis|thesis|an[aá]lisis|analiza\w*|ficha|empresa|compa[nñ][ií]a|"
    r"acci[oó]n(?:es)?|cotiza\w*|precio|valoraci[oó]n|resultados|balance|"
    r"riesgos?|catalizadores?|noticias?|dividendos?|fundamentales|stock)\b"
)
# "Que puedes hacer?" se responde de forma determinista con lo que el
# asistente cumple de verdad; el generador libre prometia capacidades que
# no existen ("revisar carteras y sugerir ajustes").
_CAPABILITIES_RE = re.compile(
    r"(?i)^\s*[¿¡]?\s*(?:"
    r"qu[eé]\s+(?:puedes|puede|sabes)\s+hacer|"
    r"(?:en\s+)?qu[eé]\s+(?:me\s+)?puedes\s+ayudar|"
    r"c[oó]mo\s+(?:es\s+que\s+)?(?:me\s+)?puedes\s+ayudar|"
    r"qu[eé]\s+(?:eres|es\s+esto)|qui[eé]n\s+eres|para\s+qu[eé]\s+sirves|"
    r"qu[eé]\s+es\s+(?:gerarai|cavaai|esta\s+(?:app|aplicaci[oó]n))|"
    r"what can you do|who are you"
    r")"
    # Preguntas gemelas: "quien eres y que puedes hacer" (en cualquier orden).
    r"(?:\s+y\s+(?:qu[eé]\s+(?:puedes|sabes)\s+hacer|qui[eé]n\s+eres))*"
    r"\s*[?!.]*\s*$"
)
_CAPABILITIES_ANSWER = (
    "Soy el Cerebro de GerarAI. Puedo contarte qué posiciones tienes "
    "guardadas, cuánto pesa cada una y cuánto vale tu cartera, incluida la "
    "caja y la deuda de margen. Puedo responder sobre una empresa concreta "
    "con los datos guardados: precio, cifras financieras, tesis, noticias y "
    "sus fuentes. También explico conceptos de inversión y, si tienes cartas "
    "o documentos ingeridos en la biblioteca, los uso para responderte con "
    "su autor. No ejecuto órdenes ni doy recomendaciones personalizadas: "
    "te muestro tus datos guardados y conocimiento general."
)

_DOCTRINE_CUE_RE = re.compile(
    r"(?i)\b(?:doctrina|biblioteca|"
    r"buffett|munger|howard\s+marks|fundsmith|smithson|numantia|azvalor|magallanes|"
    r"value\s+investing|inversi[oó]n\s+en\s+valor)\b"
)


# Palabras comunes no prueban que el usuario consulte una fuente: "a
# principios de año" o "una carta a mi banco" siguen siendo preguntas
# personales. Solo los términos cualificados indican doctrina de inversión.
_DOCTRINE_QUALIFIED_RE = re.compile(
    r"(?i)\b(?:cartas?\s+(?:a\s+(?:los\s+)?)?(?:accionistas|inversores)|"
    r"cartas?\s+de\s+(?:inversi[oó]n|fondos?|gestores?)|"
    r"(?:principios|filosof[ií]a)\s+de\s+(?:la\s+)?inversi[oó]n)\b"
)


def _is_doctrine_question(question: str) -> bool:
    return bool(_DOCTRINE_CUE_RE.search(question) or _DOCTRINE_QUALIFIED_RE.search(question))


_PORTFOLIO_SELF_RE = re.compile(
    r"(?i)\b(?:mi|mis)\s+(?:cartera|posici[oó]n(?:es)?|inversi[oó]n(?:es)?|acciones|holdings)\b"
    r"|\bmy\s+(?:portfolio|positions|holdings)\b"
)
# Preguntas de analisis sobre la cartera ("¿qué riesgos tiene mi cartera?"):
# "mi cartera" solo las mandaba al volcado de posiciones, que contesta otra
# cosa sin LLM. Siguen por la ruta de sintesis (LLM con datos de cartera).
_PORTFOLIO_ANALYSIS_RE = re.compile(
    r"(?i)\b(?:riesgos?|riesgosa|arriesgad\w*|diversific\w*|concentraci[oó]n|"
    r"exposici[oó]n|vulnerab\w*|debilidades|fortalezas|qu[eé]\s+opinas|"
    r"c[oó]mo\s+(?:la\s+)?(?:mejorar|veo)|risks?|diversif\w*)\b"
)
_ORDER_VERB_RE = re.compile(r"(?i)\b(compra|compro|comprar|vende|vendo|vender|ejecuta|buy|sell)\b")
# "¿Cuál es mi posición con más peso?" / "¿qué posición pesa menos?": ranking
# directo de posiciones guardadas, no el volcado de la tabla completa.
_PORTFOLIO_RANKING_RE = re.compile(
    r"(?i)(?:qu[eé]|cu[aá]l)\b[^.!?\n]{0,30}\b(?:m[aá]s|mayor|menos|menor)\s+(?:peso|pesa|vale|valor|grande|peque[nñ]a)\b"
    r"|\bposici[oó]n\b[^.!?\n]{0,25}\b(?:m[aá]s|mayor|menos|menor)\s+(?:peso|grande|peque[nñ]a|valor)\b"
    r"|\bposici[oó]n\s+(?:que\s+)?pesa\s+(?:m[aá]s|menos)\b"
    r"|\b(?:mayor|menor)\s+posici[oó]n\b"
)
# Rentabilidad de la cartera o de una posición: cifra guardada (coste base y
# valor base), declarada como rentabilidad simple sobre coste, nunca TWR.
_PERFORMANCE_RE = re.compile(
    r"(?i)\b(?:rentabilidad|rendimiento|ganancia(?:s)?|p[ée]rdida(?:s)?|"
    r"cu[aá]nto\s+(?:he\s+)?(?:ganado|perdido)|c[oó]mo\s+(?:me\s+)?va\s+(?:la|mi)\s+inversi[oó]n)\b"
)
# "¿Qué es la rentabilidad?" / "¿cómo se calcula?" son preguntas de concepto:
# las responde la ruta educativa, no la cifra de cartera.
_CONCEPT_QUESTION_RE = re.compile(
    r"(?i)\b(?:qu[eé]\s+es|qu[eé]\s+significa|c[oó]mo\s+se\s+calcula|en\s+qu[eé]\s+consiste)\b"
)
# Preguntas de cartera sin la formula "mi cartera": recuento, peso, valor o
# patrimonio. Se responden con los datos guardados del tenant, nunca con una
# orden ni con una recomendacion.
_PORTFOLIO_QUERY_RE = re.compile(
    r"(?i)\b(?:cu[aá]ntas\s+posiciones|posiciones\s+(?:abiertas\s+)?tengo|"
    r"qu[eé]\s+posici[oó]n\s+pesa|patrimonio(?:\s+neto)?|"
    r"valor\s+(?:total\s+)?de\s+(?:la|mi)\s+cartera|"
    r"c[oó]mo\s+va\s+(?:la|mi)\s+cartera)\b"
)
# Pregunta por la posicion de un ticker concreto ("peso de ASTS",
# "cuanto tengo en ASTS", "acciones de ASTS que tengo").
_POSITION_QUERY_RE = re.compile(
    r"(?i)\b(?:peso|posici[oó]n|acciones)\b[^.!?\n]{0,40}\b(?:cartera|tengo|mis)\b"
    r"|\b(?:peso|posici[oó]n)\s+(?:de|en|que)\b"
    r"|\bcu[aá]nt[oa]s?\s+(?:acciones\s+)?(?:tengo|vale|valen|tienen)\b"
    # "cuánto pesa ASTS (en mi cartera)" / "qué peso tiene ASTS": la forma
    # verbal de peso tambien es pregunta de posicion.
    r"|\bcu[aá]nt[oa]\s+pesa[n]?\b"
    r"|\bqu[eé]\s+peso\s+tiene[n]?\b"
)
# Impuesto de una venta de un ticker concreto («¿cuánto IRPF pagaría si vendo
# todo UBER?»). Antes el verbo «vendo» la sacaba de la ruta de posición (es
# un verbo de orden) y el sintetizador de empresa no recibía la posición:
# respondía «no tengo su posición» con 30 UBER guardadas (prueba real
# realqa-23). Es una simulación sobre datos guardados, nunca una orden.
_SALE_TAX_RE = re.compile(
    r"(?i)\b(?:irpf|impuestos?|hacienda|tribut\w*|plusval[ií]as?)\b"
)
# «si vendo 10 UBER» / «vendiera 12,5 acciones»: cantidad parcial opcional.
_SALE_QTY_RE = re.compile(
    r"(?i)\bvend\w*\s+(?:solo\s+|s[oó]lo\s+)?(\d+(?:[.,]\d+)?)\s*(?:acciones|t[ií]tulos|participaciones)?\b"
)
_SALE_TAX_PROMPT_VERSION = "portfolio-sale-tax-v3"
_SALE_HALF_RE = re.compile(r"(?i)\bvend\w*\s+(?:la\s+)?mitad\b")
# «¿cuántos impuestos paga UBER?» es la fiscalidad de la empresa, no la tuya:
# hace falta venta, IRPF o primera persona para ir a la simulación.
_SALE_CONTEXT_RE = re.compile(
    r"(?i)\b(?:vend\w*|venta|irpf|pagar[ií]a|pagar[ée]|tributar[ií]a|mis|tengo)\b"
)
# Venta propia explícita: con impuesto + venta la pregunta es SIEMPRE tu IRPF,
# tengas o no el valor. Revisión de Nico: «¿cuánto IRPF pagaría si vendo
# AAPL?» sin AAPL en cartera cambiaba a la información de la empresa sin
# decir que no calculaba el impuesto.
_SALE_VERB_RE = re.compile(r"(?i)\b(?:vend\w*|venta)\b")
_NO_POSITION_OFFER = "Si me dices cuántas acciones, a qué precio y cuándo las compraste, te hago la estimación."
# Primera palabra de un nombre que no identifica a una empresa por sí sola.
_GENERIC_NAME_WORDS = frozenset({"grupo", "banco", "compania", "compañía", "company", "corporation", "holdings"})
# «si vendo mis acciones de Apple»: nombre propio de lo que se vende cuando
# no está en el maestro (no puede estar en tu cartera).
_SALE_NAMED_RE = re.compile(
    r"\b(?:acciones|participaciones|t[ií]tulos|vend\w*|venta)\s+(?:(?:de|mis|las|los|todo|todas|todos)\s+)*"
    r"([A-ZÁÉÍÓÚÑ][\w&.\-]+(?:\s+[A-ZÁÉÍÓÚÑ][\w&.\-]+)?)"
)
_NO_POSITION_TICKER_RE = re.compile(r"No tienes (.+?) en cartera, así que no puedo calcular tu IRPF real")
# Cuando la misma frase pide ademas caja o patrimonio se adjunta ese bloque.
_RANK_HIGH_RE = re.compile(
    r"(?i)\b(?:m[aá]s\s+(?:alto|caro|grande|pesad[oa])|mayor|m[aá]xim[oa]|m[aá]s\s+peso|pesa\s+m[aá]s)\b"
)
_RANK_LOW_RE = re.compile(
    r"(?i)\b(?:m[aá]s\s+(?:bajo|barato|peque[nñ]o|livian[oa]|ligera)|menor|m[ií]nim[oa]|menos\s+peso|pesa\s+menos)\b"
)
_RANK_COST_RE = re.compile(r"(?i)\bcoste\s+medio\b|\bprecio\s+medio\b")
_RANK_VALUE_RE = re.compile(r"(?i)\b(?:valor|pes[oa])\b")
_RANK_WEIGHT_LABEL_RE = re.compile(r"(?i)\bpes[oa]\b")


def _ranking_metric(question: str) -> tuple[str, str, bool] | None:
    """(métrica, etiqueta, ¿el más alto?) si es una pregunta de ranking; si no, None."""
    high = bool(_RANK_HIGH_RE.search(question))
    low = bool(_RANK_LOW_RE.search(question))
    if high == low:
        return None
    if _RANK_COST_RE.search(question):
        return ("cost", "coste medio", high)
    if _RANK_VALUE_RE.search(question):
        label = "peso" if _RANK_WEIGHT_LABEL_RE.search(question) else "valor"
        return ("value", label, high)
    return None


def _history_is_portfolio(history: list[ChatTurn] | None) -> bool:
    """¿Va la conversación de la cartera? Mira los últimos turnos."""
    for turn in (history or [])[-4:]:
        text = turn.content or ""
        if turn.role == "assistant" and "posiciones abiertas" in text:
            return True
        if turn.role == "user" and (_PORTFOLIO_SELF_RE.search(text) or _PORTFOLIO_QUERY_RE.search(text)):
            return True
    return False


_PAGE_IDENTITY_RE = re.compile(
    r"(?i)\bqu[eé]\s+(?:p[aá]gina|pantalla|secci[oó]n)\s+(?:es\s+esta|estoy\s+viendo|es|ves)\b"
    r"|\bqu[eé]\s+estoy\s+viendo\b|\bd[oó]nde\s+estoy\b"
)
_PROMPT_OVERRIDE_RE = re.compile(
    r"(?i)\b(?:ignora|olvida|descarta)\b[^.?!\n]{0,40}\b(?:instrucciones|reglas)\b"
    r"|\b(?:tu|el)\s+prompt\b|\bsystem\s+prompt\b"
)
_PAGE_CONTENT_RE = re.compile(
    r"(?i)\b(?:en|de|sobre)\s+(?:esta|la\s+presente)\s+(?:p[aá]gina|pantalla|secci[oó]n)\b"
    r"|\b(?:esta|la)\s+(?:p[aá]gina|pantalla)\b[^.?!\n]{0,40}\b(?:hay|muestra|tiene|dice)\b"
    r"|\bqu[eé]\s+(?:hay|veo)\s+(?:aqu[ií]|en\s+pantalla)\b"
)
_NET_WORTH_CUE_RE = re.compile(r"(?i)\b(?:patrimonio|caja|margen|neto)\b")


_UNVALUED_TEXT = "sin valor en {base} (falta tipo de cambio o la valoración está suspendida)"


class ChatService:
    def __init__(self, provider: LLMProvider | None = None) -> None:
        self.memory = MemoryService()
        self.provider = provider or create_chat_llm_provider()

    def _resolve_company(self, db: Session, question: str, scope: str, ticker: str | None) -> Company | None:
        if ticker:
            return resolve_company(db, ticker)
        if scope == "portfolio":
            # El asistente global manda scope="portfolio" sin ticker. Antes eso
            # cortaba aqui y "meta tesis?" se quedaba sin empresa. Ahora solo
            # se resuelve una mencion EXPLICITA (ver _explicit_mention); sin
            # ella la pregunta sigue siendo de cartera.
            return self._explicit_mention(db, question)
        # Misma logica cuidadosa que el scope de cartera: un scan ingenuo
        # con question.upper() convertia cada palabra en candidata y
        # resolvia "es" (o cualquier sigla) como ticker real.
        return self._explicit_mention(db, question)

    def _explicit_mention(self, db: Session, question: str) -> Company | None:
        """Empresa nombrada por su ticker en el texto, para el scope global.

        - Ticker escrito en mayusculas (>= 2 letras): vale siempre.
        - Ticker en minusculas ("meta tesis?"): vale si tiene >= 3 letras y no
          es una palabra corriente; si lo es ("meta", "now") exige ademas una
          pista de consulta sobre empresas, para que "mi meta de ahorro" no se
          convierta en una pregunta sobre Meta Platforms.
        - Con varias empresas distintas nombradas no se elige ninguna: la
          ambiguedad se deja al flujo general en vez de adivinar.
        """
        companies = list(db.scalars(select(Company)).all())
        by_ticker = {company.ticker.upper(): company for company in companies}
        found: dict[str, Company] = {}
        has_cue = bool(_COMPANY_CUE_RE.search(question))
        all_caps = not any(ch.islower() for ch in question)
        recent: list[str] = []  # las dos palabras anteriores (ventana de 2)
        for match in re.finditer(r"[A-Za-z0-9][A-Za-z0-9.\-]*", question):
            raw = match.group(0).strip(".-")
            after_determiner = any(word in _DETERMINERS for word in recent)
            recent = [*recent, raw.lower()][-2:]
            if not raw:
                continue
            token = raw.upper()
            company = by_ticker.get(token)
            if company is None:
                continue
            if token in _COMMON_WORD_TICKERS:
                # Palabra corriente: siempre exige pista de empresa y que no
                # vaya tras un determinante/posesivo ("mi meta de ahorro").
                # Un ticker escrito en MAYUSCULAS (>= 3 letras) en una frase en
                # minusculas es deliberado; en minusculas pide pista de empresa.
                deliberate = raw.isupper() and not all_caps and len(token) >= 3
                ok = (deliberate or (len(token) >= 3 and has_cue)) and not after_determiner
                if len(token) < 3:
                    ok = has_cue and raw.isupper() and not all_caps and not after_determiner
            elif raw.isupper() and not all_caps:
                # Una sola letra ("T", "V") solo con pista de empresa; dos o
                # mas valen siempre. Los tickers con digito inicial entran por
                # la misma puerta ("0700.HK", "7203.T").
                ok = len(token) >= 2 or (len(token) == 1 and has_cue and not after_determiner)
            else:
                ok = len(token) >= 3
            if ok:
                found[token] = company
        if not found:
            # Nombre en texto llano («AST SpaceMobile», «Apple»): antes la
            # primera palabra en mayúsculas pasaba por ticker desconocido.
            from app.services.company_names import companies_named_in

            named = companies_named_in(question, companies)
            if len(named.companies) == 1 and not named.ambiguous:
                return named.companies[0]
        return next(iter(found.values())) if len(found) == 1 else None

    def _history_company(
        self, db: Session, question: str, history: list[ChatTurn] | None
    ) -> Company | None:
        """Empresa de la que ya se hablaba, para seguimientos sin nombre.

        «cuéntame de ASTS» → «¿cuánta deuda tiene?»: sin esta mirada al hilo,
        el seguimiento caia en la abstencion general pidiendo un ticker que el
        usuario ya habia dado. Solo aplica cuando la pregunta actual pinta a
        dato de empresa (pista de empresa o de metrica) y no es de cartera,
        doctrina ni orden; se toma la mencion explicita mas reciente de un
        turno del usuario. Si el ultimo tramo del hilo es de cartera («que
        tengo en mi cartera»), no se arrastra la empresa anterior: «y el
        efectivo?» pasaria a hablar de la empresa cuando se pregunta por la
        caja.
        """
        text = question or ""
        if not history:
            return None
        if not (_COMPANY_CUE_RE.search(text) or _question_metrics(text)):
            return None
        if (
            _PORTFOLIO_SELF_RE.search(text)
            or _ORDER_VERB_RE.search(text)
            or _is_doctrine_question(text)
        ):
            return None
        user_turns = [t.content for t in history if t.role == "user" and t.content][-4:]
        for turn in reversed(user_turns):
            mentioned = self._explicit_mention(db, turn)
            if mentioned is not None:
                return mentioned
            if _PORTFOLIO_SELF_RE.search(turn):
                return None
        return None

    def _latest_thesis(self, db: Session, company: Company) -> ThesisVersion | None:
        return latest_thesis_version(db, company)

    def _key_facts(self, db: Session, company: Company, limit: int = 8) -> list[FinancialFact]:
        # One query instead of one per metric: pick the latest fact per
        # metric in Python, preserving the per-metric ordering contract.
        rows = db.scalars(
            select(FinancialFact)
            .where(
                FinancialFact.company_id == company.id,
                FinancialFact.metric.in_(KEY_FACT_METRICS),
            )
            .order_by(
                FinancialFact.metric,
                FinancialFact.fiscal_year.desc().nullslast(),
                desc(FinancialFact.created_at),
                desc(FinancialFact.id),
            )
        ).all()
        latest: dict[str, FinancialFact] = {}
        for row in rows:
            latest.setdefault(row.metric, row)
        facts = [latest[m] for m in KEY_FACT_METRICS if m in latest]
        return facts[:limit]

    def _sections(self, db: Session, thesis: ThesisVersion | None, limit: int = 6) -> list[ThesisSection]:
        if not thesis:
            return []
        return list(
            db.scalars(
                select(ThesisSection)
                .where(ThesisSection.thesis_version_id == thesis.id)
                .order_by(ThesisSection.order_index, ThesisSection.section_key)
                .limit(limit)
            ).all()
        )

    def _claims(self, db: Session, company: Company, limit: int = 8) -> list[Claim]:
        # The live claims only: the chat answers about the current thesis, so
        # citing a claim from a superseded version answers a different question.
        return live_claims(db, company, limit=limit)

    def _recent_news(self, db: Session, company: Company, limit: int = 4) -> list[NewsEvent]:
        from app.services.ticker_news_lane import _cites_company

        # Se leen más filas y se descartan las que no citan a la empresa (feeds por
        # ticker con artículos de otra: "AAPL ... Broadcom ...").
        rows = db.scalars(
            select(NewsEvent)
            .where(NewsEvent.company_id == company.id)
            .order_by(desc(NewsEvent.date))
            .limit(limit * 6)
        ).all()
        return [r for r in rows if _cites_company(company, r.title or "", getattr(r, "summary", "") or "")][:limit]

    def _recent_sessions(self, db: Session, company: Company | None, limit: int = 4) -> list[ResearchSession]:
        statement = select(ResearchSession).order_by(desc(ResearchSession.updated_at)).limit(limit)
        if company:
            statement = statement.where(ResearchSession.company_id == company.id)
        return list(db.scalars(statement).all())

    def _document_chunks(
        self, db: Session, company: Company, question: str, limit: int = 4
    ) -> list[tuple[DocumentChunk, Document, str]]:
        """Pasajes de los documentos de la empresa (todo el 10-K, no solo los
        80 primeros fragmentos), con puente castellano->ingles y sin la
        cabecera XBRL. El tercer elemento es el pasaje que viaja al prompt."""
        from app.services.filing_passages import company_passages

        return [
            (passage.chunk, passage.document, passage.text)
            for passage in company_passages(db, company, question, limit=limit)
        ]

    def _rag_chunks(
        self,
        db: Session,
        question: str,
        company: Company | None,
        limit: int = 4,
    ) -> list[dict]:
        if os.getenv("CAVAAI_ENABLE_VECTOR_CHAT") != "1":
            return []
        try:
            from app.services.rag import RAGIndex

            hits = RAGIndex().search(
                question,
                ticker=company.ticker if company else None,
                limit=limit,
                tenant_id=db.info.get("tenant_id"),
            )
            tenant_id = db.info.get("tenant_id")
            if type(tenant_id) is not int or tenant_id <= 0:
                return []
            rows = []
            seen = set()
            for hit in hits:
                chunk_id = hit.get("entity_id")
                if hit.get("entity_type") != "document_chunk" or type(chunk_id) is not int or chunk_id in seen:
                    continue
                statement = (
                    select(DocumentChunk, Document)
                    .join(Document, Document.id == DocumentChunk.document_id)
                    .where(DocumentChunk.id == chunk_id, DocumentChunk.tenant_id == tenant_id,
                           Document.tenant_id == tenant_id)
                )
                if company:
                    statement = statement.where(Document.company_id == company.id)
                row = db.execute(statement).first()
                if not row:
                    continue
                chunk, document = row
                if not chunk.text.strip() or not chunk.qdrant_point_id or str(hit.get("point_id")) != chunk.qdrant_point_id:
                    continue
                seen.add(chunk_id)
                rows.append({
                    "point_id": chunk.qdrant_point_id, "entity_id": chunk.id,
                    "document_id": document.id, "title": document.title,
                    "source_type": document.source_type, "text": chunk.text,
                    "url": document.source_url, "chunk_index": chunk.chunk_index,
                })
            return rows
        except Exception:
            return []

    def _source_entry(self, kind: str, source_id: int | str | None, title: str, **extra) -> dict:
        payload = {
            "type": kind,
            "id": source_id,
            "title": title,
        }
        payload.update({key: value for key, value in extra.items() if value is not None})
        return payload

    async def answer(
        self,
        db: Session,
        question: str,
        scope: str,
        ticker: str | None,
        *,
        enable_debate: bool | None = None,
        use_jev: bool = True,
        page: ChatPageContext | None = None,
        history: list[ChatTurn] | None = None,
    ) -> ChatResponse:
        try:
            return await self._answer_impl(
                db, question, scope, ticker,
                enable_debate=enable_debate, use_jev=use_jev, page=page, history=history,
            )
        except TimeoutError:
            # El plazo total vencio a media generacion (p. ej. todos los
            # proveedores caidos): fallback determinista rotulado en vez de
            # propagar TimeoutError/CancelledError sin capturar.
            return ChatResponse(
                answer="La respuesta tardó demasiado; vuelve a intentarlo en un momento.",
                sources=[],
                model="deterministic",
                confidence=0,
                llm_trace={
                    "fallback": True,
                    "fallback_reason": "chat_total_deadline",
                    "deadline_seconds": get_settings().chat_total_timeout_seconds,
                },
            )

    @bounded_chat
    async def _answer_impl(
        self,
        db: Session,
        question: str,
        scope: str,
        ticker: str | None,
        *,
        enable_debate: bool | None = None,
        use_jev: bool = True,
        page: ChatPageContext | None = None,
        history: list[ChatTurn] | None = None,
    ) -> ChatResponse:
        # Contexto de página explícito ("Viendo X"): el ticker de la página se
        # resuelve en servidor en el catálogo global; el contenido privado
        # posterior sigue aislado por tenant. El eco vuelve al cliente
        # para la pastilla. Prioridad: ticker explícito > mención en el texto
        # > ticker de la página.
        page_context = resolve_page_context(db, page)
        context_echo = page_context.echo() if page_context else None
        if _SMALL_TALK_RE.match(question or ""):
            return ChatResponse(
                answer=_small_talk_answer(question),
                sources=[],
                model="small-talk",
                prompt_version="small-talk-v1",
                confidence=0.9,
                llm_trace={"path": "small_talk"},
                context=context_echo,
            )
        # "¿Qué página estoy viendo?": la identidad de la página ya está
        # resuelta en servidor; se responde sin LLM y sin fuentes (la
        # pastilla "Viendo X" es la propia UI, no un documento citable).
        if (
            page_context is not None
            and _PAGE_IDENTITY_RE.search(question or "")
            and not _PROMPT_OVERRIDE_RE.search(question or "")
        ):
            seen = (
                f"{page_context.label} ({page_context.company.name})"
                if page_context.company is not None
                else page_context.label
            )
            pointer = (
                f" Pregúntame por {page_context.ticker}: precio, financieros, tesis o noticias guardadas."
                if page_context.ticker
                else ""
            )
            return ChatResponse(
                answer=f"Estás viendo {seen}.{pointer}",
                sources=[],
                model="deterministic",
                prompt_version="page-identity-v1",
                confidence=0.9,
                llm_trace={"path": "page_identity", "generated": False, "provider_calls": 0},
                context=context_echo,
            )
        # Tu IRPF al vender va antes que los datos de empresa, el ticker
        # desconocido o el contexto personal: tengas el valor o no, se
        # responde a esa pregunta y no a otra.
        sale_tax = self._sale_tax_route(db, question, scope, ticker, page_context, history)
        if sale_tax is not None:
            sale_tax.context = context_echo
            return sale_tax
        from app.services.brain_data_tools import (
            answer_data_question,
            dividend_ticker_without_records,
        )

        missing_dividends = dividend_ticker_without_records(db, question)
        if missing_dividends is not None:
            from app.services.dividend_ingestion_service import DividendIngestionService

            try:
                await DividendIngestionService().sync_company(db, ticker=missing_dividends)
            except Exception:  # noqa: BLE001 - sin proveedor se responde con lo guardado
                db.rollback()
        # «¿Cuándo se invalidan mis tesis?»: la lista de tesis de
        # answer_data_question no lleva los criterios de invalidación; el
        # contexto personal sí.
        if not ticker and re.search(r"(?i)\binvalid", question or ""):
            from app.services.personal_answer import (
                answer_personal_question,
                detect_personal_intent,
            )

            thesis_intent = detect_personal_intent(question or "")
            if thesis_intent is not None and thesis_intent.kind == "tesis":
                personal = await answer_personal_question(db, question or "", thesis_intent, self.provider)
                if personal is not None:
                    personal.context = context_echo
                    return personal
        data_answer = answer_data_question(db, question)
        if data_answer is not None:
            # A quote question may also request a concrete metric. Do not let
            # the first deterministic tool swallow the rest of the question.
            from app.services.chat_metric_answer import metric_question_answer

            metric_company = self._resolve_company(db, question, scope, ticker)
            if metric_company is None and page_context is not None:
                metric_company = page_context.company
            extra_metric = metric_question_answer(db, question, metric_company)
            if extra_metric is not None:
                data_answer.answer += "\n\n" + extra_metric.answer
                data_answer.sources.extend(extra_metric.sources)
            data_answer.context = context_echo
            return data_answer
        # A purchase QUESTION is not an execution order. Use the same personal
        # snapshot even when a company is named or the guide supplies a ticker.
        # Otherwise "qué debo comprar hoy" lost DCA/plan/alerts on company routes.
        from app.services.personal_answer import answer_personal_question, detect_personal_intent

        purchase_intent = detect_personal_intent(question or "")
        if purchase_intent is not None and purchase_intent.kind == "barato":
            history_text = "\n".join(
                f"{turn.role}: {turn.content[:300]}" for turn in (history or [])[-4:] if turn.content
            ) or None
            personal = await answer_personal_question(
                db, question or "", purchase_intent, self.provider, history_text=history_text
            )
            if personal is not None:
                personal.context = context_echo
                return personal
        # Routing por compania RESUELTA del texto, no solo por el parametro
        # ticker: "precio de ASTS" sin campo ticker va igualmente por la
        # ruta estructurada con validacion financiera.
        company = self._resolve_company(db, question, scope, ticker)
        if company is None and page_context is not None and (
            _PAGE_CONTENT_RE.search(question or "") or _COMPANY_CUE_RE.search(question or "")
            or _question_metrics(question or "")
            or re.search(r"(?i)\b(?:evidencia|fuentes?|documentos?|riesgos?)\b", question or "")
        ):
            company = page_context.company
        # Ticker nombrado que GerarAI no tiene («¿qué opinas de TSLAA?»): se dice,
        # sin pasar por el generador libre, que inventaba sobre él.
        # Una pregunta a la biblioteca («¿qué opina la carta de Numantia
        # sobre …?») va a la recuperación aunque nombre algo con forma de
        # ticker: la respuesta está en la carta, no en el maestro.
        doctrine_question = _is_doctrine_question(question or "")
        if company is None and not ticker:
            from app.services.chat_unknown_ticker import (
                unknown_ticker_answer,
                unknown_ticker_mentions,
            )
            from app.services.company_names import ambiguous_name_answer, companies_named_in

            named = companies_named_in(question, db.scalars(select(Company)).all())
            if named.ambiguous and not named.companies and not doctrine_question:
                word, candidates = named.ambiguous[0]
                return ChatResponse(
                    answer=ambiguous_name_answer(word, candidates),
                    sources=[],
                    model="deterministic",
                    prompt_version="company-ambiguous-v1",
                    confidence=0.9,
                    llm_trace={
                        "path": "company_ambiguous", "generated": False, "provider_calls": 0,
                        "candidates": [c.ticker for c in candidates],
                    },
                    context=context_echo,
                )
            known_tickers = list(db.scalars(select(Company.ticker)).all())
            unknown = (
                [] if doctrine_question
                else unknown_ticker_mentions(question, known_tickers, ignore_spans=named.spans)
            )
            if unknown:
                return ChatResponse(
                    answer=unknown_ticker_answer(unknown, known_tickers),
                    sources=[],
                    model="deterministic",
                    prompt_version="unknown-ticker-v1",
                    confidence=0.9,
                    llm_trace={"path": "unknown_ticker", "generated": False, "provider_calls": 0, "tickers": unknown},
                    context=context_echo,
                )
        # Seguimiento sin nombre («¿y su deuda?») tras hablar de una empresa:
        # se resuelve desde el hilo. Despues del bloque de ticker desconocido
        # para que «¿y la deuda de RKLB?» siga diciendo que RKLB no existe.
        if company is None and not ticker:
            company = self._history_company(db, question or "", history)
        # Pregunta sobre el contenido de la página sin empresa: el cerebro solo
        # recibe el nombre de la sección, no sus datos. Lo dice, sin inventar
        # cifras ni citar fuentes ajenas.
        if (
            page_context is not None
            and company is None
            and not ticker
            and _PAGE_CONTENT_RE.search(question or "")
        ):
            return ChatResponse(
                answer=(
                    f"No tengo los datos de esta página ({page_context.label}): solo veo el nombre de la sección, "
                    "no su contenido. Dime qué quieres saber y lo busco en la biblioteca o en tu cartera."
                ),
                sources=[],
                model="deterministic",
                prompt_version="page-content-unavailable-v1",
                confidence=0.9,
                llm_trace={"path": "page_content_unavailable", "generated": False, "provider_calls": 0},
                context=context_echo,
            )
        from app.services.chat_metric_answer import metric_question_answer

        metric_answer = metric_question_answer(db, question, company)
        if metric_answer is not None:
            metric_answer.context = context_echo
            return metric_answer
        # Memoria SOLO ante "recuerda ..." explicito; respuesta visible, sin LLM.
        note = remember_note(question)
        if note is not None:
            item = self.memory.write_explicit_note(db, note, company, scope)
            return ChatResponse(
                answer=f"Apuntado: {note}",
                sources=[self._source_entry("memory_item", item.id, "Nota guardada por tu orden")],
                model="memory-note",
                prompt_version="memory-note-v1",
                confidence=1.0,
                llm_trace={"path": "memory_note"},
                context=context_echo,
            )
        # Saludo inicial + pregunta real ("hola, quien eres?"): se responde
        # a la pregunta, no al saludo.
        without_greeting = LEADING_GREETING_RE.sub("", question or "").strip()
        if _CAPABILITIES_RE.match(question or "") or (
            without_greeting and _CAPABILITIES_RE.match(without_greeting)
        ):
            return ChatResponse(
                answer=_CAPABILITIES_ANSWER,
                sources=[],
                model="deterministic",
                prompt_version="capabilities-v1",
                confidence=0.9,
                llm_trace={"path": "capabilities", "generated": False, "provider_calls": 0},
                context=context_echo,
            )
        if (
            company is not None
            and _SALE_TAX_RE.search(question or "")
            and _SALE_CONTEXT_RE.search(question or "")
        ):
            tax_answer = self._sale_tax_answer(db, company, question or "")
            if tax_answer is not None:
                tax_answer.context = context_echo
                return tax_answer
        if (
            company is not None
            and _POSITION_QUERY_RE.search(question or "")
            and not _ORDER_VERB_RE.search(question or "")
        ):
            position_answer = self._position_answer(db, company, question or "")
            if position_answer is not None:
                position_answer.context = context_echo
                return position_answer
        # «vende mis acciones de ASTS» / «compra mas ASTS»: GerarAI no opera
        # con el broker. Antes caia en el volcado de datos de la empresa como
        # si se hubiera preguntado por ella. Las preguntas de IRPF al vender
        # ya salieron por _sale_tax_route / _sale_tax_answer.
        if company is not None and _ORDER_VERB_RE.search(question or ""):
            return ChatResponse(
                answer=(
                    "No ejecuto órdenes: GerarAI no compra ni vende en tu bróker. "
                    f"Puedo enseñarte lo que tengo guardado de {company.ticker} "
                    "(precio, cifras, tesis y noticias, con sus fuentes) o tu posición en cartera."
                ),
                sources=[],
                model="deterministic",
                prompt_version="order-verb-v1",
                confidence=0.9,
                llm_trace={"path": "order_verb", "generated": False, "provider_calls": 0},
                context=context_echo,
            )
        if (
            company is None
            and not ticker
            and _PORTFOLIO_RANKING_RE.search(question or "")
            and not _ORDER_VERB_RE.search(question or "")
            and not doctrine_question
        ):
            ranking_answer = self._portfolio_ranking(db, question or "")
            if ranking_answer is not None:
                ranking_answer.context = context_echo
                return ranking_answer
        if (
            not ticker
            and _PERFORMANCE_RE.search(question or "")
            and not _CONCEPT_QUESTION_RE.search(question or "")
            and not _ORDER_VERB_RE.search(question or "")
        ):
            performance_answer = self._portfolio_performance(db, question or "", company)
            if performance_answer is not None:
                performance_answer.context = context_echo
                return performance_answer
        if (
            company is None
            and not ticker
            and _PORTFOLIO_SELF_RE.search(question or "")
            and _PORTFOLIO_ANALYSIS_RE.search(question or "")
            and not _ORDER_VERB_RE.search(question or "")
            and not doctrine_question
        ):
            analysis_answer = self._portfolio_analysis(db)
            if analysis_answer is not None:
                analysis_answer.context = context_echo
                return analysis_answer
        if (
            company is None
            and not ticker
            and (
                (
                    _PORTFOLIO_SELF_RE.search(question or "")
                    and not _PORTFOLIO_ANALYSIS_RE.search(question or "")
                )
                or _PORTFOLIO_QUERY_RE.search(question or "")
            )
            and not _ORDER_VERB_RE.search(question or "")
            # «¿Qué diría Numantia de mi cartera?»: pregunta mixta carta +
            # cartera. El volcado de posiciones no usa la carta; sigue a la
            # síntesis, que recibe la biblioteca y las posiciones.
            and not doctrine_question
        ):
            portfolio_answer = self._portfolio_overview(db)
            if portfolio_answer is not None:
                portfolio_answer.context = context_echo
                return portfolio_answer
        # Pregunta mixta carta + cartera («¿Qué diría Numantia de mi
        # cartera?»): antes acababa en el volcado de posiciones o en la
        # abstención general. Se responde con los fragmentos de la carta y
        # las posiciones guardadas juntos.
        if (
            company is None
            and not ticker
            and doctrine_question
            and _PORTFOLIO_SELF_RE.search(question or "")
            and not _ORDER_VERB_RE.search(question or "")
        ):
            mixed_answer = await self._doctrine_portfolio_answer(
                db, question or "", scope, history, context_echo
            )
            if mixed_answer is not None:
                return mixed_answer
        # Seguimiento de cartera ("¿cuál tiene el coste medio más alto?"): sin
        # empresa ni orden y con la cartera ya en la conversación, se responde
        # con las posiciones guardadas en lugar de perder el hilo.
        if (
            company is None
            and not ticker
            and _history_is_portfolio(history)
            and not _ORDER_VERB_RE.search(question or "")
            and not doctrine_question
        ):
            followup = self._portfolio_ranking(db, question or "")
            if followup is not None:
                followup.context = context_echo
                return followup
        # Preguntas sobre los datos propios sin empresa («¿qué riesgo tengo?»,
        # «¿qué está barato de mi watchlist?», cartera vacía): antes caían en
        # la abstención «Selecciona la empresa» o en el LLM sin contexto
        # («no tengo acceso a tu watchlist»). Se responden con el contexto
        # personal y comprobación de cifras (personal_answer).
        if company is None and not ticker and not doctrine_question:
            from app.services.personal_answer import (
                answer_personal_question,
                detect_personal_intent,
            )

            intent = detect_personal_intent(question or "")
            if intent is not None:
                history_text = "\n".join(
                    f"{turn.role}: {turn.content[:300]}" for turn in (history or [])[-4:] if turn.content
                ) or None
                personal = await answer_personal_question(
                    db, question or "", intent, self.provider, history_text=history_text
                )
                if personal is not None:
                    personal.context = context_echo
                    return personal
        if company is not None and not ticker:
            ticker = company.ticker
        # La abstencion financiera vive en el clasificador unificado de
        # synthesize_general (ronda 8 auditor): los conceptos financieros
        # genericos llegan al LLM y solo lo especifico/ambiguo se abstiene.
        baseline = self._deterministic_answer(db, question, scope, ticker)
        try:
            remaining_seconds()
        except ProviderTransportError:
            # La recuperacion (RAG/Qdrant) agoto el plazo total: responde
            # con el baseline determinista en vez de un error vacio.
            baseline.llm_trace = {"fallback": True, "fallback_reason": "chat_total_deadline"}
            baseline.context = context_echo
            return baseline
        # Fast-path Jev (4): si la pregunta es una consulta factual simple
        # (baseline_ok, conf >= 0.8), el contexto determinista ya responde y
        # se ahorra la llamada LLM de sintesis. Sin key o ante fallo,
        # sintesis como siempre.
        if use_jev and ticker:
            # nosemgrep: gerarai-broad-except-pass -- marca opcional de Jev; nunca rompe el chat
            try:
                from app.services.jev_gates import (
                    CHAT_BASELINE_OK_THRESHOLD,
                    CHAT_NEEDS_LLM_CRITERIA,
                    CHAT_NEEDS_LLM_INSTRUCTIONS,
                    jev_choice_or_none,
                )
                gate = await asyncio.wait_for(jev_choice_or_none(
                    name="chat_needs_llm",
                    text=question,
                    instructions=CHAT_NEEDS_LLM_INSTRUCTIONS,
                    criteria=CHAT_NEEDS_LLM_CRITERIA,
                ), timeout=min(1.0, remaining_seconds()))
                if (
                    gate is not None
                    and gate.label == "baseline_ok"
                    and gate.confidence >= CHAT_BASELINE_OK_THRESHOLD
                ):
                    baseline.model = "deterministic"
                    baseline.llm_trace = {
                        "fast_path": True,
                        "reason": "jev_baseline_ok",
                        "jev_gate": {
                            "label": gate.label,
                            "confidence": gate.confidence,
                        },
                    }
                    baseline.context = context_echo
                    return baseline
            except Exception:  # noqa: BLE001 — Jev nunca rompe el chat
                pass
        synthesis = ChatSynthesisService(self.provider)
        # La página visible viaja al LLM: sin ella "esta página/esta empresa"
        # no tenía referente y el modelo lo inventaba (y citaba fuentes
        # ajenas para apoyarlo).
        page_payload = context_echo
        if ticker:
            response = await synthesis.synthesize(
                question=question,
                ticker=ticker,
                baseline=baseline,
                db=db,
                enable_debate=enable_debate,
                page=page_payload,
            )
        else:
            response = await synthesis.synthesize_general(
                question=question,
                baseline=baseline,
                db=db,
                history=history,
                page=page_payload,
            )
        response.context = context_echo
        return response

    def _portfolio_positions_context(self, db: Session, limit: int = 15) -> list[dict]:
        """Posiciones guardadas en forma compacta para el prompt (sin LLM)."""
        tenant_id = db.info.get("tenant_id")
        if type(tenant_id) is not int or tenant_id <= 0:
            return []
        rows = list(
            db.execute(
                select(Position, Company)
                .join(Company, Company.id == Position.company_id)
                .where(Position.quantity > 0, Position.tenant_id == tenant_id)
            ).all()
        )
        if not rows:
            return []

        def _value(pos: Position) -> float | None:
            raw = position_base_value(pos)
            return float(raw) if raw is not None else None

        rows.sort(key=lambda row: _value(row[0]) or 0.0, reverse=True)
        bases = {pos.base_currency or "EUR" for pos, _ in rows}
        total = sum(_value(pos) or 0.0 for pos, _ in rows) if len(bases) == 1 else 0.0
        out: list[dict] = []
        for pos, comp in rows[:limit]:
            out.append({
                "ticker": comp.ticker,
                "name": comp.name,
                "sector": comp.sector,
                "weight_pct": (
                    round(value / total * 100, 1) if total > 0 and (value := _value(pos)) is not None else None
                ),
                "position_id": pos.id,
            })
        return out

    def _letter_fragments_for_portfolio(
        self, db: Session, question: str, positions: list[dict], limit: int = 3
    ) -> list[dict]:
        """Fragmentos de la carta pedida cuando la pregunta en sí no los encuentra.

        «¿Qué diría Numantia de mi cartera?» no comparte palabras con la carta:
        se busca por las empresas de la cartera y, si no, por los pasajes del
        autor que hablan de cartera, riesgo o negocios.
        """
        from app.services.library_context import lexical_library_context, named_investors

        authors = named_investors(question)
        names = " ".join(
            f"{row.get('ticker') or ''} {row.get('name') or ''}" for row in positions
        )
        rows = lexical_library_context(db, f"{question} {names}", authors=authors, limit=limit)
        if not rows:
            rows = lexical_library_context(
                db,
                "cartera negocios riesgo diversificación valoración margen de seguridad",
                authors=authors,
                limit=limit,
            )
        return rows

    async def _doctrine_portfolio_answer(
        self,
        db: Session,
        question: str,
        scope: str,
        history: list[ChatTurn] | None,
        context_echo: dict | None,
    ) -> ChatResponse | None:
        positions = self._portfolio_positions_context(db)
        if not positions:
            return None
        baseline = self._deterministic_answer(db, question, scope, None)
        if not any(source.get("type") == "knowledge_chunk" for source in baseline.sources):
            extra = self._letter_fragments_for_portfolio(db, question, positions)
            baseline.sources = [*baseline.sources, *extra]
        position_sources = [
            self._source_entry("position", row["position_id"], f"Posición {row['ticker']}", url="/portfolio")
            for row in positions
        ]
        prompt_positions = [{k: v for k, v in row.items() if k != "position_id"} for row in positions]
        response = await ChatSynthesisService(self.provider).synthesize_general(
            question=question,
            baseline=baseline,
            db=db,
            history=history,
            page=context_echo,
            portfolio_context=prompt_positions,
        )
        if response.model not in {"abstain"} and (response.llm_trace or {}).get("path") != "author_source_missing":
            response.sources = [*response.sources, *position_sources]
            trace = dict(response.llm_trace or {})
            trace["mixed"] = "doctrine_portfolio"
            response.llm_trace = trace
        response.context = context_echo
        return response

    def _portfolio_overview(self, db: Session, limit: int = 15) -> ChatResponse | None:
        """Resumen de la cartera del usuario leido de la BD, sin LLM ni recomendaciones.

        Solo lo guardado (cantidad, coste medio, valor y fecha). Sin posiciones
        devuelve None y la pregunta sigue por la ruta de siempre.
        """
        # TenantOwnedMixin no filtra solo: sin tenant valido no se lee ninguna cartera.
        tenant_id = db.info.get("tenant_id")
        if type(tenant_id) is not int or tenant_id <= 0:
            return None
        rows = list(
            db.execute(
                select(Position, Company)
                .join(Company, Company.id == Position.company_id)
                .where(Position.quantity > 0, Position.tenant_id == tenant_id)
            ).all()
        )
        if not rows:
            return None

        def _value(pos: Position) -> float | None:
            raw = position_base_value(pos)
            return float(raw) if raw is not None else None

        rows.sort(key=lambda row: _value(row[0]) or 0.0, reverse=True)
        total = sum(_value(pos) or 0.0 for pos, _ in rows)
        unvalued = sum(1 for pos, _ in rows if _value(pos) is None)
        as_of = max(pos.as_of for pos, _ in rows)
        bases = {pos.base_currency or "EUR" for pos, _ in rows}
        mixed = len(bases) > 1
        base = rows[0][0].base_currency or "EUR"
        lines = []
        sources = []
        for pos, comp in rows[:limit]:
            value = _value(pos)
            weight = (
                f" ({_fmt_number_es(value / total * 100, 1)} %)"
                if value is not None and total > 0 and not mixed
                else ""
            )
            value_text = (
                f"valor {_fmt_number_es(value, 2)} {_currency_display(pos.base_currency or 'EUR')}{weight}"
                if value is not None
                else _UNVALUED_TEXT.format(base=_currency_display(pos.base_currency or "EUR"))
            )
            lines.append(
                f"- {comp.ticker}: {_fmt_number_es(float(pos.quantity), 4)} acciones, "
                f"coste medio {_fmt_money_es(float(pos.average_cost))} {_currency_display(pos.currency)}, "
                + value_text
            )
            sources.append(self._source_entry("position", pos.id, f"Posición {comp.ticker}", url="/portfolio", as_of=str(pos.as_of)))
        extra = f"\n(Se muestran las {limit} mayores de {len(rows)}.)" if len(rows) > limit else ""
        total_text = (
            "monedas base distintas, sin total"
            if mixed
            else f"valor total {_fmt_money_es(total)} {_currency_display(base)}"
            + (f" sin contar {unvalued} sin valor en {_currency_display(base)}" if unvalued else "")
        )
        count_label = "posición abierta" if len(rows) == 1 else "posiciones abiertas"
        answer = (
            f"Tu cartera guardada tiene {len(rows)} {count_label}, {total_text}, "
            f"con datos a {_fmt_date_es(as_of.isoformat())}:\n"
            + "\n".join(lines)
            + extra
        )
        cash_line = self._cash_line(
            db, tenant_id, base if not mixed else None,
            positions_total=None if mixed or unvalued else total,
        )
        if cash_line:
            answer += "\n\n" + cash_line
        return ChatResponse(
            answer=answer,
            sources=sources,
            model="deterministic",
            prompt_version="portfolio-overview-v1",
            confidence=0.9,
            llm_trace={"path": "portfolio_overview", "generated": False, "provider_calls": 0},
        )

    def _portfolio_analysis(self, db: Session, limit: int = 5) -> ChatResponse | None:
        """Cifras de riesgo CALCULADAS de las posiciones guardadas, sin LLM.

        Concentracion (mayor posicion, top 3), reparto por divisa y por sector y
        posiciones sin valor. Solo aritmetica sobre lo guardado: no es un
        analisis de riesgos de mercado ni una recomendacion, y la respuesta lo
        dice. Sin posiciones devuelve None.
        """
        tenant_id = db.info.get("tenant_id")
        if type(tenant_id) is not int or tenant_id <= 0:
            return None
        rows = list(
            db.execute(
                select(Position, Company)
                .join(Company, Company.id == Position.company_id)
                .where(Position.quantity > 0, Position.tenant_id == tenant_id)
            ).all()
        )
        if not rows:
            return None
        bases = {pos.base_currency or "EUR" for pos, _ in rows}
        if len(bases) > 1:
            return None

        base = next(iter(bases))

        def _value(pos: Position) -> float:
            # Solo valor en moneda base: o el convertido, o el nativo cuando la
            # posicion ya esta en la base. Un nativo en otra divisa sin
            # convertir NO se suma (mezclaria divisas): cuenta como sin valor.
            if pos.market_value_base is not None:
                return float(pos.market_value_base)
            if (pos.currency or base) == base:
                # nosemgrep: gerarai-money-none-to-zero -- columna NOT NULL (default 0): el `or 0` no convierte ningun None real
                return float(pos.market_value or 0)
            return 0.0

        valued = [(pos, comp, _value(pos)) for pos, comp in rows if _value(pos) > 0]
        unvalued = [comp.ticker for pos, comp in rows if _value(pos) <= 0]
        total = sum(v for _, _, v in valued)
        if total <= 0:
            return None
        valued.sort(key=lambda row: row[2], reverse=True)
        top = valued[:limit]
        weights = [v / total * 100 for _, _, v in valued]
        lines = [
            f"- Mayor posición: {top[0][1].ticker} con {_fmt_number_es(weights[0], 1)} % de la cartera valorada.",
            f"- Las 3 mayores suman {_fmt_number_es(sum(weights[:3]), 1)} %.",
        ]
        lines.append(
            "- Mayores pesos: "
            + ", ".join(f"{comp.ticker} {_fmt_number_es(v / total * 100, 1)} %" for _, comp, v in top)
            + "."
        )
        by_currency: dict[str, float] = {}
        by_sector: dict[str, float] = {}
        for pos, comp, v in valued:
            cur = _currency_display(pos.currency)
            by_currency[cur] = by_currency.get(cur, 0.0) + v
            sector = comp.sector if comp.sector and comp.sector != "Unknown" else "sin sector"
            by_sector[sector] = by_sector.get(sector, 0.0) + v
        lines.append(
            "- Por divisa de la posición: "
            + ", ".join(f"{k} {_fmt_number_es(v / total * 100, 1)} %" for k, v in sorted(by_currency.items(), key=lambda kv: -kv[1]))
            + "."
        )
        lines.append(
            "- Por sector: "
            + ", ".join(f"{k} {_fmt_number_es(v / total * 100, 1)} %" for k, v in sorted(by_sector.items(), key=lambda kv: -kv[1])[:limit])
            + "."
        )
        if unvalued:
            lines.append(f"- Sin valor en moneda base (no entran en los porcentajes): {', '.join(sorted(unvalued))}.")
        # Reglas del panel de riesgo y TWR/caída máxima del histórico de snapshots:
        # el Cerebro ya no se queda solo en la concentración.
        from app.services.brain_context_tools import portfolio_risk_lines

        try:
            risk_lines, risk_sources = portfolio_risk_lines(db, tenant_id)
        except Exception:  # noqa: BLE001 - el panel nunca rompe la respuesta de concentración
            risk_lines, risk_sources = [], []
        lines.extend(f"- {line}" if not line.startswith("- ") else line for line in risk_lines)
        as_of = min(pos.as_of for pos, _ in rows)
        answer = (
            "Cifras calculadas de tus posiciones guardadas "
            f"(datos a {_fmt_date_es(as_of.isoformat())}), sin modelo de lenguaje. "
            "Miden concentración y reparto; no son un análisis de riesgos de mercado ni una recomendación:\n"
            + "\n".join(lines)
        )
        sources = [
            self._source_entry("position", pos.id, f"Posición {comp.ticker}", url="/portfolio", as_of=str(pos.as_of))
            for pos, comp, _ in top
        ]
        sources.extend(risk_sources)
        return ChatResponse(
            answer=answer,
            sources=sources,
            model="deterministic",
            prompt_version="portfolio-analysis-v1",
            confidence=0.9,
            llm_trace={"path": "portfolio_analysis", "generated": False, "provider_calls": 0},
        )

    def _portfolio_ranking(self, db: Session, question: str) -> ChatResponse | None:
        """Mayor/menor posición por coste medio, valor o peso, de lo guardado."""
        metric = _ranking_metric(question)
        if metric is None:
            return None
        tenant_id = db.info.get("tenant_id")
        if type(tenant_id) is not int or tenant_id <= 0:
            return None
        rows = list(
            db.execute(
                select(Position, Company)
                .join(Company, Company.id == Position.company_id)
                .where(Position.quantity > 0, Position.tenant_id == tenant_id)
            ).all()
        )
        if not rows:
            return None
        key_name, label, highest = metric

        def _value(pos: Position) -> float:
            # Orden dentro de UNA moneda (currency_of): base si existe, si no el nativo.
            raw = pos.market_value_base if pos.market_value_base is not None else pos.market_value
            return float(raw or 0)

        if key_name == "cost":
            rows = [row for row in rows if row[0].average_cost is not None and float(row[0].average_cost) > 0]
            if not rows:
                return None
            keyfn = lambda row: float(row[0].average_cost)  # noqa: E731
            currency_of = lambda row: row[0].currency or "EUR"  # noqa: E731
        else:
            keyfn = lambda row: _value(row[0])  # noqa: E731
            currency_of = (  # noqa: E731
                lambda row: (row[0].base_currency or "EUR")
                if row[0].market_value_base is not None
                else (row[0].currency or "EUR")
            )
        currencies = sorted({currency_of(row) for row in rows})
        if len(currencies) > 1:
            return ChatResponse(
                answer=(
                    f"No puedo ordenarlas por {label}: tus posiciones están en monedas distintas "
                    f"({', '.join(currencies)}) y no se pueden comparar sin convertirlas."
                ),
                sources=[],
                model="deterministic",
                prompt_version="portfolio-ranking-v1",
                confidence=0.9,
                llm_trace={"path": "portfolio_ranking", "generated": False, "provider_calls": 0, "mixed_currency": True},
            )
        rows.sort(key=keyfn, reverse=highest)
        pos, comp = rows[0]
        cur = currencies[0]
        amount = _fmt_money_es(keyfn(rows[0]))
        word = "más alto" if highest else "más bajo"
        weight_text = ""
        if key_name == "value":
            total = sum(keyfn(row) for row in rows)
            if total > 0:
                weight_text = f", el {_fmt_number_es(keyfn(rows[0]) / total * 100, 1)} % de tu cartera"
        answer = f"Tu posición con el {label} {word} es {comp.ticker}: {amount} {_currency_display(cur)}{weight_text}."
        if len(rows) > 1:
            nxt_pos, nxt = rows[1]
            answer += f" Le sigue {nxt.ticker} con {_fmt_money_es(keyfn(rows[1]))} {_currency_display(cur)}."
        return ChatResponse(
            answer=answer,
            sources=[self._source_entry("position", pos.id, f"Posición {comp.ticker}", url="/portfolio", as_of=str(pos.as_of))],
            model="deterministic",
            prompt_version="portfolio-ranking-v1",
            confidence=0.9,
            llm_trace={"path": "portfolio_ranking", "generated": False, "provider_calls": 0},
        )

    def _portfolio_performance(
        self, db: Session, question: str, company: Company | None
    ) -> ChatResponse | None:
        """Rentabilidad guardada: valor frente a coste de compra (simple, no TWR).

        Solo posiciones abiertas con sus cifras base del tenant; sin caja,
        dividendos ni ventas cerradas, y se dice asi. Monedas base mezcladas o
        coste sin datos: se declara, no se mezcla ni se inventa.
        """
        tenant_id = db.info.get("tenant_id")
        if type(tenant_id) is not int or tenant_id <= 0:
            return None
        rows = list(
            db.execute(
                select(Position, Company)
                .join(Company, Company.id == Position.company_id)
                .where(Position.quantity > 0, Position.tenant_id == tenant_id)
            ).all()
        )
        if company is not None:
            rows = [row for row in rows if row[0].company_id == company.id]
            if not rows:
                return ChatResponse(
                    answer=(
                        f"No tienes ninguna posición abierta en {company.ticker}: "
                        "no hay rentabilidad guardada que contar."
                    ),
                    sources=[],
                    model="deterministic",
                    prompt_version="portfolio-performance-v1",
                    confidence=0.9,
                    llm_trace={"path": "portfolio_performance", "generated": False, "provider_calls": 0},
                )
        if not rows:
            return None

        def _pair(pos: Position) -> tuple[float | None, float, str]:
            if pos.market_value_base is not None and pos.cost_basis_base is not None:
                return float(pos.cost_basis_base), float(pos.market_value_base), pos.base_currency or "EUR"
            # average_cost se guarda 0 cuando no se conoce (default de la columna):
            # un coste 0 no es "gratis", es desconocido. Contarlo como 0 inflaba la
            # rentabilidad con todo el valor de esa posicion como ganancia ficticia.
            avg = pos.average_cost
            cost = (
                float(avg) * float(pos.quantity)
                if avg is not None and avg > 0 and pos.quantity is not None
                else None
            )
            return cost, float(pos.market_value), pos.currency or "EUR"

        currencies = sorted({_pair(pos)[2] for pos, _ in rows})
        if len(currencies) > 1:
            return ChatResponse(
                answer=(
                    "No puedo sumar la rentabilidad: tus posiciones están valoradas en monedas "
                    f"distintas ({', '.join(currencies)}) y faltan las cifras en moneda base para compararlas."
                ),
                sources=[],
                model="deterministic",
                prompt_version="portfolio-performance-v1",
                confidence=0.9,
                llm_trace={"path": "portfolio_performance", "generated": False, "provider_calls": 0, "mixed_currency": True},
            )
        cur = currencies[0]
        pairs = [(_pair(pos), comp) for pos, comp in rows]
        unknown_cost = sorted(comp.ticker for (cost, _v, _c), comp in pairs if cost is None)
        known = [(cost, value) for (cost, value, _c), _comp in pairs if cost is not None]
        total_cost = sum(cost for cost, _ in known)
        total_value = sum(value for _, value in known)
        if total_cost <= 0:
            return ChatResponse(
                answer="No tengo el coste de compra guardado de tus posiciones: sin él no calculo rentabilidad.",
                sources=[],
                model="deterministic",
                prompt_version="portfolio-performance-v1",
                confidence=0.9,
                llm_trace={"path": "portfolio_performance", "generated": False, "provider_calls": 0},
            )
        pnl = total_value - total_cost
        pct = pnl / total_cost * 100

        def _signed(value: float) -> str:
            return f"+{_fmt_number_es(value, 2)}" if value >= 0 else _fmt_number_es(value, 2)

        label = "tu cartera" if company is None else f"tu posición en {company.ticker}"
        as_of = max(pos.as_of for pos, _ in rows)
        answer = (
            f"La rentabilidad guardada de {label} es {_signed(pct).replace(' %', '')} % "
            f"sobre el coste de compra: valor {_fmt_money_es(total_value)} {_currency_display(cur)} "
            f"frente a coste {_fmt_money_es(total_cost)} {_currency_display(cur)} "
            f"({_signed(pnl)} {_currency_display(cur)}), con datos a {_fmt_date_es(as_of.isoformat())}. "
            "Es rentabilidad simple sobre el coste de las posiciones abiertas, no TWR: "
            "no cuenta caja, dividendos ni ventas cerradas."
        )
        if unknown_cost:
            answer += (
                " Sin coste de compra guardado y fuera del cálculo: "
                + ", ".join(unknown_cost[:10])
                + (f" y {len(unknown_cost) - 10} más" if len(unknown_cost) > 10 else "")
                + "."
            )
        sources = [
            self._source_entry("position", pos.id, f"Posición {comp.ticker}", url="/portfolio", as_of=str(pos.as_of))
            for pos, comp in rows[:15]
        ]
        return ChatResponse(
            answer=answer,
            sources=sources,
            model="deterministic",
            prompt_version="portfolio-performance-v1",
            confidence=0.9,
            llm_trace={"path": "portfolio_performance", "generated": False, "provider_calls": 0},
        )

    def _cash_line(
        self,
        db: Session,
        tenant_id: int,
        base: str | None,
        *,
        positions_total: float | None = None,
    ) -> str | None:
        """Bloque de caja/margen/neto leido de cash_balances del tenant.

        Con ``base`` (monedas base homogeneas) convierte cada saldo con la
        tabla FX point-in-time y da caja, deuda de margen y neto; sin tipo de
        cambio para una divisa lo declara y no la suma. Con monedas base
        distintas (``base=None``) solo lista los saldos por divisa, sin
        inventar un total.
        """
        cash_rows = list(
            db.scalars(
                select(CashBalance).where(CashBalance.tenant_id == tenant_id)
            ).all()
        )
        if not cash_rows:
            return None
        native: dict[str, float] = {}
        for row in cash_rows:
            native[row.currency] = native.get(row.currency, 0.0) + float(row.balance)
        if base is None:
            parts = [
                f"{_fmt_money_es(amount)} {_currency_display(currency)}"
                for currency, amount in sorted(native.items())
            ]
            return (
                "Caja guardada por divisa (sin sumar, monedas base distintas): "
                + ", ".join(parts) + "."
            )
        table = PortfolioFXService().fx_table(
            db,
            currencies=set(native),
            base_currency=base,
            as_of_max=max((row.as_of for row in cash_rows), default=date.today()),
        )
        assets = 0.0
        debt = 0.0
        missing: list[str] = []
        for currency, amount in sorted(native.items()):
            as_of = max(
                (row.as_of for row in cash_rows if row.currency == currency),
                default=date.today(),
            )
            rate = PortfolioFXService.rate_from_table(
                table, quote_currency=currency, base_currency=base, as_of=as_of,
            )
            if rate is None:
                missing.append(currency)
                continue
            converted = amount * float(rate)
            if converted >= 0:
                assets += converted
            else:
                debt += -converted
        line = ""
        pieces: list[str] = []
        if assets:
            pieces.append(f"caja {_fmt_money_es(assets)} {_currency_display(base)}")
        if debt:
            pieces.append(f"deuda de margen {_fmt_money_es(debt)} {_currency_display(base)}")
        if pieces:
            line = "Además: " + " y ".join(pieces)
            if positions_total is not None:
                net = positions_total + assets - debt
                line += f"; patrimonio neto {_fmt_money_es(net)} {_currency_display(base)}"
            line += "."
        if missing:
            detalle = ", ".join(f"{_fmt_money_es(native[c])} {_currency_display(c)}" for c in missing)
            line += (
                f" Sin tipo de cambio guardado para {', '.join(missing)}"
                f" ({detalle}): esa caja no entra en la suma."
            )
        return line.strip() or None

    def _position_answer(self, db: Session, company: Company, question: str) -> ChatResponse | None:
        """Posicion guardada de un ticker: cantidad, coste, valor y peso.

        Determinista y sin recomendacion; sin posiciones del tenant devuelve
        None y la pregunta sigue por la ruta de empresa.
        """
        tenant_id = db.info.get("tenant_id")
        if type(tenant_id) is not int or tenant_id <= 0:
            return None
        rows = list(
            db.execute(
                select(Position, Company)
                .join(Company, Company.id == Position.company_id)
                .where(Position.quantity > 0, Position.tenant_id == tenant_id)
            ).all()
        )
        if not rows:
            return None

        def _value(pos: Position) -> float | None:
            raw = position_base_value(pos)
            return float(raw) if raw is not None else None

        found = [(pos, comp) for pos, comp in rows if comp.id == company.id]
        if not found:
            answer = (
                f"No tienes ninguna posición guardada en {company.ticker}; "
                f"tu cartera guardada tiene {len(rows)} posiciones abiertas en otros tickers."
            )
            return ChatResponse(
                answer=answer,
                sources=[],
                model="deterministic",
                prompt_version="portfolio-position-v1",
                confidence=0.9,
                llm_trace={"path": "portfolio_position", "generated": False, "provider_calls": 0},
            )
        pos, comp = found[0]
        total = sum(_value(p) or 0.0 for p, _ in rows)
        bases = {p.base_currency or "EUR" for p, _ in rows}
        mixed = len(bases) > 1
        unvalued = any(_value(p) is None for p, _ in rows)
        value = _value(pos)
        if value is None:
            weight_text = ""
        elif total > 0 and not mixed:
            known = " con valor conocido" if unvalued else ""
            weight_text = f", un {_fmt_number_es(value / total * 100, 1)} % del valor de tus posiciones{known}"
        else:
            weight_text = " (sin peso: monedas base distintas)"
        value_text = (
            f"valor {_fmt_money_es(value)} {_currency_display(pos.base_currency or 'EUR')}{weight_text}"
            if value is not None
            else _UNVALUED_TEXT.format(base=_currency_display(pos.base_currency or "EUR"))
        )
        answer = (
            f"Tu posición guardada en {comp.ticker}: {_fmt_number_es(float(pos.quantity), 4)} acciones, "
            f"coste medio {_fmt_money_es(float(pos.average_cost))} {_currency_display(pos.currency)}, "
            f"{value_text}, "
            f"con datos a {_fmt_date_es(pos.as_of.isoformat())}."
        )
        if _NET_WORTH_CUE_RE.search(question):
            cash_line = self._cash_line(
                db, tenant_id, None if mixed else (pos.base_currency or "EUR"),
                positions_total=None if mixed or unvalued else total,
            )
            if cash_line:
                answer += "\n\n" + cash_line
        return ChatResponse(
            answer=answer,
            sources=[self._source_entry("position", pos.id, f"Posición {comp.ticker}", url="/portfolio", as_of=str(pos.as_of))],
            model="deterministic",
            prompt_version="portfolio-position-v1",
            confidence=0.9,
            llm_trace={"path": "portfolio_position", "generated": False, "provider_calls": 0},
        )

    def _no_position_sale_answer(self, label: str) -> ChatResponse:
        """Sin posición no hay IRPF real: se dice y se ofrece la estimación, sin cambiar de tema."""
        return ChatResponse(
            answer=f"No tienes {label} en cartera, así que no puedo calcular tu IRPF real. {_NO_POSITION_OFFER}",
            sources=[],
            model="deterministic",
            prompt_version=_SALE_TAX_PROMPT_VERSION,
            confidence=0.9,
            llm_trace={
                "path": "portfolio_sale_tax", "generated": False, "provider_calls": 0,
                "no_position": True, "ticker": label,
            },
        )

    def _company_by_name(self, db: Session, question: str) -> Company | None:
        """Empresa nombrada por su nombre («mis acciones de Apple»), solo si es única."""
        words = {w.lower() for w in re.findall(r"[A-Za-zÀ-ÿ]{4,}", question or "")}
        found: dict[int, Company] = {}
        for company in db.scalars(select(Company)).all():
            first = re.findall(r"[A-Za-zÀ-ÿ]{4,}", company.name or "")
            if first and first[0].lower() in words and first[0].lower() not in _GENERIC_NAME_WORDS:
                found[company.id] = company
        return next(iter(found.values())) if len(found) == 1 else None

    def _sale_tax_route(
        self,
        db: Session,
        question: str,
        scope: str,
        ticker: str | None,
        page_context: ResolvedPageContext | None,
        history: list[ChatTurn] | None,
    ) -> ChatResponse | None:
        """«¿Cuánto IRPF pagaría si vendo X?»: siempre tu IRPF, tengas X o no.

        - Con posición: cálculo FIFO real (``_sale_tax_answer``).
        - Sin posición: lo dice y ofrece la estimación hipotética.
        - Con lotes en la pregunta (o en la respuesta a esa oferta): estimación
          con el mismo FIFO y la misma escala del ahorro.
        Nunca pasa a la información de la empresa. «¿Cuántos impuestos paga
        X?» (los de la empresa) no lleva venta y no entra aquí.
        """
        from app.services.sale_hypothetical import parse_purchase_lots

        q = question or ""
        tenant_id = db.info.get("tenant_id")
        if type(tenant_id) is not int or tenant_id <= 0:
            return None
        lots = parse_purchase_lots(q)
        intent = bool(_SALE_TAX_RE.search(q) and _SALE_VERB_RE.search(q) and _SALE_CONTEXT_RE.search(q))
        offered: str | None = None
        if not intent:
            if not lots:
                # Seguimiento de una respuesta de IRPF («y si vendo la
                # mitad?»): sin la palabra impuesto pero con venta y una
                # respuesta de IRPF reciente, es la misma pregunta sobre la
                # misma empresa (la del hilo si la pregunta no la nombra).
                if _SALE_VERB_RE.search(q):
                    last_sale = next(
                        (turn for turn in reversed(history or [])
                         if turn.role == "assistant"
                         and re.search(r"(?i)\birpf\b|impuestos?\b|ganancia\b", turn.content or "")),
                        None,
                    )
                    if last_sale is not None:
                        company = self._explicit_mention(db, q)
                        if company is None:
                            for turn in reversed(
                                [t.content for t in (history or []) if t.role == "user" and t.content][-4:]
                            ):
                                company = self._explicit_mention(db, turn)
                                if company is not None:
                                    break
                        if company is not None:
                            return self._sale_tax_answer(db, company, q)
                return None
            last = next((turn for turn in reversed(history or []) if turn.role == "assistant"), None)
            match = _NO_POSITION_TICKER_RE.search(last.content or "") if last is not None else None
            if match is None:
                return None
            offered = match.group(1)
        company = self._resolve_company(db, q, scope, ticker)
        label: str | None = None
        if company is None:
            from app.services.chat_unknown_ticker import unknown_ticker_mentions

            unknown = unknown_ticker_mentions(q, list(db.scalars(select(Company.ticker)).all()))
            if len(unknown) == 1:
                label = unknown[0]
            elif not unknown:
                company = self._company_by_name(db, q)
        if company is None and label is None:
            label = (ticker or "").strip().upper() or offered
            if label:
                company = resolve_company(db, label)
            elif page_context is not None and page_context.company is not None:
                company = page_context.company
        if company is not None:
            label = company.ticker
        elif label is None:
            named = _SALE_NAMED_RE.search(q)
            label = named.group(1) if named else None
        if lots:
            return self._hypothetical_sale_answer(db, q, lots, company, label)
        if company is not None:
            return self._sale_tax_answer(db, company, q)
        if label:
            return self._no_position_sale_answer(label)
        return None

    def _hypothetical_sale_answer(
        self, db: Session, question: str, lots: list, company: Company | None, label: str | None,
    ) -> ChatResponse:
        """Estimación con los lotes que da el usuario: mismo FIFO y misma escala del ahorro."""
        from app.services.tax_sale_intent import sale_intent_issue

        issue = sale_intent_issue(question)
        if issue:
            return ChatResponse(
                answer=issue, sources=[], model="deterministic",
                prompt_version=_SALE_TAX_PROMPT_VERSION, confidence=0.8,
                llm_trace={"path": "portfolio_sale_tax", "generated": False, "provider_calls": 0,
                           "clarification": "sale_clause_intent"},
            )

        from app.services.sale_hypothetical import simulate_hypothetical_sale

        res = simulate_hypothetical_sale(db, lots=lots, question=question, company=company)
        trace: dict = {
            "path": "portfolio_sale_tax", "generated": False, "provider_calls": 0,
            "hypothetical": True, "method": "fifo", "ticker": label,
        }
        name = label or "esas acciones"
        intro = f"Estimación hipotética de {name} con los datos que me das, no con tu cartera."
        sources: list[dict] = []
        if res.invalid:
            return ChatResponse(
                answer=f"{intro} {res.invalid}", sources=[], model="deterministic",
                prompt_version=_SALE_TAX_PROMPT_VERSION, confidence=0.8, llm_trace=trace,
            )
        if res.sale_price is None:
            return ChatResponse(
                answer=f"{intro} Me falta {', '.join(res.missing)}: ¿a qué precio las venderías?",
                sources=[], model="deterministic", prompt_version=_SALE_TAX_PROMPT_VERSION,
                confidence=0.8, llm_trace=trace,
            )
        qty_text = _fmt_number_es(float(res.quantity), 4)
        price_text = _price_display(res.sale_price, res.sale_currency)
        sale_text = f"{qty_text} acciones a {price_text}"
        if res.sale_price_source == "cotización" and company is not None:
            sale_text += f" (última cotización guardada, {_fmt_date_es(str(res.sale_price_date))})"
            if res.sale_price_ref is not None:
                sources.append(self._source_entry(
                    "market_price", res.sale_price_ref, f"Cotización {company.ticker}",
                    as_of=str(res.sale_price_date),
                ))
        fifo_lots = res.fifo.lots if res.fifo is not None else []
        lot_texts = [
            f"{_fmt_date_es(lot.trade_date.isoformat() if lot.trade_date else None)}, "
            f"{_fmt_number_es(float(lot.quantity), 4)} acciones a {_price_display(lot.unit_cost_native, lot.currency)}"
            + (
                f", coste {_fmt_money_es(float(lot_cost))} €"
                if (lot_cost := lot.cost_eur_dgt(res.sale_currency, res.sale_rate)) is not None else ""
            )
            for lot in fifo_lots
        ]
        method = (
            "Método FIFO, obligatorio en IRPF (art. 37.2 LIRPF): salen primero las acciones más antiguas. "
            "Lotes vendidos: " + "; ".join(lot_texts) + "."
        )
        if res.undated:
            method += " Sin fechas de compra, tomo los lotes en el orden en que me los das."
        if res.approx_dates:
            method += " Donde solo me das mes y año, tomo el día 1 para el tipo de cambio."
        if res.missing or res.gain_eur is None or res.value_eur is None or res.cost_eur is None:
            answer = f"{intro} Para pasar a euros la venta de {sale_text} me falta {', '.join(res.missing)}."
            if res.native_gain is not None:
                kind = "ganancia" if res.native_gain >= 0 else "pérdida"
                ccy = _currency_display(res.sale_currency)
                answer += f" En {ccy}, sería una {kind} de {_fmt_money_es(float(abs(res.native_gain)))} {ccy}."
            answer += f" Dímelo y te calculo el IRPF. {method}"
            return ChatResponse(
                answer=answer, sources=sources, model="deterministic",
                prompt_version=_SALE_TAX_PROMPT_VERSION, confidence=0.6, llm_trace=trace,
            )
        head = (
            f"{intro} Si vendieras {sale_text}: valor {_fmt_money_es(float(res.value_eur))} €, "
            f"coste {_fmt_money_es(float(res.cost_eur))} €"
        )
        year = date.today().year
        if res.gain_eur > 0 and res.tax_eur is not None:
            rate = res.tax_eur / res.gain_eur * 100
            answer = (
                f"{head}, ganancia de {_fmt_money_es(float(res.gain_eur))} €. "
                f"IRPF estimado: {_fmt_money_es(float(res.tax_eur))} € (un {_fmt_number_es(float(rate), 1)} % "
                f"de la ganancia, {_savings_scale_label(year)}: 19 % hasta 6.000 €, 21 % hasta 50.000 €…). "
                "Lo calculo como si fuera tu única operación del año."
            )
        else:
            answer = (
                f"{head}, pérdida de {_fmt_money_es(float(-res.gain_eur))} €. No pagarías IRPF por esta venta."
            )
        if res.gain_eur < 0:
            if res.fifo is not None and res.fifo.blocking_qty > 0:
                blocked = -res.gain_eur * res.fifo.blocking_qty / res.quantity
                trace["wash_sale_blocked_qty"] = float(res.fifo.blocking_qty)
                answer += (
                    f" Por compras previas que siguen en cartera, {_fmt_money_es(float(blocked))} € "
                    "de la pérdida no se pueden compensar ahora: se aplazan hasta vender esas acciones."
                )
                if res.fifo.blocking_qty < res.quantity:
                    answer += f" El resto, {_fmt_money_es(float(-res.gain_eur - blocked))} €, queda sujeto a las posibles recompras posteriores."
            elif res.undated:
                answer += " Sin las fechas de todas las compras no puedo confirmar si la pérdida se puede compensar por la regla de los dos meses."
            else:
                answer += " La pérdida compensa otras ganancias si no recompras en los dos meses siguientes."
        answer += f" {method} Es una estimación, no asesoría fiscal."
        return ChatResponse(
            answer=answer, sources=sources, model="deterministic",
            prompt_version=_SALE_TAX_PROMPT_VERSION, confidence=0.8, llm_trace=trace,
        )

    def _sale_tax_answer(self, db: Session, company: Company, question: str) -> ChatResponse | None:
        """IRPF estimado si el usuario vendiera hoy su posición guardada en ``company``.

        Determinista y en tuteo. La ganancia es FIFO (art. 37.2 LIRPF): se
        venden primero los lotes más antiguos, con el coste en euros al tipo
        de la fecha de compra. Sin compras individuales guardadas se usa el
        coste medio y se dice. La cuota sale de la escala del ahorro del año en
        curso, como si fuera la única operación del ejercicio. Sin tenant
        devuelve None.
        """
        from app.services.tax_sale_intent import sale_intent_issue

        issue = sale_intent_issue(question)
        if issue:
            return ChatResponse(
                answer=issue, sources=[], model="deterministic",
                prompt_version=_SALE_TAX_PROMPT_VERSION, confidence=0.8,
                llm_trace={"path": "portfolio_sale_tax", "generated": False, "provider_calls": 0,
                           "clarification": "sale_clause_intent"},
            )

        from app.services.sale_simulation import repurchase_deadline, simulate_fifo_sale
        from app.services.tax_irpf_filing import calculate_savings_tax

        tenant_id = db.info.get("tenant_id")
        if type(tenant_id) is not int or tenant_id <= 0:
            return None
        trace: dict = {"path": "portfolio_sale_tax", "generated": False, "provider_calls": 0}
        pos = db.execute(
            select(Position)
            .where(
                Position.quantity > 0,
                Position.tenant_id == tenant_id,
                Position.company_id == company.id,
            )
            .order_by(Position.as_of.desc())
        ).scalars().first()
        if pos is None:
            return self._no_position_sale_answer(company.ticker)
        held = Decimal(pos.quantity)
        from app.services.sale_hypothetical import _sale_quantity, parse_sale_price

        qty = _sale_quantity(question, held)
        issue = None
        if not 0 < qty <= held:
            issue = (
                f"Pides vender {_fmt_number_es(float(qty), 4)} acciones de {company.ticker}, "
                f"pero tienes {_fmt_number_es(float(held), 4)}. Confirma la cantidad; no he calculado otra venta."
            )
        elif re.search(r"(?i)comisi[oó]n|comisiones|gastos|fees?\b", question):
            issue = "Has indicado comisiones o gastos: confirma el importe de venta y su divisa. No he calculado una cuota ignorándolos."
        if issue:
            return ChatResponse(
                answer=issue, sources=[], model="deterministic", prompt_version=_SALE_TAX_PROMPT_VERSION,
                confidence=0.8, llm_trace=trace,
            )
        share = qty / held
        qty_text = _fmt_number_es(float(qty), 4)
        what = (
            f"todas tus {qty_text} acciones de {company.ticker}" if qty == held
            else f"{qty_text} de tus {_fmt_number_es(float(held), 4)} acciones de {company.ticker}"
        )
        source = self._source_entry(
            "position", pos.id, f"Posición {company.ticker}", url="/portfolio", as_of=str(pos.as_of)
        )
        today = date.today()
        fifo = simulate_fifo_sale(
            db, tenant_id=tenant_id, company_id=company.id, quantity=qty, held_quantity=held, sale_date=today,
        )
        value_base = pos.market_value_base if (pos.base_currency or "EUR") == "EUR" else None
        # Criterio del informe fiscal (DGT V0152-26): coste nativo de los lotes
        # al cambio de la VENTA. Sin precio dado, el cambio es el implícito del
        # valor guardado (valor en euros / valor en divisa).
        sale_ccy = (pos.currency or company.currency or "EUR").upper()
        native_value = pos.market_value_native if pos.market_value_native is not None else pos.market_value
        sale_rate: Decimal | None = None
        if sale_ccy == "EUR":
            sale_rate = Decimal("1")
        elif value_base is not None and native_value:
            sale_rate = Decimal(value_base) / Decimal(native_value)
        explicit_sale = parse_sale_price(question)
        if explicit_sale is not None:
            from app.services.portfolio_fx_service import PortfolioFXService
            from app.services.tax_report_service import MAX_FX_AGE_DAYS, _rate_not_older_than

            price, currency = explicit_sale
            currency = currency or pos.currency or company.currency or "EUR"
            fx_table = PortfolioFXService().fx_table(
                db, currencies={currency}, base_currency="EUR", as_of_max=today,
            ) if currency != "EUR" else {}
            rate = _rate_not_older_than(
                fx_table, quote_currency=currency, base_currency="EUR", as_of=today,
                max_age_days=MAX_FX_AGE_DAYS,
            )
            if rate is None:
                return ChatResponse(
                    answer=f"Has indicado un precio de venta en {currency}, pero falta el tipo de cambio de hoy para calcular el IRPF en euros. No he usado el valor guardado de la posición.",
                    sources=[source], model="deterministic", prompt_version=_SALE_TAX_PROMPT_VERSION,
                    confidence=0.7, llm_trace=trace,
                )
            value_base = price * held * rate
            sale_ccy, sale_rate = currency.upper(), rate
            trace["sale_price_source"] = "usuario"
        fifo_cost = fifo.cost_eur_dgt(sale_ccy, sale_rate) if fifo is not None else None
        avg_cost = pos.cost_basis_base if (pos.base_currency or "EUR") == "EUR" else None
        trace["method"] = "fifo" if fifo_cost is not None else "average_cost"
        if value_base is None or (fifo_cost is None and avg_cost is None):
            native_value = pos.market_value_native if pos.market_value_native is not None else pos.market_value
            # average_cost 0 es el default de la columna: coste desconocido.
            avg_known = pos.average_cost is not None and pos.average_cost > 0
            native_cost = (
                pos.cost_basis_native if pos.cost_basis_native is not None
                else (Decimal(pos.average_cost) * held if avg_known else None)
            )
            ccy = _currency_display(pos.currency)
            avg_text = (
                f"a un coste medio de {_fmt_money_es(float(pos.average_cost))} {ccy}"
                if avg_known
                else "sin coste medio guardado"
            )
            answer = (
                f"Tengo tu posición: {_fmt_number_es(float(held), 4)} acciones de {company.ticker} "
                f"{avg_text}. "
                "Pero no puedo estimarte el IRPF en euros: falta "
                + ("el valor actual en euros" if value_base is None and (fifo_cost is not None or avg_cost is not None)
                   else "el coste en euros (tipo de cambio de la fecha de compra)")
                + " de la posición, y Hacienda calcula la ganancia en euros."
            )
            if native_value is not None and native_cost:
                diff = (Decimal(native_value) - Decimal(native_cost)) * share
                kind = "ganancia" if diff >= 0 else "pérdida"
                answer += (
                    f" En {ccy} y a coste medio, vender {what} te daría una {kind} de "
                    f"{_fmt_money_es(float(abs(diff)))} {ccy}."
                )
            answer += " Cuando la cartera tenga el coste en euros, te lo calculo con los tramos del ahorro."
            return ChatResponse(
                answer=answer,
                sources=[source],
                model="deterministic",
                prompt_version=_SALE_TAX_PROMPT_VERSION,
                confidence=0.7,
                llm_trace=trace,
            )
        value = Decimal(value_base) * share
        if fifo is not None and fifo_cost is not None:
            cost = fifo_cost
            lot_texts = [
                f"{_fmt_date_es(lot.trade_date.isoformat() if lot.trade_date else None)}, "
                f"{_fmt_number_es(float(lot.quantity), 4)} acciones, "
                # nosemgrep: gerarai-money-none-to-zero -- lote FIFO ya casado: con fifo_cost conocido cada lote tiene coste; solo es texto
                f"coste {_fmt_money_es(float(lot.cost_eur_dgt(sale_ccy, sale_rate) or 0))} €"
                for lot in fifo.lots
            ]
            method = (
                "Método FIFO, obligatorio en IRPF (art. 37.2 LIRPF): salen primero las acciones más antiguas. "
                "Lotes vendidos: " + "; ".join(lot_texts) + "."
            )
        else:
            # nosemgrep: gerarai-money-none-to-zero -- aqui avg_cost es conocido: la rama de arriba (avg_known/fifo_cost None) ya respondio sin cifra
            cost = Decimal(avg_cost or 0) * share
            method = (
                "Ojo: sin historial de lotes; estimación con coste medio, puede diferir de FIFO. "
                "Hacienda exige FIFO (art. 37.2 LIRPF): registra tus compras en Cartera y te lo calculo por lotes."
            )
        gain = value - cost
        year = today.year
        head = (
            f"Si vendieras hoy {what} (datos a {_fmt_date_es(pos.as_of.isoformat())}): "
            f"valor {_fmt_money_es(float(value))} €, coste {_fmt_money_es(float(cost))} €"
        )
        if explicit_sale is not None:
            head += f" (precio de venta indicado: {_price_display(explicit_sale[0], currency)})"
        scale_label = _savings_scale_label(year)
        if gain > 0:
            tax = calculate_savings_tax(gain, year)
            rate = (tax / gain * 100) if gain else Decimal("0")
            answer = (
                f"{head}, ganancia de {_fmt_money_es(float(gain))} €. "
                f"IRPF estimado: {_fmt_money_es(float(tax))} € (un {_fmt_number_es(float(rate), 1)} % "
                f"de la ganancia, {scale_label}: 19 % hasta 6.000 €, 21 % hasta 50.000 €…). "
                "Lo calculo como si fuera tu única operación del año: si ya tienes otras ganancias, "
                "el tramo sube, y las pérdidas del año lo compensan."
            )
        else:
            loss = -gain
            answer = f"{head}, pérdida de {_fmt_money_es(float(loss))} €. No pagarías IRPF por esta venta."
            deadline = _fmt_date_es(repurchase_deadline(today).isoformat())
            if fifo is not None and fifo_cost is not None and fifo.blocking_qty > 0:
                blocked = loss * fifo.blocking_qty / qty
                dates = ", ".join(_fmt_date_es(d.isoformat()) for d in fifo.blocking_dates)
                trace["wash_sale_blocked_qty"] = float(fifo.blocking_qty)
                answer += (
                    f" Pero ojo con la regla de los dos meses: compraste {company.ticker} el {dates} "
                    f"y esas {_fmt_number_es(float(fifo.blocking_qty), 4)} acciones siguen en cartera tras la venta, "
                    f"así que {_fmt_money_es(float(blocked))} € de la pérdida no se pueden compensar ahora: "
                    "se aplazan hasta que vendas esas acciones."
                )
                if fifo.blocking_qty < qty:
                    answer += (
                        f" El resto, {_fmt_money_es(float(loss - blocked))} €, sí compensa otras ganancias del año."
                    )
            else:
                answer += (
                    " La pérdida compensa otras ganancias del año, siempre que no recompres "
                    f"{company.ticker} antes del {deadline} (regla de los dos meses)."
                )
        answer += f" {method} Es una estimación, no asesoría fiscal; el detalle está en Fiscal."
        return ChatResponse(
            answer=answer,
            sources=[source],
            model="deterministic",
            prompt_version=_SALE_TAX_PROMPT_VERSION,
            confidence=0.8 if fifo_cost is not None else 0.6,
            llm_trace=trace,
        )

    def _deterministic_answer(
        self, db: Session, question: str, scope: str, ticker: str | None
    ) -> ChatResponse:
        company = self._resolve_company(db, question, scope, ticker)
        # El cerebro es SOLO LECTURA: la memoria se recupera, nunca se escribe
        # desde el chat (maybe_write_from_chat quedó retirado).
        retrieved_memory = self.memory.retrieve(db, question, company, scope=scope, limit=6)
        recent_sessions = self._recent_sessions(db, company)

        # Doctrina de la biblioteca (cartas Buffett/Numantia/...): contexto para
        # preguntas generales o de doctrina, NUNCA fuente visible de una ficha de
        # empresa. Antes se recuperaba siempre y la seccion "inferences" citaba
        # cada chunk, asi que una respuesta sobre ASTS salia con "Fuentes:
        # Numantia Patrimonio - Carta 2020" sin relacion alguna con ASTS.
        vector_chat = os.getenv("CAVAAI_ENABLE_VECTOR_CHAT") == "1"
        # Con el vectorial apagado la doctrina llega por texto SQL. En una
        # pregunta general (sin empresa) se busca siempre: exigir palabras como
        # "cartas" o "Buffett" dejaba fuera "¿qué es el margen de seguridad?" o
        # "¿cuánto ha rentado Numantia?" aunque la biblioteca lo tuviera. El
        # umbral lexico (dos terminos juntos, una frase o una entidad) evita
        # traer fragmentos a un "hola".
        library_context = (
            retrieve_library_context(db, question, vector=vector_chat)
            if company is None or _is_doctrine_question(question or "")
            else []
        )
        library_lines = [
            f"- Investment doctrine, not a company fact: {item['text']} "
            f"[knowledge_chunk:{item['id']}]" for item in library_context
        ]
        sources: list[dict] = list(library_context)
        proposed_actions: list[str] = []

        if company:
            thesis = self._latest_thesis(db, company)
            withheld_reason = thesis_withheld_reason(db, thesis) if thesis else None
            sections = [] if withheld_reason else self._sections(db, thesis)
            facts = self._key_facts(db, company)
            claims = self._claims(db, company)
            news = self._recent_news(db, company)
            db_chunks = self._document_chunks(db, company, question)
            rag_chunks = self._rag_chunks(db, question, company)
            # Notas, informes y tesis propias que el usuario subio con este
            # ticker: antes el chat de empresa no las leia nunca.
            seen_library = {item["id"] for item in library_context}
            own_documents = [
                item for item in company_library_context(db, company, question)
                if item["id"] not in seen_library
            ]
            sources.extend(own_documents)
            own_document_lines = [
                f"- Documento propio del usuario sobre {company.ticker} ({item['title']}), "
                f"no es un dato oficial: {' '.join(str(item['text']).split())[:700]} "
                f"[knowledge_chunk:{item['id']}]"
                for item in own_documents
            ]
            evidence_suggestions = list(
                db.scalars(
                    select(EvidenceSuggestion)
                    .where(
                        EvidenceSuggestion.company_id == company.id,
                        EvidenceSuggestion.status == "pending",
                    )
                    .order_by(
                        desc(EvidenceSuggestion.confidence),
                        desc(EvidenceSuggestion.created_at),
                    )
                    .limit(6)
                ).all()
            )

            if thesis:
                sources.append(
                    self._source_entry(
                        "thesis_version",
                        thesis.id,
                        f"Tesis {company.ticker} v{thesis.version}",
                        # El LLM ve este campo y lo copia en la respuesta:
                        # siempre la etiqueta en castellano, nunca el enum.
                        status=_THESIS_STATUS_ES.get(
                            (thesis.status or "").strip(), thesis.status
                        ),
                    )
                )
            for section in sections:
                sources.append(
                    self._source_entry(
                        "thesis_section",
                        section.id,
                        section.title,
                        section_key=section.section_key,
                        confidence=_decimal_to_float(section.confidence),
                    )
                )
            for fact in facts:
                sources.append(
                    self._source_entry(
                        "financial_fact",
                        fact.id,
                        f"{_METRIC_LABELS_ES.get(fact.metric, fact.metric)} "
                        f"({_fmt_period_es(fact.period, fact.fiscal_year, fact.fiscal_quarter)})",
                        metric=fact.metric,
                        value=_decimal_to_float(fact.value),
                        unit=fact.unit,
                        source_type=fact.source_type,
                        source_tier=source_tier_key(fact.source_type),
                        confidence=_decimal_to_float(fact.confidence),
                    )
                )
            for claim in claims:
                sources.append(
                    self._source_entry(
                        "claim",
                        claim.id,
                        _short(claim.statement, 120),
                        status=claim.status,
                        materiality_score=claim.materiality_score,
                        confidence=_decimal_to_float(claim.confidence),
                    )
                )
                for evidence in claim.evidence[:2]:
                    sources.append(
                        self._source_entry(
                            "claim_evidence",
                            evidence.id,
                            _human_evidence_title(evidence.summary),
                            claim_id=claim.id,
                            evidence_type=evidence.evidence_type,
                            document_id=evidence.document_id,
                            document_chunk_id=evidence.document_chunk_id,
                            source_tier=evidence.source_tier,
                            confidence=_decimal_to_float(evidence.confidence),
                        )
                    )
            for chunk, document, passage in db_chunks:
                sources.append(
                    self._source_entry(
                        "document_chunk",
                        chunk.id,
                        document.title,
                        document_id=document.id,
                        source_type=document.source_type,
                        source_tier=source_tier_key(document.source_type),
                        url=document.source_url,
                        # El pasaje que responde (hasta ~900 car.), no los
                        # 240 primeros caracteres del fragmento.
                        text=passage,
                    )
                )
            for chunk in rag_chunks:
                sources.append(
                    self._source_entry(
                        "rag_chunk",
                        chunk.get("point_id"),
                        chunk.get("title") or "Fragmento de documento indexado",
                        document_id=chunk.get("document_id"),
                        knowledge_document_id=chunk.get("knowledge_document_id"),
                        collection_id=chunk.get("collection_id"),
                        page_number=chunk.get("page_number"),
                        chunk_index=chunk.get("chunk_index"),
                        entity_id=chunk.get("entity_id"),
                        source_type=chunk.get("source_type"),
                        source_tier=source_tier_key(chunk.get("source_type")),
                        score=chunk.get("score"),
                        url=chunk.get("url"),
                        text=_short(chunk.get("text", ""), 240),
                    )
                )
            latest_price = db.scalars(
                select(MarketPrice)
                .where(MarketPrice.company_id == company.id)
                .where(MarketPrice.date <= date.today())
                .order_by(desc(MarketPrice.date))
                .limit(1)
            ).first()
            price_line: str | None = None
            if latest_price is not None:
                # adj_close NULL = spot sin ajustar por splits/dividendos
                # (p. ej. intraday): se distingue de cierre diario y se
                # declara el proveedor. Fechas futuras excluidas: una barra
                # de manana no es cotizacion actual.
                adjusted = latest_price.adj_close is not None
                value = latest_price.adj_close if adjusted else latest_price.close
                kind = "cierre ajustado" if adjusted else "spot"
                price_line = (
                    f"{company.ticker} cotiza a "
                    f"{_price_display(value, company.currency)} "
                    f"({kind} del {_fmt_date_es(latest_price.date.isoformat())}, "
                    f"fuente {latest_price.source})."
                )
                sources.append(
                    self._source_entry(
                        "market_price",
                        latest_price.id,
                        f"{company.ticker} {_price_display(value, company.currency)} ({kind} {latest_price.date.isoformat()}, {latest_price.source})",
                        date=latest_price.date.isoformat(),
                        price=str(value),
                        currency=company.currency,
                        adjusted=adjusted,
                    )
                )
            market_cap_fact = db.scalars(
                select(FinancialFact)
                .where(
                    FinancialFact.company_id == company.id,
                    FinancialFact.metric == "market_cap",
                )
                .order_by(
                    FinancialFact.fiscal_year.desc().nullslast(),
                    desc(FinancialFact.created_at),
                    desc(FinancialFact.id),
                )
                .limit(1)
            ).first()
            if market_cap_fact is not None:
                sources.append(
                    self._source_entry(
                        "financial_fact",
                        market_cap_fact.id,
                        f"{_METRIC_LABELS_ES['market_cap']} {market_cap_fact.period}",
                        metric=market_cap_fact.metric,
                        value=_decimal_to_float(market_cap_fact.value),
                        unit=market_cap_fact.unit,
                        source_type=market_cap_fact.source_type,
                        source_tier=source_tier_key(market_cap_fact.source_type),
                        confidence=_decimal_to_float(market_cap_fact.confidence),
                    )
                )
            for event in news:
                sources.append(
                    self._source_entry(
                        "news_event",
                        event.id,
                        event.title,
                        event_type=event.event_type,
                        materiality_score=event.materiality_score,
                        impact_direction=event.impact_direction,
                        requires_update=event.requires_update,
                    )
                )

            for retrieved in retrieved_memory:
                sources.append(
                    self._source_entry(
                        "memory_item",
                        retrieved.item.id,
                        _short(retrieved.item.content, 140),
                        memory_type=retrieved.item.memory_type,
                        importance=retrieved.item.importance,
                        score=retrieved.score,
                        reason=retrieved.reason,
                    )
                )
            if not thesis:
                proposed_actions.append(f"Crear la primera tesis para {company.ticker}")
            if any(claim.status in {"unverified", "contradicted"} for claim in claims):
                proposed_actions.append("Revisar afirmaciones no verificadas o contradichas")
            if any(event.requires_update for event in news):
                proposed_actions.append("Revisar cambios de tesis por noticias materiales")
            if not facts:
                proposed_actions.append(
                    "Ingerir hechos financieros SEC/FMP antes de sacar conclusiones cuantitativas"
                    if files_with_sec(company)
                    else f"Ingerir hechos financieros de FMP o de los informes de {company.ticker} "
                    "(la SEC no cubre ese mercado) antes de sacar conclusiones cuantitativas"
                )

            facts_text = (
                "\n".join(
                    f"- {fact.metric}: {_decimal_to_float(fact.value)} {fact.unit} "
                    f"({fact.period}, {source_tier_key(fact.source_type)}) "
                    f"[financial_fact:{fact.id}]"
                    for fact in facts[:5]
                )
                or "- No hay hechos financieros fiables almacenados para esta empresa."
            )
            calculations_text = (
                "- No se ha hecho un calculo nuevo en esta respuesta; los hechos almacenados se citan como entradas."
                if facts
                else "- Calculo bloqueado: faltan hechos financieros almacenados."
            )
            assumptions_text = (
                "\n".join(
                    f"- {_short(item.item.content, 180)} "
                    f"[memory_item:{item.item.id}]"
                    for item in retrieved_memory[:3]
                )
                or "- No se recupero memoria relevante del usuario."
            )
            claim_lines = [
                f"- [{claim.status}] {_short(claim.statement, 180)} "
                f"[claim:{claim.id}]"
                for claim in claims[:5]
                if claim.status != "supported"
            ]
            unverified_text = "\n".join(claim_lines) or "- No hay afirmaciones sin resolver en el contexto recuperado."
            thesis_text = (
                f"{archived_thesis_notice(thesis, withheld_reason)} "
                f"[thesis_version:{thesis.id}]"
                if thesis and withheld_reason
                else f"Tesis {company.ticker} v{thesis.version}: `{thesis.status}` con rating `{thesis.rating}`. "
                f"Valor esperado={_decimal_to_float(thesis.expected_value)} frente a precio actual={_decimal_to_float(thesis.current_price)}. "
                f"[thesis_version:{thesis.id}]"
                if thesis
                else f"Aun no hay tesis almacenada para {company.ticker}."
            )
            rag_evidence_lines = [
                f"- {_short(chunk.get('text', ''), 180)} "
                f"({chunk.get('source_type') or 'indexed'}) "
                f"[rag_chunk:{chunk.get('point_id')}]"
                for chunk in rag_chunks[:3]
                if chunk.get("point_id") and chunk.get("text")
            ] + library_lines
            db_evidence_lines = [
                f"- {_short(passage, 180)} ({document.source_type}) "
                f"[document_chunk:{chunk.id}]"
                for chunk, document, passage in db_chunks[:3]
            ]
            news_lines = [
                f"- {event.title} [{event.impact_direction}, materiality {event.materiality_score}] "
                f"[news_event:{event.id}]"
                for event in news[:3]
            ]
            contradiction_claims = [
                claim
                for claim in claims
                if claim.status in {"contradicted", "superseded", "stale"}
            ]
            contradictions_text = (
                "\n".join(
                    f"- [{claim.status}] {_short(claim.statement, 180)} "
                    f"[claim:{claim.id}]"
                    for claim in contradiction_claims
                )
                or "- No se encontraron contradicciones en las afirmaciones recuperadas."
            )
            found_metrics = {fact.metric for fact in facts}
            missing_metrics = [
                metric for metric in KEY_FACT_METRICS if metric not in found_metrics
            ]
            insufficient_text = (
                f"- Faltan entradas almacenadas: {', '.join(missing_metrics)}."
                if missing_metrics
                else "- No falta ninguna entrada financiera clave en esta recuperacion."
            )
            conclusion_text = (
                "- Hay que revisar la tesis antes de cambiar supuestos."
                if contradiction_claims
                or any(event.requires_update for event in news)
                else "- La evidencia recuperada no exige un cambio automatico de tesis; seguir monitorizando."
            )

            # La respuesta VISIBLE es prosa natural en castellano (pedido de
            # Nico 2026-10-17: "que sea lectura natural y en castellano"). El
            # volcado estructurado con citas no desaparece: sigue en
            # `sections`, que el frontend muestra plegado, y es el contexto
            # que verifica la sintesis LLM.
            answer = _natural_company_answer(
                company=company,
                facts=facts,
                thesis=thesis,
                news=news,
                missing_metrics=missing_metrics,
                claims=claims,
                contradiction_claims=contradiction_claims,
                price_line=price_line,
                memory_notes=[item.item.content for item in retrieved_memory[:3]],
                market_cap_fact=market_cap_fact,
                question=question,
                thesis_withheld=withheld_reason,
            )

            sections = [
                {
                    "key": "facts",
                    "body": "\n".join([facts_text, *news_lines]),
                    "citations": [
                        *(f"financial_fact:{fact.id}" for fact in facts[:5]),
                        *([f"financial_fact:{market_cap_fact.id}"] if market_cap_fact is not None else []),
                    ],
                },
                {
                    "key": "calculations",
                    "body": calculations_text,
                    "citations": [
                        f"financial_fact:{fact.id}" for fact in facts[:5]
                    ],
                },
                {
                    "key": "user_hypotheses",
                    "body": assumptions_text,
                    "citations": [
                        f"memory_item:{item.item.id}"
                        for item in retrieved_memory[:3]
                    ],
                },
                {
                    "key": "unverified_claims",
                    "body": unverified_text,
                    "citations": [
                        f"claim:{claim.id}"
                        for claim in claims[:5]
                        if claim.status != "supported"
                    ],
                },
                {
                    "key": "inferences",
                    "body": "\n".join(
                        [thesis_text, *db_evidence_lines, *rag_evidence_lines, *own_document_lines]
                    )
                    if (rag_evidence_lines or db_evidence_lines or own_document_lines)
                    else thesis_text,
                    "citations": [
                        *([f"thesis_version:{thesis.id}"] if thesis else []),
                        *[f"knowledge_chunk:{item['id']}" for item in library_context],
                        *[f"knowledge_chunk:{item['id']}" for item in own_documents],
                        *[
                            f"rag_chunk:{chunk.get('point_id')}"
                            for chunk in rag_chunks[:3]
                            if chunk.get("point_id") and chunk.get("text")
                        ],
                    ],
                },
                {
                    "key": "contradictions",
                    "body": contradictions_text,
                    "citations": [
                        f"claim:{claim.id}" for claim in contradiction_claims
                    ],
                },
                {
                    "key": "insufficient_data",
                    "body": insufficient_text,
                    "citations": [],
                },
                {
                    "key": "conclusion",
                    "body": conclusion_text,
                    "citations": [
                        *[
                            f"claim:{claim.id}"
                            for claim in contradiction_claims
                        ],
                        *[
                            f"news_event:{event.id}"
                            for event in news
                            if event.requires_update
                        ],
                    ],
                },
            ]

            sources = _prune_sources(sources, sections, answer)
            return ChatResponse(
                answer=answer,
                sections=sections,
                sources=sources,
                blocked=not thesis or not sources,
                proposed_actions=list(dict.fromkeys(proposed_actions)),
                evidence_suggestions=[
                    {
                        "id": suggestion.id,
                        "statement": suggestion.statement,
                        "relation": suggestion.relation,
                        "suggestion_type": suggestion.suggestion_type,
                        "confidence": float(suggestion.confidence),
                        "suggested_claim_id": suggestion.suggested_claim_id,
                        "document_chunk_id": suggestion.document_chunk_id,
                    }
                    for suggestion in evidence_suggestions
                ],
                prompt_version="source-aware-synthesis-v1",
                model="deterministic",
            )

        portfolio_memories = [retrieved.item for retrieved in retrieved_memory]
        for item in portfolio_memories:
            sources.append(
                self._source_entry(
                    "memory_item",
                    item.id,
                    _short(item.content, 140),
                    memory_type=item.memory_type,
                    importance=item.importance,
                )
            )
        for session in recent_sessions:
            sources.append(
                self._source_entry(
                    "research_session",
                    session.id,
                    session.title,
                    status=session.status,
                    summary=_short(session.summary, 180),
                )
            )

        answer = (
            "CONTEXTO\n- Pregunta general sin ticker: el asistente dispone de memorias de cartera, sesiones de research y contexto documental.\n\n"
            "SIN CALCULOS\n- Sin ticker no hay calculos de cartera en esta respuesta.\n\n"
            "MEMORIAS\n"
            f"{chr(10).join(f'- {_short(item.content, 180)}' for item in portfolio_memories[:5]) or '- No se recuperó memoria de cartera relevante.'}\n\n"
            "SIN AFIRMACIONES DE EMPRESA\n- Pregunta por un ticker concreto para revisar afirmaciones y evidencia.\n\n"
            "CONTEXTO DOCUMENTAL\n"
            + ("\n".join(library_lines) or "- Para respuestas con fuentes de empresa, indica un ticker o ingiere evidencia primero.")
        )
        return ChatResponse(
            answer=answer,
            sections=[
                {
                    "key": "facts",
                    "body": "Solo contexto de memorias de cartera y sesiones de research.",
                    "citations": [
                        f"memory_item:{item.id}"
                        for item in portfolio_memories[:5]
                    ],
                },
                {
                    "key": "calculations",
                    "body": "No se hizo ningún cálculo de cartera.",
                    "citations": [],
                },
                {
                    "key": "user_hypotheses",
                    "body": "Memorias de cartera recuperadas.",
                    "citations": [
                        f"memory_item:{item.id}"
                        for item in portfolio_memories[:5]
                    ],
                },
                {
                    "key": "unverified_claims",
                    "body": "Pregunta por un ticker concreto para revisar afirmaciones y evidencia.",
                    "citations": [],
                },
                {
                    "key": "inferences",
                    "body": "\n".join(library_lines) or "Hace falta un ticker para inferencias de empresa.",
                    "citations": [f"knowledge_chunk:{item['id']}" for item in library_context],
                },
                {
                    "key": "contradictions",
                    "body": "No se seleccionaron afirmaciones de empresa.",
                    "citations": [],
                },
                {
                    "key": "insufficient_data",
                    "body": "Indica un ticker o ingiere evidencia de cartera.",
                    "citations": [],
                },
                {
                    "key": "conclusion",
                    "body": "No hay conclusión de empresa disponible.",
                    "citations": [],
                },
            ],
            sources=sources,
            blocked=False,
            proposed_actions=["Pregunta por un ticker", "Ingiere documentos de cartera"],
            prompt_version="source-aware-synthesis-v1",
            model="deterministic",
        )
