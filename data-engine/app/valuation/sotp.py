def run_sotp(segments: list[dict], net_debt: float, shares_outstanding: float) -> dict:
    if shares_outstanding <= 0:
        raise ValueError("shares_outstanding must be positive")

    segment_values = []
    for segment in segments:
        metric = float(segment["metric"])
        multiple = float(segment["multiple"])
        value = metric * multiple
        segment_values.append({**segment, "value": value})

    enterprise_value = sum(segment["value"] for segment in segment_values)
    equity_value = enterprise_value - net_debt
    return {
        "enterprise_value": enterprise_value,
        "equity_value": equity_value,
        "value_per_share": equity_value / shares_outstanding,
        "segments": segment_values,
        "trace": {"method": "sum_of_the_parts"},
    }



# ---------------------------------------------------------------------------
# Modelo SOTP editable por el usuario (desglose por partes a madurez).
#
# A diferencia de ``run_sotp`` (métrica actual × múltiplo − deuda, con datos de
# FinancialFact para el motor ``sotp``), aquí cada parte es un SUPUESTO del
# usuario a un año de madurez (p. ej. 2030E): ingresos, EBITDA (o margen) y
# múltiplo sectorial dan el EV de esa parte en ese año, que se descuenta a hoy
# con una tasa y se reparte entre las acciones totalmente diluidas. Los activos
# de balance (espectro, patentes) y la caja neta futura se suman al mismo año y
# se descuentan igual. Puro: sin DB ni red, para testearlo y reutilizarlo.
# ---------------------------------------------------------------------------

USER_SOTP_VERSION = "sotp-user-v1"
USER_SOTP_MAX_PARTS = 30
USER_SOTP_MAX_SCENARIOS = 8


def _num(value, *, name: str, problems: list[str], required: bool = False,
         low: float | None = None, high: float | None = None, low_inclusive: bool = True):
    if value is None or value == "":
        if required:
            problems.append(f"falta {name}")
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        problems.append(f"{name} no es un número")
        return None
    if out != out or out in (float("inf"), float("-inf")):
        problems.append(f"{name} no es un número finito")
        return None
    if low is not None and (out < low or (not low_inclusive and out == low)):
        problems.append(f"{name} fuera de rango (mínimo {low})")
        return None
    if high is not None and out > high:
        problems.append(f"{name} fuera de rango (máximo {high})")
        return None
    return out


def _text(value, limit: int = 240) -> str:
    return str(value or "").strip()[:limit]


#: Campos «¿de dónde sale?» de cada parte (opcionales; los rellena la propuesta de los agentes).
USER_SOTP_WHY_KEYS = ("revenue", "margin", "multiple", "probability", "value", "shares")
USER_SOTP_MAX_SOURCES = 6


def _why(value) -> dict | None:
    if not isinstance(value, dict):
        return None
    out = {k: _text(value.get(k), 300) for k in USER_SOTP_WHY_KEYS if _text(value.get(k), 300)}
    return out or None


def _sources(value) -> list[dict]:
    """Fuentes de una cifra: [{label, url?, date?}], solo texto, URL https o ruta interna."""
    out: list[dict] = []
    for item in value if isinstance(value, list) else []:
        if not isinstance(item, dict):
            continue
        label = _text(item.get("label"), 160)
        url = _text(item.get("url"), 400)
        if url and not (url.startswith("https://") or url.startswith("/")):
            url = ""
        if not label and not url:
            continue
        out.append({"label": label or url, "url": url or None, "date": _text(item.get("date"), 20) or None})
        if len(out) >= USER_SOTP_MAX_SOURCES:
            break
    return out


def _provenance(item: dict, target: dict) -> None:
    """Copia las razones y fuentes opcionales de una parte, dilución o escenario."""
    why = _why(item.get("why"))
    if why:
        target["why"] = why
    sources = _sources(item.get("sources"))
    if sources:
        target["sources"] = sources
    assumption = _text(item.get("assumption"), 300)
    if assumption:
        target["assumption"] = assumption


def normalize_user_sotp(raw) -> tuple[dict, list[str]]:
    """Valida y normaliza el modelo editable. Devuelve (modelo, problemas).

    Unidades: importes en millones de la divisa del modelo; acciones en
    millones; tasas en decimal (12,5 % = 0.125); múltiplos en veces.
    """
    problems: list[str] = []
    if not isinstance(raw, dict):
        return {}, ["el modelo debe ser un objeto"]
    base_year = _num(raw.get("base_year"), name="año de hoy", problems=problems, required=True, low=1990, high=2100)
    valuation_year = _num(raw.get("valuation_year"), name="año de madurez", problems=problems, required=True, low=1990, high=2120)
    discount_rate = _num(raw.get("discount_rate"), name="tasa de descuento", problems=problems, required=True, low=0.0, high=0.6)
    discount_years = _num(raw.get("discount_years"), name="años de descuento", problems=problems, low=0.0, high=40)
    if discount_years is None and base_year is not None and valuation_year is not None:
        discount_years = valuation_year - base_year
        if discount_years < 0:
            problems.append("el año de madurez es anterior al de hoy")
    shares_current = _num(raw.get("shares_current"), name="acciones actuales", problems=problems, required=True, low=0.0, low_inclusive=False)
    dilution = []
    for i, item in enumerate(raw.get("dilution") or []):
        if not isinstance(item, dict):
            problems.append(f"dilución {i + 1}: formato no válido")
            continue
        shares = _num(item.get("shares"), name=f"dilución {i + 1}", problems=problems, required=True)
        if shares is not None:
            entry = {"label": _text(item.get("label")) or f"Dilución {i + 1}", "shares": shares}
            _provenance(item, entry)
            dilution.append(entry)
    parts = []
    raw_parts = raw.get("parts") or []
    if not isinstance(raw_parts, list) or not raw_parts:
        problems.append("hace falta al menos una parte")
        raw_parts = []
    if len(raw_parts) > USER_SOTP_MAX_PARTS:
        problems.append(f"máximo {USER_SOTP_MAX_PARTS} partes")
        raw_parts = raw_parts[:USER_SOTP_MAX_PARTS]
    for i, item in enumerate(raw_parts):
        if not isinstance(item, dict):
            problems.append(f"parte {i + 1}: formato no válido")
            continue
        name = _text(item.get("name"), 120)
        if not name:
            problems.append(f"parte {i + 1}: falta el nombre")
        kind = item.get("kind") or "operating"
        if kind not in ("operating", "asset"):
            problems.append(f"parte {i + 1}: tipo desconocido {kind!r}")
            kind = "operating"
        label = f"parte {i + 1}"
        part = {"name": name, "kind": kind, "group": _text(item.get("group"), 60) or None,
                "note": _text(item.get("note"), 400) or None}
        probability = _num(item.get("probability"), name=f"{label}: probabilidad", problems=problems, low=0.0, high=1.0)
        part["probability"] = 1.0 if probability is None else probability
        if isinstance(item.get("commercial"), bool):
            part["commercial"] = item["commercial"]
        _provenance(item, part)
        if kind == "operating":
            revenue = _num(item.get("revenue"), name=f"{label}: ingresos", problems=problems, low=0.0)
            ebitda = _num(item.get("ebitda"), name=f"{label}: EBITDA", problems=problems)
            # El margen solo se usa (y se valida) si no hay EBITDA: con EBITDA dado
            # (p. ej. un FCF equivalente mayor que los ingresos) manda el EBITDA.
            margin = None if ebitda is not None else _num(
                item.get("ebitda_margin"), name=f"{label}: margen EBITDA", problems=problems, low=-1.0, high=1.0)
            multiple = _num(item.get("multiple"), name=f"{label}: múltiplo", problems=problems, required=True, low=0.0, high=200)
            if ebitda is None and margin is not None and revenue is None:
                problems.append(f"{label}: con margen hacen falta los ingresos")
            if ebitda is None and margin is None:
                problems.append(f"{label}: falta el EBITDA o el margen")
            part.update({"revenue": revenue, "ebitda": ebitda, "ebitda_margin": margin, "multiple": multiple})
        else:
            value = _num(item.get("value"), name=f"{label}: valor", problems=problems, required=True)
            discounted = item.get("discounted", True)
            part.update({"value": value, "discounted": bool(discounted)})
        parts.append(part)
    scenarios = []
    raw_scenarios = raw.get("scenarios") or []
    if len(raw_scenarios) > USER_SOTP_MAX_SCENARIOS:
        problems.append(f"máximo {USER_SOTP_MAX_SCENARIOS} escenarios")
        raw_scenarios = raw_scenarios[:USER_SOTP_MAX_SCENARIOS]
    for i, item in enumerate(raw_scenarios):
        if not isinstance(item, dict):
            problems.append(f"escenario {i + 1}: formato no válido")
            continue
        label = f"escenario {i + 1}"
        scenario = {
            "key": _text(item.get("key"), 40) or f"s{i + 1}",
            "label": _text(item.get("label"), 120) or f"Escenario {i + 1}",
            "note": _text(item.get("note"), 400) or None,
            "revenue_factor": _num(item.get("revenue_factor"), name=f"{label}: factor de ingresos", problems=problems, low=0.0, high=20),
            "multiple_factor": _num(item.get("multiple_factor"), name=f"{label}: factor de múltiplos", problems=problems, low=0.0, high=20),
            "delay_years": _num(item.get("delay_years"), name=f"{label}: retraso", problems=problems, low=0.0, high=20),
            "discount_rate": _num(item.get("discount_rate"), name=f"{label}: tasa", problems=problems, low=0.0, high=0.6),
            "shares_total": _num(item.get("shares_total"), name=f"{label}: acciones", problems=problems, low=0.0, low_inclusive=False),
            "stated_value_per_share": _num(item.get("stated_value_per_share"), name=f"{label}: valor declarado", problems=problems),
        }
        _provenance(item, scenario)
        scenarios.append(scenario)
    model = {
        "version": USER_SOTP_VERSION,
        # Sin divisa no se inventa una: el servicio pone la de la empresa.
        "currency": (_text(raw.get("currency"), 8).upper() or None),
        "units": "millones",
        "base_year": int(base_year) if base_year is not None else None,
        "valuation_year": int(valuation_year) if valuation_year is not None else None,
        "discount_years": discount_years,
        "discount_rate": discount_rate,
        "shares_current": shares_current,
        "dilution": dilution,
        "parts": parts,
        "scenarios": scenarios,
        "author": _text(raw.get("author"), 120) or None,
        "source": _text(raw.get("source"), 400) or None,
        "stated_value_per_share": _num(raw.get("stated_value_per_share"), name="valor declarado", problems=problems),
    }
    summary = _text(raw.get("summary"), 1500)
    if summary:
        model["summary"] = summary
    shares_why = _why(raw.get("shares_why"))
    if shares_why:
        model["shares_why"] = shares_why
    unvalued = []
    for item in (raw.get("unvalued") or [])[:20]:
        if isinstance(item, dict) and _text(item.get("name"), 120):
            unvalued.append({"name": _text(item.get("name"), 120), "status": _text(item.get("status"), 30) or None,
                             "reason": _text(item.get("reason"), 300) or None})
    if unvalued:
        model["unvalued"] = unvalued
    warnings = [_text(w, 300) for w in (raw.get("warnings") or [])[:10] if _text(w, 300)]
    if warnings:
        model["warnings"] = warnings
    rules = _text(raw.get("rules_version"), 40)
    if rules:
        model["rules_version"] = rules
    rate_source = _text(raw.get("discount_rate_source"), 300)
    if rate_source:
        model["discount_rate_source"] = rate_source
    if shares_current is not None and shares_current + sum(d["shares"] for d in dilution) <= 0:
        problems.append("las acciones diluidas deben ser positivas")
    return model, problems


def _compute(model: dict, *, revenue_factor: float = 1.0, multiple_factor: float = 1.0,
             delay_years: float = 0.0, discount_rate: float | None = None,
             shares_total: float | None = None) -> dict:
    rate = model["discount_rate"] if discount_rate is None else discount_rate
    years = float(model["discount_years"] or 0.0)
    shares = shares_total if shares_total is not None else (
        model["shares_current"] + sum(d["shares"] for d in model["dilution"]))
    op_factor = (1.0 + rate) ** (years + delay_years)
    asset_factor = (1.0 + rate) ** years
    rows = []
    for part in model["parts"]:
        p = part["probability"]
        if part["kind"] == "operating":
            raw_ebitda = part["ebitda"] if part["ebitda"] is not None else (
                (part["revenue"] or 0.0) * (part["ebitda_margin"] or 0.0))
            ebitda = raw_ebitda * revenue_factor
            revenue = part["revenue"] * revenue_factor if part["revenue"] is not None else None
            multiple = part["multiple"] * multiple_factor
            ev = ebitda * multiple
            factor = op_factor
        else:
            ebitda = None
            revenue = None
            multiple = None
            ev = part["value"]
            factor = asset_factor if part.get("discounted", True) else 1.0
        ev_weighted = ev * p
        pv = ev_weighted / factor
        rows.append({
            "name": part["name"], "kind": part["kind"], "group": part.get("group"),
            "revenue": revenue, "ebitda": ebitda, "multiple": multiple, "probability": p,
            "ebitda_margin": (ebitda / revenue) if (ebitda is not None and revenue) else None,
            "value_at_maturity": ev, "value_at_maturity_weighted": ev_weighted,
            "discount_factor": factor, "present_value": pv,
            "value_per_share": pv / shares,
            **{k: part[k] for k in ("why", "sources", "assumption", "commercial") if k in part},
        })
    total_ev = sum(r["value_at_maturity_weighted"] for r in rows)
    total_pv = sum(r["present_value"] for r in rows)
    total_ebitda = sum((r["ebitda"] or 0.0) * r["probability"] for r in rows if r["kind"] == "operating")
    op_ev = sum(r["value_at_maturity_weighted"] for r in rows if r["kind"] == "operating")
    return {
        "rows": rows,
        "total_value_at_maturity": total_ev,
        "total_present_value": total_pv,
        "total_revenue": sum((r["revenue"] or 0.0) * r["probability"] for r in rows if r["kind"] == "operating"),
        "total_ebitda": total_ebitda,
        "weighted_multiple": (op_ev / total_ebitda) if total_ebitda > 0 else None,
        "shares_diluted": shares,
        "discount_rate": rate,
        "discount_years": years + delay_years,
        "discount_factor": op_factor,
        "value_per_share": total_pv / shares,
    }


def _vs_price(value: float, price: float | None) -> float | None:
    if price is None or price <= 0:
        return None
    return value / price - 1.0


# Sensibilidad fija: cuánto depende el total de cada supuesto.
USER_SOTP_SENSITIVITY = (
    ("multiples_minus_30", "Múltiplos −30 %", {"multiple_factor": 0.7}),
    ("delay_2y", "Ingresos 2 años más tarde", {"delay_years": 2.0}),
    ("revenue_minus_50", "Ingresos −50 %", {"revenue_factor": 0.5}),
    ("rate_plus_5pp", "Tasa +5 puntos", {"rate_delta": 0.05}),
    ("combined", "Las tres a la vez: múltiplos −30 %, 2 años tarde y tasa +5 puntos",
     {"multiple_factor": 0.7, "delay_years": 2.0, "rate_delta": 0.05}),
)


def run_user_sotp(model: dict, *, price: float | None = None) -> dict:
    """Calcula el SOTP editable ya normalizado (``normalize_user_sotp``).

    Devuelve tabla parte → valor a madurez → valor hoy → $/acción, totales,
    escenarios del usuario (con su cifra declarada al lado si la dio) y una
    sensibilidad fija. ``price`` solo sirve para el % frente al precio.
    """
    base = _compute(model)
    scenarios = []
    for s in model.get("scenarios") or []:
        has_params = any(s.get(k) is not None for k in
                         ("revenue_factor", "multiple_factor", "delay_years", "discount_rate", "shares_total"))
        computed = None
        if has_params:
            computed = _compute(
                model,
                revenue_factor=s["revenue_factor"] if s.get("revenue_factor") is not None else 1.0,
                multiple_factor=s["multiple_factor"] if s.get("multiple_factor") is not None else 1.0,
                delay_years=s["delay_years"] or 0.0,
                discount_rate=s.get("discount_rate"),
                shares_total=s.get("shares_total"),
            )["value_per_share"]
        stated = s.get("stated_value_per_share")
        scenarios.append({
            **s,
            "computed": has_params,
            "value_per_share": computed,
            "vs_price": _vs_price(computed, price) if computed is not None else None,
            "stated_vs_price": _vs_price(stated, price) if stated is not None else None,
            # Diferencia entre la cifra declarada y la que salen de sus propios
            # parámetros (None si no hay ambas).
            "stated_gap": (stated / computed - 1.0) if (stated is not None and computed) else None,
        })
    sensitivity = []
    for key, label, knobs in USER_SOTP_SENSITIVITY:
        rate = model["discount_rate"] + knobs.get("rate_delta", 0.0)
        value = _compute(
            model,
            revenue_factor=knobs.get("revenue_factor", 1.0),
            multiple_factor=knobs.get("multiple_factor", 1.0),
            delay_years=knobs.get("delay_years", 0.0),
            discount_rate=rate,
        )["value_per_share"]
        sensitivity.append({
            "key": key, "label": label, "value_per_share": value,
            "vs_base": value / base["value_per_share"] - 1.0 if base["value_per_share"] else None,
            "vs_price": _vs_price(value, price),
        })
    stated = model.get("stated_value_per_share")
    return {
        **base,
        "price": price,
        "vs_price": _vs_price(base["value_per_share"], price),
        "stated_value_per_share": stated,
        "stated_gap": (stated / base["value_per_share"] - 1.0) if (stated and base["value_per_share"]) else None,
        # Parte del precio actual que ya cubren las partes, de mayor a menor.
        "price_covered_by": _price_covered_by(base["rows"], price),
        "scenarios": scenarios,
        "sensitivity": sensitivity,
        "trace": {"method": "sum_of_the_parts_user", "version": USER_SOTP_VERSION,
                  "formula": "Σ (EBITDA × múltiplo × probabilidad) / (1 + tasa)^años + activos / (1 + tasa)^años; ÷ acciones diluidas"},
    }


def _price_covered_by(rows: list[dict], price: float | None) -> list[dict]:
    if price is None or price <= 0:
        return []
    out = []
    cumulative = 0.0
    for row in sorted(rows, key=lambda r: r["value_per_share"], reverse=True):
        cumulative += row["value_per_share"]
        out.append({"name": row["name"], "value_per_share": row["value_per_share"],
                    "cumulative_per_share": cumulative, "covers_price": cumulative >= price})
        if cumulative >= price:
            break
    return out
