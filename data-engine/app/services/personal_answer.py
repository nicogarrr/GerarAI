"""Preguntas sobre TUS datos («¿qué riesgo tengo?», «¿qué está barato?»).

Prueba real 2026-10-27, antes de este módulo:

* «¿qué está barato de mi watchlist?» → «no tengo acceso a tu watchlist»;
* «¿qué riesgo tengo?» → preguntaba si era riesgo personal o de salud;
* «¿cómo va mi cartera?» sin posiciones → «Selecciona la empresa o su
  ticker» en 0,1 s.

Aquí se detecta la intención personal (barato, watchlist, riesgo, cartera,
tesis, plan, fiscal) y se responde con ``build_user_context``:

1. Con LLM: el modelo recibe SOLO el contexto del usuario y la pregunta.
   La respuesta pasa una comprobación de anclaje: cada cifra tiene que estar
   en el contexto (misma cifra, con tolerancia de redondeo) y cada ticker
   también. Si algo no cuadra, no se muestra.
2. Sin LLM, con el LLM caído o con una respuesta no anclada: respuesta
   determinista construida con las mismas líneas del contexto.

Ninguna rama inventa: lo que no está en GerarAI se dice («sin valor justo»,
«aún sin ficha»).
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.schemas import ChatResponse
from app.services.user_context import UserContext, build_user_context, pct_es

PROMPT_VERSION = "personal-context-v1"
MAX_ANSWER_CHARS = 1600


@dataclass(frozen=True)
class PersonalIntent:
    kind: str
    sections: tuple[str, ...]


_INTENT_SECTIONS: dict[str, tuple[str, ...]] = {
    "fiscal": ("fiscal",),
    "barato": ("watchlist", "cartera", "tesis", "avisos", "diario", "plan"),
    "watchlist": ("watchlist", "tesis"),
    "riesgo": ("cartera", "tesis", "avisos", "watchlist"),
    "plan": ("plan", "cartera", "watchlist"),
    "tesis": ("tesis", "diario"),
    "cartera": ("cartera", "tesis", "avisos"),
    "general": ("cartera", "watchlist", "tesis", "avisos", "diario", "plan"),
}


def _fold(text: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", (text or "").lower()) if unicodedata.category(c) != "Mn"
    )


# Sobre el texto sin tildes y en minúsculas.
_PERSONAL = re.compile(r"\b(?:mi|mis|me|tengo|tenga|corro|estoy|voy|llevo|my|i have)\b")
_IMPERATIVE_ORDER = re.compile(r"^\W*(?:compra|vende|ejecuta|buy|sell|vender|comprar)\b")
_CONCEPT = re.compile(r"\b(?:que es|que son|que significa|como se calcula|en que consiste|define|explica(?:me)?)\b")
_FISCAL = re.compile(
    r"\b(?:fiscal\w*|impuestos?|hacienda|irpf|renta \d{4}|declaracion de la renta|modelo 720|plusvalias?|"
    r"retencion(?:es)?|base del ahorro|(?:ganancias?|perdidas?)(?: y (?:ganancias?|perdidas?))? patrimonial(?:es)?)\b"
)
# «¿Cuánto IRPF pagaré este año?», «¿qué impuestos pago?»: el verbo en primera
# persona ya hace la pregunta personal aunque no haya «mi» ni «me».
_FISCAL_SELF_VERB = re.compile(r"\b(?:pagare|pague|pago|pagamos|he pagado|declarare|declaro)\b")
# «¿Cuánto he ganado en 2025?»: con un ejercicio concreto es la ganancia
# realizada de ese año (bloque fiscal), no la rentabilidad acumulada de hoy.
_YEAR_GAIN = re.compile(r"\b(?:(?:he|hemos)\s+(?:ganado|perdido)|gane|perdi)\b")
_GAIN_YEAR = re.compile(r"\b(?:20\d{2}|(?:el )?(?:ano|ejercicio) pasado)\b")
_CHEAP = re.compile(
    r"\b(?:barat\w*|infravalorad\w*|margen de seguridad|descuento|oportunidad\w*|chollo\w*|"
    r"zona de compra|niveles? dca|[1-4]x|que (?:compro|debo comprar|deberia comprar|comprar|me compro)|"
    r"donde (?:meto|invierto|pongo|aporto)|cheap|undervalued)\b"
)
_WATCHLIST = re.compile(r"\b(?:watch\s?-?list|lista de seguimiento|seguimiento|(?:valores|empresas|acciones) que sigo)\b")
_RISK = re.compile(
    r"\b(?:riesgos?|arriesgad\w*|expuest\w*|exposicion|concentrad\w*|concentracion|vulnerab\w*|"
    r"me preocupa\w*|drawdown|risk\w*)\b"
)
_PLAN = re.compile(r"\b(?:aportacion\w*|aportar|plan de inversion|mi plan|cuanto (?:aporto|invierto|meto))\b")
_THESES = re.compile(r"\b(?:mis tesis|tesis (?:activas|abiertas|vigentes)|invalidacion|invalida\w*)\b")
_PORTFOLIO = re.compile(
    r"\b(?:cartera|mis (?:posiciones|acciones|inversiones|holdings)|como voy|portfolio|p&l)\b"
)
_GENERAL = re.compile(r"\b(?:que sabes de mi|mis datos|que tengo|resumen de lo mio)\b")


def detect_personal_intent(question: str) -> PersonalIntent | None:
    """Intención sobre los datos propios, o None si la pregunta no es personal."""
    text = _fold(question)
    if not text.strip() or _IMPERATIVE_ORDER.search(text):
        return None
    personal = bool(_PERSONAL.search(text))
    concept = bool(_CONCEPT.search(text))
    kind: str | None = None
    fiscal = bool(_FISCAL.search(text)) and (personal or "resumen" in text or bool(_FISCAL_SELF_VERB.search(text)))
    year_gain = bool(_YEAR_GAIN.search(text) and _GAIN_YEAR.search(text)) and not concept
    if fiscal or year_gain:
        kind = "fiscal"
    elif _CHEAP.search(text) and not concept:
        kind = "barato"
    elif _WATCHLIST.search(text) and not concept:
        kind = "watchlist"
    elif _RISK.search(text) and (personal or _PORTFOLIO.search(text)) and not concept:
        kind = "riesgo"
    elif _PLAN.search(text) and not concept:
        kind = "plan"
    elif _THESES.search(text) and personal:
        kind = "tesis"
    elif _PORTFOLIO.search(text) and (personal or "la cartera" in text) and not concept:
        kind = "cartera"
    elif _GENERAL.search(text):
        kind = "general"
    if kind is None:
        return None
    return PersonalIntent(kind=kind, sections=_INTENT_SECTIONS[kind])


# ------------------------------------------------------------- anclaje

_NUMBER_RE = re.compile(r"(?<![\w.,])[-+−]?\d{1,3}(?:\.\d{3})+(?:,\d+)?|(?<![\w.,])[-+−]?\d+(?:[.,]\d+)?")
_TICKER_RE = re.compile(r"\b[A-Z][A-Z0-9]{1,5}(?:\.[A-Z]{1,2})?\b")


def _parse_number(raw: str) -> float | None:
    token = raw.replace("−", "-").lstrip("+")
    if re.fullmatch(r"-?\d{1,3}(?:\.\d{3})+(?:,\d+)?", token):
        token = token.replace(".", "").replace(",", ".")
    else:
        token = token.replace(",", ".")
    try:
        return float(token)
    except ValueError:
        return None


_UNIT_AFTER_RE = re.compile(r"\s*(?:%|€|\$|eur\b|usd\b|gbp\b|gbx\b|pp\b|puntos\b)", re.IGNORECASE)


def _numbers_with_unit(text: str) -> list[tuple[float, bool]]:
    out = []
    for match in _NUMBER_RE.finditer(text or ""):
        value = _parse_number(match.group(0))
        if value is not None:
            out.append((value, bool(_UNIT_AFTER_RE.match(text, match.end()))))
    return out


def numbers_in(text: str) -> list[float]:
    return [value for value, _ in _numbers_with_unit(text)]


def _trivial(value: float, has_unit: bool) -> bool:
    """Recuentos, días y años sin unidad: no son cifras que haya que anclar.

    Un número con % o divisa detrás («26 %», «12 EUR») siempre se ancla.
    """
    if has_unit or value != int(value):
        return False
    magnitude = abs(int(value))
    return magnitude <= 31 or 1990 <= magnitude <= 2100


def ungrounded_numbers(answer: str, context_text: str) -> list[float]:
    allowed = [abs(v) for v in numbers_in(context_text)]
    missing = []
    for value, has_unit in _numbers_with_unit(answer):
        if _trivial(value, has_unit):
            continue
        target = abs(value)
        if not any(abs(target - c) <= max(0.011, 0.005 * c) for c in allowed):
            missing.append(value)
    return missing


def ungrounded_tickers(answer: str, context_text: str) -> list[str]:
    return sorted({t for t in _TICKER_RE.findall(answer or "") if t not in context_text})


# ------------------------------------------------------------- determinista


def _block_lines(ctx: UserContext, key: str, limit: int = 40) -> list[str]:
    block = ctx.block(key)
    return list(block.lines[:limit]) if block else []


def _dca_word(level: int | None) -> str:
    if level is None:
        return ""
    if level < 0:
        return " (zona de recorte)" if level == -1 else " (recorte fuerte)"
    return f" ({level}X DCA)"


def _cheap_answer(ctx: UserContext) -> list[str]:
    watch = ctx.block("watchlist")
    rows = watch.rows if watch else []
    held = ctx.block("cartera")
    held_rows = held.rows if held else []
    cheap = sorted((r for r in rows if r.get("mos") is not None and r["mos"] > 0), key=lambda r: r["mos"], reverse=True)
    pricey = sorted((r for r in rows if r.get("mos") is not None and r["mos"] <= 0), key=lambda r: r["mos"])
    dca_buy = [r for r in [*rows, *held_rows] if (r.get("dca_level") or 0) >= 3 and r.get("mos") is None]
    lines = []
    if cheap:
        lines.append("Lo más barato de tu watchlist por margen de seguridad (V − P) / V (watchlist):")
        lines += [f"- {r['ticker']}: {pct_es(r['mos'], signed=True)}{_dca_word(r.get('dca_level'))}." for r in cheap[:6]]
    else:
        lines.append("No hay margen positivo calculable entre los datos guardados; si falta precio o valor justo no puedo clasificar ese valor.")
    if dca_buy:
        lines.append(
            "En zona de compra fuerte por DCA pero sin valor justo para medir el margen: "
            + ", ".join(f"{r['ticker']}{_dca_word(r.get('dca_level'))}" for r in dca_buy[:6]) + "."
        )
    if pricey:
        lines.append(
            "Por encima de su valor justo: "
            + ", ".join(f"{r['ticker']} {pct_es(r['mos'], signed=True)}{_dca_word(r.get('dca_level'))}" for r in pricey[:4])
            + "."
        )
    missing = [r["ticker"] for r in rows if r.get("fair_value") is None]
    if missing:
        lines.append(
            f"Sin valor justo (ni tesis publicada ni motor), no puedo decir si están baratos: {', '.join(missing[:12])}."
        )
    trims = [r for r in held_rows if (r.get("dca_level") or 0) < 0]
    if trims:
        lines.append("En cartera, en zona de recorte (no reciben dinero nuevo): " + ", ".join(
            f"{r['ticker']}{_dca_word(r.get('dca_level'))}" for r in trims) + ".")
    return lines


def _risk_answer(ctx: UserContext, db: Session) -> list[str]:
    lines: list[str] = []
    held = ctx.block("cartera")
    rows = held.rows if held else []
    weighted = [r for r in rows if r.get("weight") is not None]
    if not rows:
        lines.append("No tienes posiciones guardadas en la cartera, así que no hay riesgo de cartera que medir.")
    elif weighted:
        top = weighted[0]
        top3 = sum(r["weight"] for r in weighted[:3])
        lines.append(
            f"Concentración (cartera): {top['ticker']} pesa {pct_es(top['weight'])} y las 3 mayores suman {pct_es(top3)}."
        )
        sector_line = next((line for line in held.lines if line.startswith("- Peso por sector")), None) if held else None
        if sector_line:
            lines.append(sector_line.removeprefix("- "))
        losers = [r for r in rows if r.get("pnl_pct") is not None and r["pnl_pct"] < 0]
        if losers:
            losers.sort(key=lambda r: r["pnl_pct"])
            lines.append("En pérdidas latentes: " + ", ".join(
                f"{r['ticker']} {pct_es(r['pnl_pct'], signed=True)}" for r in losers[:5]) + ".")
        trims = [r for r in rows if (r.get("dca_level") or 0) < 0]
        if trims:
            lines.append("En zona de recorte por DCA: " + ", ".join(
                f"{r['ticker']}{_dca_word(r.get('dca_level'))}" for r in trims) + ".")
    else:
        lines.append("Tus posiciones tienen divisas base mezcladas: no calculo pesos ni concentración.")
    theses = ctx.block("tesis")
    held_tickers = {r["ticker"] for r in rows}
    criteria = [r for r in (theses.rows if theses else []) if r["ticker"] in held_tickers and r.get("criteria")]
    for row in criteria[:4]:
        lines.append(f"Tu tesis de {row['ticker']} se invalida si: {row['criteria'][0]}")
    alerts = _block_lines(ctx, "avisos", 4)
    if alerts:
        lines.append("Avisos: " + alerts[0].removeprefix("- "))
        lines += alerts[1:4]
    # Panel de riesgo y histórico (#2317), si esa pieza está disponible.
    # nosemgrep: gerarai-broad-except-pass -- pieza opcional; sin ella la respuesta sigue (comentario en linea)
    try:
        from importlib import import_module

        tools = import_module("app.services.brain_context_tools")
        risk_lines, _ = tools.portfolio_risk_lines(db, ctx.tenant_id)
        lines += [line if line.startswith("- ") else f"- {line}" for line in risk_lines[:4]]
    except Exception:  # noqa: BLE001 - pieza opcional; sin ella sigue la respuesta
        pass
    return lines


def deterministic_lines(intent: PersonalIntent, ctx: UserContext, db: Session) -> list[str]:
    if intent.kind == "barato":
        lines = ["Lecturas guardadas, no cotizaciones en directo ni órdenes de compra."]
        # Keep the plan and risk notices ahead of the bounded candidates, so
        # fallback truncation cannot silently drop investment constraints.
        for section, maximum in (("plan", 2), ("avisos", 2)):
            lines.extend(_block_lines(ctx, section, maximum))
        seen: set[str] = set()
        for block in (ctx.block("cartera"), ctx.block("watchlist")):
            if block:
                for row in block.rows:
                    symbol = row["ticker"]
                    if symbol in seen or (row.get("dca_level") or 0) < 3:
                        continue
                    dated = next((line for line in block.lines if line.startswith(f"- {symbol} (") and "nivel DCA" in line), None)
                    if dated:
                        seen.add(symbol)
                        lines.append(dated)
        lines.extend(_cheap_answer(ctx))
        return lines
    if intent.kind == "riesgo":
        return _risk_answer(ctx, db)
    if intent.kind == "cartera":
        lines = _block_lines(ctx, "cartera", 12)
        if lines == ["- Sin posiciones guardadas."]:
            return [
                "No tienes posiciones guardadas en la cartera (/portfolio). Importa el CSV de IBKR o añade "
                "las posiciones y te digo cómo va, con peso, P&L y nivel DCA de cada una."
            ]
        return ["Tu cartera (/portfolio):", *lines]
    key = {"watchlist": "watchlist", "plan": "plan", "tesis": "tesis", "fiscal": "fiscal"}.get(intent.kind)
    if key:
        return [f"Tus datos de {key} en GerarAI:", *_block_lines(ctx, key)]
    out = ["Lo que GerarAI tiene guardado de ti:"]
    for section in intent.sections:
        out += _block_lines(ctx, section, 6)
    return out


# ------------------------------------------------------------- LLM

CHAT_PERSONAL = (
    "You are GerarAI's Cerebro answering a question about the user's OWN data. "
    "The user message is JSON with `question` and `user_data`: a snapshot of the user's portfolio, watchlist, "
    "theses, alerts, decision journal and plan taken from GerarAI's database, in blocks titled with the page "
    "each comes from. `user_data` is the ONLY valid source. Rules: "
    "1) Answer in natural Castilian Spanish (es-ES number format), under 900 characters, no markdown tables, "
    "addressing the user with 'tú' (tienes, tu cartera), never 'usted'. "
    "2) Every number you write must appear in user_data exactly as written there; never compute, round, "
    "estimate or recall a new figure, never use outside knowledge about prices or companies. "
    "3) Never mention a ticker that is not in user_data. "
    "4) Say which page a figure comes from in plain words, e.g. «(watchlist)», «(cartera)», «(tesis de KKR)». "
    "5) If user_data lacks what is asked (no fair value, no price, no DCA level), say exactly that and which "
    "page fills it; do not guess. "
    "6) 'Barato' means a positive margin of safety and/or a 3X-4X DCA level; 'caro' means a negative margin or "
    "a trim zone (RECORTE). Risk means concentration, losses, trim zones, invalidation criteria and open alerts. "
    "7) No buy or sell orders and no personalised advice: describe what the data shows."
)


def _response(
    answer: str, ctx: UserContext, intent: PersonalIntent, *, model: str, trace: dict, confidence: float
) -> ChatResponse:
    return ChatResponse(
        answer=answer[:MAX_ANSWER_CHARS],
        sources=ctx.sources[:20],
        model=model,
        prompt_version=PROMPT_VERSION,
        confidence=confidence,
        llm_trace={"path": "personal_context", "intent": intent.kind, "sections": list(intent.sections), **trace},
    )


_YEAR_RE = re.compile(r"\b(20\d{2})\b")
_THIS_YEAR_RE = re.compile(r"(?i)\b(?:este|esta|en\s+lo\s+que\s+va\s+de)\s+(?:a[nñ]o|ejercicio)\b")
_LAST_YEAR_RE = re.compile(r"(?i)\b(?:el\s+)?(?:a[nñ]o|ejercicio)\s+pasado\b")


def _fiscal_year_in(question: str) -> int | None:
    """Ejercicio que pide la pregunta («este año», «2024», «el año pasado»).

    Sin año explícito, None: el contexto usa el último ejercicio cerrado.
    Antes «¿mi plusvalía realizada este año?» respondía con el anterior.
    """
    from app.core.local_date import local_today

    explicit = _YEAR_RE.search(question or "")
    if explicit:
        return int(explicit.group(1))
    if _THIS_YEAR_RE.search(question or ""):
        return local_today().year
    if _LAST_YEAR_RE.search(question or ""):
        return local_today().year - 1
    return None


async def answer_personal_question(
    db: Session,
    question: str,
    intent: PersonalIntent,
    provider: Any | None,
    *,
    history_text: str | None = None,
    use_llm: bool = True,
    dca_reader: Any | None = None,
) -> ChatResponse | None:
    """Respuesta anclada a los datos del usuario; None si no hay tenant."""
    ctx = build_user_context(
        db,
        sections=intent.sections,
        dca_reader=dca_reader,
        fiscal_year=_fiscal_year_in(question) if intent.kind == "fiscal" else None,
    )
    if ctx is None:
        return None
    context_text = ctx.render()
    fallback = "\n".join(deterministic_lines(intent, ctx, db))
    base_trace: dict[str, Any] = {"context_chars": len(context_text), "context_truncated": ctx.truncated}
    if not use_llm or provider is None:
        return _response(fallback, ctx, intent, model="deterministic",
                         trace={**base_trace, "generated": False, "provider_calls": 0}, confidence=0.85)

    from app.llm import LLMRequest, Message
    from app.services.budget import BudgetController

    budget = BudgetController()
    try:
        if not budget.can_spend(db, 0.02):
            return _response(fallback, ctx, intent, model="deterministic",
                             trace={**base_trace, "fallback": True, "fallback_reason": "budget_exhausted",
                                    "provider_calls": 0}, confidence=0.8)
    except Exception:  # noqa: BLE001 - sin tabla de presupuesto, se responde sin LLM
        db.rollback()
        return _response(fallback, ctx, intent, model="deterministic",
                         trace={**base_trace, "fallback": True, "fallback_reason": "budget_unavailable",
                                "provider_calls": 0}, confidence=0.8)
    request = LLMRequest(
        messages=[
            Message("system", CHAT_PERSONAL),
            Message("user", json.dumps(
                {"question": question, "intent": intent.kind, "user_data": context_text,
                 "conversation": history_text or None},
                ensure_ascii=False,
            )),
        ],
        task="chat",
        temperature=0.2,
        max_tokens=500,
    )
    try:
        from app.llm.interactive_deadline import complete_with_deadline

        guarded = await complete_with_deadline(provider, request, source="chat_personal", english="strict")
        resp = guarded.response
        try:
            cost = budget.estimate_cost_eur(getattr(resp, "model", None) or "unknown",
                                            resp.usage.input_tokens, resp.usage.output_tokens)
            budget.record(db, getattr(resp, "model", None) or "unknown", "chat_personal", cost, resp.usage.total_tokens)
        except Exception:  # noqa: BLE001 - registrar coste nunca rompe la respuesta
            db.rollback()
        text = (resp.text or "").strip()
    except Exception as exc:  # noqa: BLE001 - proveedor caído o guard agotado
        return _response(fallback, ctx, intent, model="deterministic",
                         trace={**base_trace, "fallback": True, "fallback_reason": "provider_or_guard_failure",
                                "error": type(exc).__name__, "provider_calls": 1}, confidence=0.8)
    bad_numbers = ungrounded_numbers(text, context_text)
    bad_tickers = ungrounded_tickers(text, context_text)
    if not text or bad_numbers or bad_tickers:
        return _response(fallback, ctx, intent, model="deterministic",
                         trace={**base_trace, "fallback": True,
                                "fallback_reason": "ungrounded" if text else "empty",
                                "ungrounded_numbers": bad_numbers[:5], "ungrounded_tickers": bad_tickers[:5],
                                "provider_calls": 1}, confidence=0.8)
    return _response(text, ctx, intent, model=getattr(resp, "model", None) or "llm",
                     trace={**base_trace, "generated": True, "provider_calls": 1, "grounding": "ok"},
                     confidence=0.75)
