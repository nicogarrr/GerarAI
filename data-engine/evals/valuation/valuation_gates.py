"""Puertas deterministas para los 8 motores de valoración (C2).

Mismo contrato que ``evals/gates.py``: cada puerta es una funcion pura
``f(case) -> {"gate", "passed", "details"}`` sobre el caso del dataset y el
``artifact`` que es la SALIDA REAL del motor. Nada de LLM juzgando a LLM: los
numeros se comparan contra la forma cerrada calculada a mano en el propio caso,
el estado publicado se contrasta con los ``publication_blockers`` y el rango con
la banda bear/base/bull.

El dataset (``,data-engine/evals/valuation/valuation_engines_v1.json``) es un
contrato congelado: las puertas no recalculan nada del modelo, comparan.

Gates NO OMITIBLES
------------------
``NON_SKIPPABLE_GATES`` son las puertas cuya clave obligatoria falta = fallo. Sin
esa regla, un caso que no declara ``missing_inputs`` (o que publica sin
``probabilities``) deja la puerta sin nada que morder y el dataset entero queda
verde sin comprobar nada. ``tests/test_valuation_gate_contracts.py`` comprueba
que cada puerta de la tupla falla cuando su clave falta.
"""

from __future__ import annotations

import math

# Tolerancia RELATIVA contra la forma cerrada calculada a mano en el caso.
VALUE_TOLERANCE = 1e-6
# Suma de probabilidades: los pesos se construyen como 1 - base + bull, asi que
# solo puede desviarse por redondeo de coma flotante.
PROBABILITY_TOLERANCE = 1e-9

# Contrato de ``ValuationEngine.value()``. Una clave ausente aqui es lo que
# permite que una puerta pase por ausencia, asi que su ausencia es un fallo.
RESULT_CONTRACT_KEYS = (
    "ticker",
    "model_type",
    "status",
    "publishable",
    "current_price",
    "bear_value",
    "base_value",
    "bull_value",
    "expected_value",
    "margin_of_safety",
    "missing_inputs",
    "reverse_dcf",
    "sensitivity",
    "moat",
    "trace",
)

VALID_STATUSES = ("ok", "partial", "insufficient_data")

# Motores cuyo valor es EV - net_debt, es decir los que TIENEN puente de equity
# donde un net_debt desconocido podria colarse como 0. bank e insurer NO lo tienen:
# valoran el CAPITAL directamente sobre tangible/common book value (un P/B
# justificado), asi que no hay puente que pueda mentir.
NET_DEBT_BRIDGE_ENGINES = frozenset(
    {"standard_dcf", "commodity", "sotp", "holding_company", "reit", "pre_revenue"}
)

# Las cuatro claves que el motor devuelve siempre y que las demas puertas leen.
VALUE_KEYS = ("bear_value", "base_value", "bull_value", "expected_value")

# (gate, clave obligatoria del caso o del artifact cuya ausencia es un fallo)
NON_SKIPPABLE_GATES: tuple[str, ...] = (
    "engine_publishable_status",
    "value_matches_closed_form",
    "probabilities_sum_to_one",
    "missing_inputs_declared",
    "routing_expected",
    "gate_does_not_omit_itself",
)

# Sufijo literal exigido por el contrato de "gates no omitibles": una clave que
# falta es un fallo, no un "no aplica".
OMISSIBLE = ": el gate no puede omitirse"


def _result(gate: str, passed: bool, details: list[str]) -> dict:
    return {"gate": gate, "passed": passed, "details": details}


def _artifact(case: dict) -> dict:
    return case.get("artifact") or {}


def _expected(case: dict) -> dict:
    return case.get("expected") or {}


def _trace(case: dict) -> dict:
    trace = _artifact(case).get("trace")
    return trace if isinstance(trace, dict) else {}


def _omitted(gate: str, what: str) -> dict:
    return _result(gate, False, [f"falta {what}{OMISSIBLE}"])


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _close(actual: object, expected: object, tolerance: float = VALUE_TOLERANCE) -> bool:
    left, right = _number(actual), _number(expected)
    if left is None or right is None:
        return False
    return abs(left - right) <= tolerance * max(abs(right), 1e-12)


def _fmt(value: object) -> str:
    number = _number(value)
    return "None" if number is None else f"{number:.10g}"


def _sensitivity_values(sensitivity: object) -> list[float]:
    """Todos los ``value_per_share`` en una lista plana, en cualquier formato."""
    values: list[float] = []
    rows = (sensitivity or {}).get("rows") if isinstance(sensitivity, dict) else None
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        cells = [row.get("value_per_share")]
        cells += [cell.get("value_per_share") for cell in row.get("values") or []]
        for candidate in cells:
            number = _number(candidate)
            if number is not None:
                values.append(number)
    return values


def _scenario_band(artifact: dict, trace: dict) -> tuple[dict[str, float], dict[str, float]] | None:
    """Probabilidades y valores por escenario, se expongan como se expongan.

    Los motores de sector y de commodity publican ``trace.probabilities`` junto a los
    campos planos bear/base/bull; el DCF, pre-revenue y el SOTP solo publican
    ``trace.scenarios[*].definition.probability``. Es el mismo contrato.
    """
    probabilities: dict[str, float] = {}
    values: dict[str, float] = {}
    flat = trace.get("probabilities")
    if isinstance(flat, dict):
        for name, raw in flat.items():
            number = _number(raw)
            if number is not None:
                probabilities[str(name)] = number
        for name, key in (("bear", "bear_value"), ("base", "base_value"), ("bull", "bull_value")):
            number = _number(artifact.get(key))
            if number is not None and name in probabilities:
                values[name] = number
        if len(probabilities) == 3 and len(values) == 3:
            return probabilities, values
    scenarios = trace.get("scenarios")
    if isinstance(scenarios, dict) and scenarios:
        for name, data in scenarios.items():
            if not isinstance(data, dict):
                continue
            definition = data.get("definition") or {}
            probability = _number(definition.get("probability"))
            value = _number(data.get("value_per_share"))
            if probability is not None and value is not None:
                probabilities[str(name)] = probability
                values[str(name)] = value
        if len(probabilities) >= 3:
            return probabilities, values
    return None


def _case_margin(case: dict) -> float | None:
    """Effective base FCF margin implied by the facts the case declares."""
    facts = case.get("facts") or {}
    margin = _number(facts.get("fcf_margin"))
    if margin is not None:
        return margin
    fcf = _number(facts.get("free_cash_flow"))
    revenue = _number(facts.get("revenue"))
    if fcf is None or revenue is None or revenue == 0:
        return None
    return fcf / revenue


def _declares_assumptions(trace: dict) -> bool:
    """Whether a non-final result names its assumptions instead of implying facts.

    Un rango indicativo puede usar un net_debt 0 solo si lo dice: un resultado
    ``publishable=False`` con ``valuation_basis``/``assumed`` en su trace es una
    orientacion con sus inputs enumerados, no una valoracion publicada construida
    sobre uno inventado.
    """
    return bool(trace.get("assumed")) or bool(trace.get("valuation_basis"))


# ---------------------------------------------------------------------------
# contrato del resultado
# ---------------------------------------------------------------------------


def gate_does_not_omit_itself(case: dict) -> dict:
    """Ninguna puerta puede pasar por ausencia de la clave que lee.

    Una puerta que solo mira ``artifact["missing_inputs"]`` pasa sola cuando esa
    clave no existe. Aqui se exige el contrato COMPLETO de ``value()``: sin
    ``trace``, ``sensitivity`` o ``status``, el resto de puertas de este dataset
    estarian midiendo ``None`` y darian verde sin comprobar nada.
    """
    artifact = _artifact(case)
    missing = [key for key in RESULT_CONTRACT_KEYS if key not in artifact]
    if missing:
        return _result(
            "gate_does_not_omit_itself",
            False,
            [f"el resultado no declara {', '.join(missing)}{OMISSIBLE}"],
        )
    if not isinstance(artifact.get("trace"), dict):
        return _result("gate_does_not_omit_itself", False, ["trace no es dict: el gate no puede omitirse"])
    return _result(
        "gate_does_not_omit_itself",
        True,
        [f"contrato completo ({len(RESULT_CONTRACT_KEYS)} claves)"],
    )


# ---------------------------------------------------------------------------
# estado publicado
# ---------------------------------------------------------------------------


def gate_engine_publishable_status(case: dict) -> dict:
    """El estado declarado, los blockers y ``publishable`` tienen que coincidir.

    Un motor puede llamar "publicable" a una valoracion con blockers
    (``traceable_wacc`` sin fuente, forecast que no mueve el valor) y el
    consumidor la publica como final. La etiqueta es la parte que la tesis, el
    red team y la persistencia tratan como "esto es definitivo".
    """
    expected = _expected(case)
    if "status" not in expected:
        return _omitted("engine_publishable_status", "expected.status")
    artifact = _artifact(case)
    status = artifact.get("status")
    publishable = artifact.get("publishable")
    blockers = [str(item) for item in (artifact.get("publication_blockers") or [])]
    problems: list[str] = []

    if status not in VALID_STATUSES:
        problems.append(f"status desconocido: {status!r}")
    if status != expected["status"]:
        problems.append(f"status {status!r} != declarado {expected['status']!r}")
    declared_publishable = expected.get("publishable", expected["status"] == "ok")
    if publishable is not declared_publishable:
        problems.append(f"publishable {publishable!r} != declarado {declared_publishable!r}")
    if sorted(blockers) != sorted(expected.get("publication_blockers") or []):
        problems.append(f"publication_blockers {blockers} != declarados {expected.get('publication_blockers') or []}")
    if blockers and publishable is not False:
        problems.append(f"blockers {blockers} con publishable={publishable!r}")
    if publishable is True and (status != "ok" or blockers):
        problems.append(f"publishable con status={status!r} y blockers={blockers}")
    if status == "insufficient_data":
        for key in VALUE_KEYS:
            if artifact.get(key) is not None:
                problems.append(f"rechazo que publica {key}={_fmt(artifact.get(key))}")
        if publishable is not False:
            problems.append("rechazo con publishable=True")
    if problems:
        return _result("engine_publishable_status", False, problems)
    return _result(
        "engine_publishable_status",
        True,
        [f"status={status} publishable={publishable} blockers={blockers or 'ninguno'}"],
    )


# ---------------------------------------------------------------------------
# banda de escenarios
# ---------------------------------------------------------------------------


def gate_bear_le_base_le_bull(case: dict) -> dict:
    artifact = _artifact(case)
    bear = _number(artifact.get("bear_value"))
    base = _number(artifact.get("base_value"))
    bull = _number(artifact.get("bull_value"))
    if bear is None or base is None or bull is None:
        return _result(
            "bear_le_base_le_bull",
            False,
            [f"banda incompleta: bear={_fmt(bear)} base={_fmt(base)} bull={_fmt(bull)}"],
        )
    if not bear <= base <= bull:
        return _result(
            "bear_le_base_le_bull",
            False,
            [f"orden roto: {bear:.10g} <= {base:.10g} <= {bull:.10g}"],
        )
    return _result("bear_le_base_le_bull", True, [f"{bear:.10g} <= {base:.10g} <= {bull:.10g}"])


def gate_expected_value_within_band(case: dict) -> dict:
    """El valor esperado cae dentro de la banda y es la media ponderada de ella."""
    artifact = _artifact(case)
    bear = _number(artifact.get("bear_value"))
    base = _number(artifact.get("base_value"))
    bull = _number(artifact.get("bull_value"))
    expected_value = _number(artifact.get("expected_value"))
    if bear is None or base is None or bull is None or expected_value is None:
        return _result(
            "expected_value_within_band",
            False,
            [f"banda o valor esperado ausente: expected={_fmt(expected_value)}"],
        )
    problems: list[str] = []
    if not bear <= expected_value <= bull:
        problems.append(f"expected {expected_value:.10g} fuera de [{bear:.10g}, {bull:.10g}]")
    band = _scenario_band(artifact, _trace(case))
    if band is None:
        return _omitted("expected_value_within_band", "probabilidades de escenario")
    probabilities, values = band
    if len(probabilities) != 3:
        problems.append(f"se esperaban 3 escenarios con probabilidad, hay {len(probabilities)}")
    else:
        recomputed = sum(probabilities[name] * values[name] for name in probabilities)
        if not _close(expected_value, recomputed):
            problems.append(f"expected {expected_value:.10g} != suma p·v {recomputed:.10g}")
    if problems:
        return _result("expected_value_within_band", False, problems)
    return _result("expected_value_within_band", True, [f"expected={expected_value:.10g} dentro de la banda"])


# ---------------------------------------------------------------------------
# forma cerrada (el numero, no la forma)
# ---------------------------------------------------------------------------


def gate_value_matches_closed_form(case: dict) -> dict:
    """Compara contra el valor calculado A MANO en el dataset.

    ``expected.closed_form`` es la forma cerrada escrita desde la formula
    documentada del motor, no la salida del motor: si el codigo se aparta de la
    formula esta puerta tiene que FALLAR, que es justo su trabajo. ``null`` es
    una declaracion explicita ("este campo no puede llevar numero").
    """
    expected = _expected(case)
    closed_form = expected.get("closed_form")
    if not isinstance(closed_form, dict) or not closed_form:
        return _omitted("value_matches_closed_form", "expected.closed_form")
    unknown = sorted(set(closed_form) - set(VALUE_KEYS))
    if unknown:
        return _result("value_matches_closed_form", False, [f"claves no comparables: {unknown}"])
    artifact = _artifact(case)
    problems: list[str] = []
    for key in VALUE_KEYS:
        if key not in closed_form:
            continue
        want = closed_form[key]
        got = artifact.get(key)
        if want is None:
            if got is not None:
                problems.append(f"{key} deberia ser null y es {_fmt(got)}")
            continue
        if not _close(got, want):
            problems.append(f"{key} {_fmt(got)} != forma cerrada {_fmt(want)}")
    if problems:
        return _result("value_matches_closed_form", False, problems)
    return _result(
        "value_matches_closed_form",
        True,
        [f"{len(closed_form)} valores coinciden con la forma cerrada"],
    )


# ---------------------------------------------------------------------------
# probabilidades
# ---------------------------------------------------------------------------


def gate_probabilities_sum_to_one(case: dict) -> dict:
    """Toda valoracion publicada pondera escenarios cuya suma es 1.0."""
    artifact = _artifact(case)
    trace = _trace(case)
    band = _scenario_band(artifact, trace)
    if band is None:
        return _omitted("probabilities_sum_to_one", "trace.probabilities o trace.scenarios")
    probabilities, _ = band
    if len(probabilities) != 3:
        return _result(
            "probabilities_sum_to_one",
            False,
            [f"se esperaban 3 escenarios, hay {len(probabilities)}: {sorted(probabilities)}"],
        )
    total = sum(probabilities.values())
    if any(value < 0 for value in probabilities.values()):
        return _result("probabilities_sum_to_one", False, [f"probabilidad negativa: {probabilities}"])
    if abs(total - 1.0) > PROBABILITY_TOLERANCE:
        return _result(
            "probabilities_sum_to_one",
            False,
            [f"suma={total!r} (esperado 1.0 +/- {PROBABILITY_TOLERANCE})"],
        )
    return _result("probabilities_sum_to_one", True, [f"suma={total:.12f}"])


# ---------------------------------------------------------------------------
# sensibilidad
# ---------------------------------------------------------------------------


def gate_sensitivity_covers_base(case: dict) -> dict:
    """La tabla de sensibilidad tiene >=3 valores distintos y acota el base."""
    artifact = _artifact(case)
    values = _sensitivity_values(artifact.get("sensitivity"))
    if not values:
        return _result("sensitivity_covers_base", False, ["sensibilidad sin value_per_share"])
    distinct = {round(value, 10) for value in values}
    if len(distinct) < 3:
        return _result(
            "sensitivity_covers_base",
            False,
            [f"solo {len(distinct)} valores distintos en la sensibilidad"],
        )
    base = _number(artifact.get("base_value"))
    if base is None:
        return _result("sensitivity_covers_base", False, [f"base ausente: {_fmt(base)}"])
    low, high = min(values), max(values)
    if not low <= base <= high:
        return _result(
            "sensitivity_covers_base",
            False,
            [f"base {base:.10g} fuera del rango de sensibilidad [{low:.10g}, {high:.10g}]"],
        )
    return _result(
        "sensitivity_covers_base",
        True,
        [f"{len(distinct)} valores; base {base:.10g} en [{low:.10g}, {high:.10g}]"],
    )


# ---------------------------------------------------------------------------
# honestidad
# ---------------------------------------------------------------------------


def gate_missing_inputs_declared(case: dict) -> dict:
    """Lo que el motor declara que le falta tiene que estar escrito en el caso.

    Sin esta declaracion, "el motor publico sin ningun input" y "el motor dijo
    exactamente que le faltaba" son indistinguibles, y un motor que se calla un
    input obligatorio pasa igual que uno que lo confiesa.
    """
    expected = _expected(case)
    if "missing_inputs" not in expected:
        return _omitted("missing_inputs_declared", "expected.missing_inputs")
    declared = [str(item) for item in (expected["missing_inputs"] or [])]
    artifact = _artifact(case)
    actual = [str(item) for item in (artifact.get("missing_inputs") or [])]
    if sorted(actual) != sorted(declared):
        return _result(
            "missing_inputs_declared",
            False,
            [f"missing_inputs {actual} != declarados {declared}"],
        )
    return _result("missing_inputs_declared", True, [f"missing_inputs={actual or 'ninguno'}"])


def gate_no_silent_zero_net_debt(case: dict) -> dict:
    """Una deuda neta desconocida no puede entrar como 0 en algo publicable.

    El puente de equity es ``EV - net_debt``: tratar "desconocido" como 0 inventa
    equity por exactamente ``net_debt / shares``. Solo se admite cuando el
    resultado NO es publicable y nombra sus supuestos (un rango indicativo lo
    dice en su trace), y en ese caso se exige que lo diga explicitamente.
    """
    engine = case.get("engine")
    if engine not in NET_DEBT_BRIDGE_ENGINES:
        return _result(
            "no_silent_zero_net_debt",
            True,
            [f"{engine} no construye puente EV - net_debt (P/B sobre capital)"],
        )
    facts = case.get("facts") or {}
    if "net_debt" in facts:
        return _result("no_silent_zero_net_debt", True, ["net_debt declarado como fact"])
    artifact = _artifact(case)
    if artifact.get("base_value") is None:
        return _result(
            "no_silent_zero_net_debt",
            True,
            [f"sin fact de net_debt y sin valor publicado (status={artifact.get('status')})"],
        )
    trace = _trace(case)
    source = trace.get("net_debt_source")
    if source is None and (artifact.get("publishable") is not False or not _declares_assumptions(trace)):
        return _result(
            "no_silent_zero_net_debt",
            False,
            [
                "valor publicado sin fact de net_debt y sin trace.net_debt_source: "
                "la deuda neta se ha supuesto 0 en silencio"
            ],
        )
    if source is None:
        return _result(
            "no_silent_zero_net_debt",
            True,
            [
                "net_debt ausente, valor no publicable y supuestos declarados en el "
                "trace (valuation_basis/assumed): no entra como 0 en nada publicado"
            ],
        )
    if source == "missing_assumed_zero" and artifact.get("publishable") is not False:
        return _result(
            "no_silent_zero_net_debt",
            False,
            [f"net_debt_source={source} en un resultado publishable"],
        )
    return _result("no_silent_zero_net_debt", True, [f"net_debt ausente y declarado como {source}"])


def gate_no_sign_flip_on_negative_fcf(case: dict) -> dict:
    """Una quema de caja conocida no se publica con el signo cambiado.

    Un FCFF no puede representar un FCF negativo: acotar el margen a un suelo
    positivo convierte -8% de quema en un valor positivo, y en pre-revenue la
    dilucion acerca una perdida a cero y rompe el orden bear <= base <= bull.
    """
    margin = _case_margin(case)
    engine = case.get("engine")
    artifact = _artifact(case)
    trace = _trace(case)
    if margin is None or margin >= 0:
        return _result(
            "no_sign_flip_on_negative_fcf",
            False,
            [f"margen FCF efectivo {_fmt(margin)}: el caso no es de quema, no aplica{OMISSIBLE}"],
        )
    problems: list[str] = []
    if engine == "standard_dcf":
        if artifact.get("status") != "insufficient_data":
            problems.append(f"quema de caja ({margin:.4f}) publicada como status={artifact.get('status')!r}")
        if "non_negative_fcf_margin" not in (artifact.get("missing_inputs") or []):
            problems.append("falta el motivo non_negative_fcf_margin")
        for key in VALUE_KEYS:
            if artifact.get(key) is not None:
                problems.append(f"{key} publicado sobre una quema: {_fmt(artifact.get(key))}")
    elif engine == "pre_revenue" and artifact.get("status") == "insufficient_data":
        # Contrato actual: la quema se niega (cualquier motivo de insuficiencia
        # vale), no se publica valor por accion.
        for key in VALUE_KEYS:
            if artifact.get(key) is not None:
                problems.append(f"{key} publicado sobre una quema: {_fmt(artifact.get(key))}")
    elif engine == "pre_revenue":
        scenarios = trace.get("scenarios") or {}
        for name, data in scenarios.items():
            if not isinstance(data, dict):
                continue
            undiluted = _number(data.get("undiluted_value_per_share"))
            published = _number(data.get("value_per_share"))
            if undiluted is None or published is None:
                continue
            if undiluted <= 0 and published > undiluted:
                problems.append(f"escenario {name}: la dilucion sube {undiluted:.10g} a {published:.10g}")
        facts = case.get("facts") or {}
        net_debt = _number(facts.get("net_debt")) or 0.0
        base = _number(artifact.get("base_value"))
        if base is not None and net_debt >= 0 and base > 0:
            problems.append(f"quema de caja con net_debt={net_debt} publicada como base {base:.10g}")
    if problems:
        return _result("no_sign_flip_on_negative_fcf", False, problems)
    return _result(
        "no_sign_flip_on_negative_fcf",
        True,
        [f"margen FCF {margin:.4f} sin salto de signo (status={artifact.get('status')})"],
    )


# ---------------------------------------------------------------------------
# routing y evidencia
# ---------------------------------------------------------------------------


def gate_routing_expected(case: dict) -> dict:
    """La empresa llega al motor que el caso declara, no al que le toca por defecto.

    ``bank``/``insurer``/``reit`` solo se alcanzan por ``company_type``
    explicito; un cambio en el if-chain de ``resolve_engine_key`` cambiaria en
    silencio que modelo decide el valor de una entidad.
    """
    expected = _expected(case)
    if "engine_key" not in expected:
        return _omitted("routing_expected", "expected.engine_key")
    routing = (_artifact(case).get("_routing")) or {}
    resolved = routing.get("resolved_engine")
    if resolved is None:
        return _omitted("routing_expected", "artifact._routing.resolved_engine")
    if resolved != expected["engine_key"]:
        return _result(
            "routing_expected",
            False,
            [f"resolve_engine_key -> {resolved!r}, declarado {expected['engine_key']!r}"],
        )
    trace_engine = routing.get("trace_engine")
    declared_trace_engine = expected.get("trace_engine")
    if declared_trace_engine is not None:
        # Un alias tiene que declararlo el caso: un trace.engine que discrepa del
        # resolve_engine_key es un hecho que el lector no ve de otra forma.
        if trace_engine != declared_trace_engine:
            return _result(
                "routing_expected",
                False,
                [f"trace.engine {trace_engine!r} != declarado {declared_trace_engine!r}"],
            )
    elif trace_engine is not None and trace_engine != resolved:
        return _result(
            "routing_expected",
            False,
            [
                f"trace.engine {trace_engine!r} != resolve_engine_key {resolved!r} "
                f"y el caso no declara el alias"
            ],
        )
    return _result("routing_expected", True, [f"resolve_engine_key -> {resolved}"])


def gate_adr_ratio_basis(case: dict) -> dict:
    """La base del valor por accion y la de la cotizacion son la misma, y se dice.

    ``shares_diluted`` viene del filing en acciones ORDINARIAS y la cotizacion de
    un ADR es por ADR: dividir uno por otro es un error de un factor N. Con el
    ratio declarado el motor convierte la cotizacion a base ordinaria antes del
    margen de seguridad y publica los valores por ACCION LISTADA aparte.
    """
    expected = _expected(case)
    if "adr_ratio" not in expected:
        return _omitted("adr_ratio_basis", "expected.adr_ratio")
    declared = _number(expected["adr_ratio"])
    artifact = _artifact(case)
    ratio = _number(artifact.get("adr_ratio"))
    trace = _trace(case)
    problems: list[str] = []
    if (declared is None) != (ratio is None):
        problems.append(f"adr_ratio {ratio} != declarado {declared}")
    if ratio is None:
        if artifact.get("value_per_share_basis") != "ordinary_share":
            problems.append(f"value_per_share_basis={artifact.get('value_per_share_basis')!r}")
        if artifact.get("comparable_price_basis") != "listed_share":
            problems.append(f"comparable_price_basis={artifact.get('comparable_price_basis')!r}")
        if artifact.get("listed_share_values") is not None:
            problems.append("listed_share_values presente sin ratio ADR")
        return _result(
            "adr_ratio_basis",
            not problems,
            problems or ["no es ADR: valor y cotizacion en la misma base"],
        )

    if declared is not None and abs(ratio - declared) > 1e-9:
        problems.append(f"adr_ratio {ratio} != declarado {declared}")
    if artifact.get("value_per_share_basis") != "ordinary_share":
        problems.append(f"value_per_share_basis={artifact.get('value_per_share_basis')!r}")
    if artifact.get("comparable_price_basis") != "ordinary_share":
        problems.append(f"comparable_price_basis={artifact.get('comparable_price_basis')!r}")
    listed = artifact.get("listed_share_values")
    if not isinstance(listed, dict):
        problems.append("listed_share_values ausente en un ADR con ratio")
    else:
        for name, key in (
            ("bear", "bear_value"),
            ("base", "base_value"),
            ("bull", "bull_value"),
            ("expected", "expected_value"),
        ):
            value = _number(artifact.get(key))
            if name not in listed:
                problems.append(f"listed_share_values sin {name}")
            elif value is not None and not _close(listed[name], value * ratio):
                problems.append(
                    f"listed_share_values[{name}] {_fmt(listed[name])} != "
                    f"valor ordinario x {ratio}"
                )
    comparable = _number(trace.get("comparable_price"))
    price = _number(artifact.get("current_price"))
    if comparable is not None and price is not None and not _close(comparable, price / ratio):
        problems.append(f"trace.comparable_price {_fmt(comparable)} != precio / {ratio}")
    expected_value = _number(artifact.get("expected_value"))
    margin = _number(artifact.get("margin_of_safety"))
    if comparable and margin is not None and expected_value:
        # Margen de seguridad estándar (Graham): (V − P)/V = 1 − P/V.
        if not _close(margin, 1 - comparable / expected_value):
            problems.append(
                f"margin_of_safety {_fmt(margin)} != 1 - comparable/expected"
            )
    if problems:
        return _result("adr_ratio_basis", False, problems)
    return _result("adr_ratio_basis", True, [f"ratio {ratio:g}: base ordinaria declarada"])


def gate_trace_records_evidence(case: dict) -> dict:
    """Una valoracion publicable dice de que facts sale, con id y periodo."""
    artifact = _artifact(case)
    if artifact.get("base_value") is None:
        return _result(
            "trace_records_evidence",
            False,
            [f"el caso declara esta puerta pero no publica valor (status={artifact.get('status')!r})"],
        )
    trace = _trace(case)
    fact_ids = trace.get("fact_ids")
    if not isinstance(fact_ids, dict) or not any(value is not None for value in fact_ids.values()):
        return _result("trace_records_evidence", False, ["trace.fact_ids vacio o ausente"])
    periods = trace.get("periods")
    if not isinstance(periods, dict) or not any(value is not None for value in periods.values()):
        return _result("trace_records_evidence", False, ["trace.periods vacio o ausente"])
    if not trace.get("model_version"):
        return _result("trace_records_evidence", False, ["trace.model_version ausente"])
    return _result(
        "trace_records_evidence",
        True,
        [f"{sum(1 for v in fact_ids.values() if v is not None)} fact_ids con periodo"],
    )


GATES = {
    "engine_publishable_status": gate_engine_publishable_status,
    "bear_le_base_le_bull": gate_bear_le_base_le_bull,
    "expected_value_within_band": gate_expected_value_within_band,
    "value_matches_closed_form": gate_value_matches_closed_form,
    "probabilities_sum_to_one": gate_probabilities_sum_to_one,
    "sensitivity_covers_base": gate_sensitivity_covers_base,
    "missing_inputs_declared": gate_missing_inputs_declared,
    "no_silent_zero_net_debt": gate_no_silent_zero_net_debt,
    "no_sign_flip_on_negative_fcf": gate_no_sign_flip_on_negative_fcf,
    "routing_expected": gate_routing_expected,
    "trace_records_evidence": gate_trace_records_evidence,
    "gate_does_not_omit_itself": gate_does_not_omit_itself,
    "adr_ratio_basis": gate_adr_ratio_basis,
}


def run_case(case: dict) -> list[dict]:
    return [gate(case) for gate in GATES.values()]
