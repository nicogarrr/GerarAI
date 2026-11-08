"""Nota de 0 a 10 por tesis, con componentes visibles, y comparación con analistas.

Todo lo que puntúa aquí es determinista salvo el juez, que pesa poco (``PESO_JUEZ``) porque tiene ruido.
La comparación con analistas NO es una nota de «quién acierta»: hoy solo se mide la discrepancia. Quién
acierta lo dirá el registro de previsiones con fecha, puntuado a 1 y 3 años (``score_vs_analysts``).
Nunca se hace backtest de la prosa del modelo contra rentabilidades pasadas: el modelo ya sabe lo que pasó.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Iterable, Mapping, Sequence
from datetime import date
from typing import Any

NOTA_VERSION = "nota-tesis-v1"
PREVISION_VERSION = "prevision-analistas-v1"
HORIZONTES = (1, 3)

#: La nota final: rigor determinista y juez. El juez nunca pasa de una parte menor.
PESO_RIGOR = 0.8
PESO_JUEZ = 0.2

#: Rigor: cada componente vale de 0 a 1; la suma de pesos es 1 y el rigor se da sobre 10.
PESOS_RIGOR: dict[str, float] = {
    "cifras_libres": 0.15,
    "citas_literales": 0.15,
    "metodo_tipo": 0.20,
    "datos_fuente": 0.25,
    "secciones": 0.10,
    "kill_switches": 0.15,
}

FORMULAS_RIGOR: dict[str, str] = {
    "cifras_libres": "0 si quedan cifras sin marcador en el texto final; si no, 1 − (cifras sin marcador de la "
    "primera pasada, sin los falsos positivos 10b5-1/Form 4) / 10, mínimo 0",
    "citas_literales": "1 − (citas atribuidas que no están literales en la evidencia, incluidas las traducidas) "
    "/ citas atribuidas; 1 si no hay citas atribuidas",
    "metodo_tipo": "1 si el método elegido encaja con el tipo de empresa, 0,5 si encaja a medias, 0 si no",
    "datos_fuente": "0,5 × (precio, acciones y deuda neta que cuadran con su cita, de 3) + 0,5 × máx(0, 1 − "
    "0,15 × puntos de AUDIT en datos de entrada; ERROR = 2 puntos, el resto = 1)",
    "secciones": "secciones con contenido / secciones esperadas",
    "kill_switches": "kill switches escritos como umbral de una métrica / kill switches; 0 si no hay",
}

#: Dos etiquetas de la referencia del arnés de expertos que no se sostienen con los datos (el propio
#: informe de expertos-bench-1 dice que ahí «probablemente acierta la app»). Es la etiqueta del conjunto de
#: prueba, no una regla de la app; cada corrección lleva su motivo y se muestra en el informe.
REFERENCIA_CORREGIDA: dict[str, tuple[str, str]] = {
    "HIMS": (
        "operativa",
        "gana dinero desde 2024 (beneficio neto positivo, P/E propio): no es quemadora de caja",
    ),
    "FRPH": ("reit", "FRP Holdings es inmobiliaria (alquileres y derechos sobre terrenos): FFO es su método"),
}

# ----------------------------------------------------------------------------------------- AUDIT

#: Filas de AUDIT que hablan de un dato de entrada (no de la tarjeta DCF ni del método, que se mide aparte).
_DATO = re.compile(
    r"shares|acciones|debt|deuda|revenue|ingresos|income|beneficio|p&l|ebit|fcf|leases|arrend|hybrid|"
    r"h[ií]brid|cash|caja|financial data|fx|minorit",
    re.IGNORECASE,
)
_OK = re.compile(r"^\s*(OK|None|-)?\s*(\(|$)", re.IGNORECASE)


def parse_audit_md(text: str) -> dict[str, list[dict[str, Any]]]:
    """Filas «ticker | dato | app | fuente | enlace | veredicto» de AUDIT.md, solo las que no son OK."""
    out: dict[str, list[dict[str, Any]]] = {}
    in_inputs = False
    for line in text.splitlines():
        if not line.startswith("|"):
            in_inputs = False
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if cells and cells[0].lower() == "ticker":
            # Solo la tabla «ticker | dato | app | fuente | enlace | veredicto», no el resumen de motores.
            in_inputs = len(cells) >= 2 and cells[1].lower() in ("input", "dato")
            continue
        if not in_inputs or line.startswith("|---") or len(cells) < 6:
            continue
        ticker, item, verdict = cells[0], cells[1], cells[-1]
        if _OK.match(verdict):
            continue
        out.setdefault(ticker, []).append(
            {
                "input": item,
                "verdict": verdict,
                "dato": bool(_DATO.search(item)),
                "puntos": 2 if "ERROR" in verdict.upper() else 1,
            }
        )
    return out


def audit_points(flags: Iterable[Mapping[str, Any]]) -> int:
    return sum(int(f.get("puntos") or 0) for f in flags if f.get("dato"))


# ----------------------------------------------------------------------------------------- rigor


def _ratio(num: float, den: float, empty: float = 1.0) -> float:
    return empty if den <= 0 else max(0.0, min(1.0, num / den))


def rigor_components(
    rigor: Mapping[str, Any], audit_flags: Sequence[Mapping[str, Any]] = ()
) -> dict[str, Any]:
    """Componentes de rigor (0–1) a partir de las métricas deterministas del arnés de expertos."""
    gp = rigor.get("guard_problems") or {}
    first_real = max(0, int(gp.get("free_numbers") or 0) - int(gp.get("false_positive_10b5_1") or 0))
    final = int(rigor.get("free_numbers_final") or 0) + int(rigor.get("unknown_markers_final") or 0)
    cifras = 0.0 if final > 0 else max(0.0, 1 - first_real / 10)

    qa = rigor.get("quotes_attributed") or {}
    citas = 1 - _ratio(float(qa.get("not_literal") or 0), float(qa.get("quotes") or 0), empty=0.0)

    m = rigor.get("method") or {}
    metodo = 1.0 if m.get("ok") else (0.5 if m.get("kind_ok") or m.get("partial") else 0.0)

    src = (rigor.get("source") or {}).get("ok") or {}
    src_ok = sum(1 for k in ("price", "shares", "net_debt") if src.get(k))
    pts = audit_points(audit_flags)
    datos = 0.5 * src_ok / 3 + 0.5 * max(0.0, 1 - 0.15 * pts)

    sec = rigor.get("sections") or {}
    secciones = _ratio(float(sec.get("filled") or 0), float(sec.get("expected") or 0), empty=0.0)

    ks = rigor.get("kill_switches") or {}
    kill = _ratio(float(ks.get("as_threshold") or 0), float(ks.get("count") or 0), empty=0.0)

    vals = {
        "cifras_libres": (
            cifras,
            f"final {final}, 1.ª pasada {first_real} (sin {gp.get('false_positive_10b5_1') or 0} FP)",
        ),
        "citas_literales": (
            citas,
            f"{qa.get('not_literal') or 0} de {qa.get('quotes') or 0} no literales"
            f" ({qa.get('translated') or 0} traducidas)",
        ),
        "metodo_tipo": (metodo, f"{m.get('type')} → {m.get('chosen')}"),
        "datos_fuente": (datos, f"cuadran {src_ok}/3; AUDIT {pts} puntos"),
        "secciones": (secciones, f"{sec.get('filled')}/{sec.get('expected')}"),
        "kill_switches": (kill, f"{ks.get('as_threshold')}/{ks.get('count')} como umbral"),
    }
    comps = {
        k: {"valor": round(v, 4), "peso": PESOS_RIGOR[k], "detalle": d, "formula": FORMULAS_RIGOR[k]}
        for k, (v, d) in vals.items()
    }
    total = 10 * sum(c["valor"] * c["peso"] for c in comps.values())
    return {"componentes": comps, "rigor_10": round(total, 2)}


# ----------------------------------------------------------------------------------------- juez

JUEZ_RUBRICA = (
    "Eres el comité de inversión de un inversor value a largo plazo. Te doy dos informes de inversión (A y B). "
    "Pueden ser de la misma empresa o de empresas distintas: puntúa cada uno por su propia calidad, con la "
    "misma vara. No sabes quién los escribió ni cómo; no lo adivines. Puntúa cada criterio de 0 a 5:\n"
    "1. rigor: cada cifra con su fuente; nada inventado; método de valoración adecuado al tipo de empresa.\n"
    "2. tesis: dice con claridad por qué la acción vale más o menos que el precio, y qué hay que creer.\n"
    "3. riesgos: riesgos concretos de la empresa y kill switches medibles (métrica y umbral).\n"
    "4. utilidad: un inversor puede decidir con él (escenarios, qué vigilar, qué descuenta el precio).\n"
    "5. claridad: se lee bien, sin relleno ni repeticiones.\n"
    'La longitud no es un mérito. Responde SOLO con JSON: {"A": {"rigor": n, "tesis": n, "riesgos": n, '
    '"utilidad": n, "claridad": n}, "B": {...}, "preferido": "A" | "B" | "empate", "motivo": str}'
)


def judge_message(text_a: str, text_b: str, limit: int = 60000) -> str:
    return json.dumps({"A": text_a[:limit], "B": text_b[:limit]}, ensure_ascii=False)


def judge_result(first: Mapping[str, Any] | None, swapped: Mapping[str, Any] | None) -> dict[str, Any]:
    """Nuestra tesis X frente al ancla Y: X va de A en la primera pasada y de B en la segunda.

    Nota del juez = media de la nota de X en las dos órdenes (0–5). El ancla da la vara (suelo Numantia).
    """
    xs = [v for v in ((first or {}).get("score_A"), (swapped or {}).get("score_B")) if v is not None]
    ys = [v for v in ((first or {}).get("score_B"), (swapped or {}).get("score_A")) if v is not None]
    if not xs:
        return {"nota_5": None, "ancla_5": None, "delta_vs_ancla": None, "ordenes": 0, "consistente": None}
    x = sum(xs) / len(xs)
    y = sum(ys) / len(ys) if ys else None
    consistent = None
    if first and swapped:
        a = {"A": 1, "B": -1}.get(str(first.get("preferido")), 0)
        b = {"B": 1, "A": -1}.get(str(swapped.get("preferido")), 0)
        consistent = a == b
    return {
        "nota_5": round(x, 3),
        "ancla_5": None if y is None else round(y, 3),
        "delta_vs_ancla": None if y is None else round(x - y, 3),
        "ordenes": len(xs),
        "consistente": consistent,
        "dispersion_ordenes": round(abs(xs[0] - xs[1]), 3) if len(xs) == 2 else None,
    }


def placebo_noise(pairs: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Placebo: la misma tesis en A y en B, dos llamadas (una por orden). Todo lo que se mueva es ruido.

    - dentro de una llamada: diferencia de nota A−B y preferencia por uno de los dos (deberían ser 0);
    - entre llamadas: cuánto cambia la nota del mismo texto de una llamada a otra (el ruido que importa,
      porque la nota del juez de cada tesis es la media de dos llamadas).
    """
    diffs, prefs, n, between = [], 0, 0, []
    for p in pairs:
        calls = [v for v in (p.get("first"), p.get("swapped")) if v and v.get("score_A") is not None]
        for v in calls:
            if v.get("score_B") is None:
                continue
            n += 1
            diffs.append(abs(v["score_A"] - v["score_B"]))
            prefs += v.get("preferido") in ("A", "B")
        if len(calls) == 2:
            between.append(abs(calls[0]["score_A"] - calls[1]["score_A"]))
    if not n:
        return {"n": 0}
    out = {
        "n": n,
        "media_abs_diferencia_5": round(sum(diffs) / n, 3),
        "max_abs_diferencia_5": round(max(diffs), 3),
        "preferencia_espuria": round(prefs / n, 3),
    }
    if between:
        out["entre_llamadas_media_5"] = round(sum(between) / len(between), 3)
        out["entre_llamadas_max_5"] = round(max(between), 3)
        # La nota del juez es la media de 2 llamadas: su error típico es ≈ la mitad de |Δ| entre llamadas.
        out["efecto_max_en_nota_10"] = round(PESO_JUEZ * 2 * max(between) / 2, 3)
    return out


# ----------------------------------------------------------------------------------------- nota


def grade(rigor_10: float | None, judge_5: float | None) -> dict[str, Any]:
    """Nota = 0,8 × rigor (0–10) + 0,2 × juez (0–5 llevado a 0–10). Sin juez, la nota es el rigor y se dice."""
    if rigor_10 is None:
        return {"nota": None, "formula": "sin tesis: sin nota"}
    if judge_5 is None:
        return {"nota": round(rigor_10, 1), "formula": "rigor solo (sin veredicto del juez)"}
    judge_10 = 2 * judge_5
    nota = PESO_RIGOR * rigor_10 + PESO_JUEZ * judge_10
    return {
        "nota": round(nota, 1),
        "juez_10": round(judge_10, 2),
        "formula": f"{PESO_RIGOR} × rigor {rigor_10:.2f} + {PESO_JUEZ} × juez {judge_10:.2f}",
    }


# ----------------------------------------------------------------------------------------- analistas

_SUBUNIT = {
    "GBX": ("GBP", 100.0),
    "GBPENCE": ("GBP", 100.0),
    "GBP_PENCE": ("GBP", 100.0),
    "ZAC": ("ZAR", 100.0),
    "ILA": ("ILS", 100.0),
}


def to_major(value: float | None, currency: str | None) -> tuple[float | None, str | None]:
    if value is None or currency is None:
        return value, currency
    key = "GBX" if currency == "GBp" else currency.upper()
    major, div = _SUBUNIT.get(key, (key, 1.0))
    return value / div, major


def _f(v: Any) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def analyst_gap(
    ours: Mapping[str, Any],
    our_currency: str | None,
    consensus: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Nuestro valor por acción frente al precio objetivo medio del consenso. Mide discrepancia, no acierto."""
    cons = consensus or {}
    if cons.get("status") != "available":
        return {"comparable": False, "motivo": f"sin consenso ({cons.get('status') or 'no consultado'})"}
    mean, ccy = to_major(_f(cons.get("mean")), cons.get("currency"))
    low, _ = to_major(_f(cons.get("low")), cons.get("currency"))
    high, _ = to_major(_f(cons.get("high")), cons.get("currency"))
    our_ccy = (our_currency or "").upper() or None
    base = _f(ours.get("base"))
    if base is None:
        return {
            "comparable": False,
            "motivo": "sin valor por acción propio",
            "consenso_medio": mean,
            "divisa_consenso": ccy,
        }
    if our_ccy and ccy and our_ccy != ccy:
        return {
            "comparable": False,
            "motivo": f"divisas distintas ({our_ccy} frente a {ccy})",
            "consenso_medio": mean,
            "divisa_consenso": ccy,
        }
    if not mean:
        return {"comparable": False, "motivo": "consenso sin media"}
    gap = base / mean - 1
    out = {
        "comparable": True,
        "consenso_medio": round(mean, 4),
        "consenso_bajo": None if low is None else round(low, 4),
        "consenso_alto": None if high is None else round(high, 4),
        "divisa": ccy,
        "base_vs_consenso": round(gap, 4),
        "log_distancia": round(abs(math.log(base / mean)), 4) if base > 0 else None,
        "base_en_rango_analistas": None if low is None or high is None else low <= base <= high,
    }
    for k in ("bear", "bull"):
        v = _f(ours.get(k))
        out[f"{k}_vs_consenso"] = None if v is None else round(v / mean - 1, 4)
    return out


# ----------------------------------------------------------------------------------------- previsiones


def forecast_record(
    *,
    ticker: str,
    as_of: date,
    price: float,
    currency: str | None,
    value_per_share: Mapping[str, Any],
    irr5: Mapping[str, Any] | None,
    method: str | None,
    analyst: Mapping[str, Any] | None,
    thesis_fingerprint: str | None,
    commit: str | None,
    nota: float | None = None,
) -> dict[str, Any]:
    """Una previsión con fecha que guarda a la vez nuestro valor y el objetivo de los analistas."""
    a = dict(analyst or {})
    rec = {
        "v": PREVISION_VERSION,
        "ticker": ticker,
        "as_of": as_of.isoformat(),
        "price": price,
        "currency": currency,
        "method": method,
        "value_per_share": {k: _f(value_per_share.get(k)) for k in ("bear", "base", "bull")},
        "irr5": {k: _f((irr5 or {}).get(k)) for k in ("bear", "base", "bull")},
        "analyst": {
            k: a.get(k)
            for k in (
                "status",
                "mean",
                "median",
                "low",
                "high",
                "currency",
                "n_analysts",
                "n_firms_12m",
                "source",
                "source_url",
                "fetched_at",
                "converted",
            )
        },
        "nota": nota,
        "thesis_fingerprint": thesis_fingerprint,
        "commit": commit,
        "score_at": {
            f"{h}y": date(as_of.year + h, as_of.month, min(as_of.day, 28)).isoformat() for h in HORIZONTES
        },
    }
    rec["id"] = hashlib.sha256(
        json.dumps(
            {k: rec[k] for k in ("ticker", "as_of", "price", "value_per_share", "analyst")},
            sort_keys=True,
            default=str,
        ).encode()
    ).hexdigest()[:16]
    return rec


def score_vs_analysts(
    record: Mapping[str, Any], *, horizon_years: int, price_then: float, dividends_per_share: float = 0.0
) -> dict[str, Any]:
    """Puntúa nuestro valor base y el objetivo medio de los analistas contra el precio real a 1 o 3 años.

    - error = |ln(precio real / valor)|: más pequeño = más cerca;
    - dirección: si el precio real se movió hacia el lado (arriba/abajo del precio de partida) que dijo cada uno.
    El objetivo de analistas es a 12 meses; nuestro valor no tiene plazo. Se dice así en el informe.
    """
    p0 = _f(record.get("price"))
    pt = price_then + dividends_per_share
    out: dict[str, Any] = {
        "ticker": record.get("ticker"),
        "as_of": record.get("as_of"),
        "horizon_years": horizon_years,
        "price_then": price_then,
    }
    if not p0 or pt <= 0:
        return {**out, "ok": False}
    out["ok"] = True
    out["realized_total"] = pt / p0 - 1
    realized_up = pt > p0
    ours = _f((record.get("value_per_share") or {}).get("base"))
    a = record.get("analyst") or {}
    a = a.get("converted") or a  # el objetivo en nuestra divisa cuando se convirtió (tipo anotado)
    target, _ccy = to_major(_f(a.get("mean")), a.get("currency"))
    for name, v in (("nuestro", ours), ("analistas", target)):
        if v is None or v <= 0:
            out[f"error_{name}"] = None
            out[f"direccion_{name}"] = None
            continue
        out[f"error_{name}"] = abs(math.log(pt / v))
        out[f"direccion_{name}"] = (v > p0) == realized_up
    eo, ea = out.get("error_nuestro"), out.get("error_analistas")
    out["mas_cerca"] = (
        None if eo is None or ea is None else ("nuestro" if eo < ea else "analistas" if ea < eo else "empate")
    )
    return out


def summarize_vs(scores: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    both = [s for s in scores if s.get("mas_cerca")]
    if not both:
        return {"n": 0}

    def mean(key: str) -> float:
        return sum(s[key] for s in both) / len(both)

    def hits(key: str) -> float:
        xs = [s[key] for s in both if s.get(key) is not None]
        return sum(xs) / len(xs) if xs else float("nan")

    return {
        "n": len(both),
        "nuestro_mas_cerca": sum(s["mas_cerca"] == "nuestro" for s in both),
        "analistas_mas_cerca": sum(s["mas_cerca"] == "analistas" for s in both),
        "error_medio_nuestro": mean("error_nuestro"),
        "error_medio_analistas": mean("error_analistas"),
        "acierto_direccion_nuestro": hits("direccion_nuestro"),
        "acierto_direccion_analistas": hits("direccion_analistas"),
    }


# ----------------------------------------------------------------------------------------- módulos
# Nota de 0 a 10 por módulo, contra una vara dicha: 10 = ventaja significativa o cero errores.
# Las entradas son números de los informes de cada carril (con su fuente en el JSON de entrada).


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def _module(parts: dict[str, tuple[float, float, str, str]]) -> dict[str, Any]:
    """parts: nombre → (valor 0–1, peso, fórmula, detalle). Nota = 10 × Σ peso × valor."""
    total = sum(w for _, w, _, _ in parts.values())
    comps = {
        k: {"valor": round(v, 4), "peso": w, "formula": f, "detalle": d} for k, (v, w, f, d) in parts.items()
    }
    return {"nota": round(10 * sum(v * w for v, w, _, _ in parts.values()) / total, 1), "componentes": comps}


def grade_valor_intrinseco(x: Mapping[str, Any]) -> dict[str, Any]:
    ic = float(x["ic5_holdout"])
    bias = abs(float(x["sesgo_nivel_pp"]))
    cov = float(x["cobertura_bajista_alcista"])
    return _module(
        {
            "prediccion": (
                _clamp01(ic / 0.10),
                0.4,
                "IC de rangos a 5 años en el holdout 2010–14 (sin fuga) / 0,10",
                f"IC {ic:+.3f}",
            ),
            "calibracion": (
                _clamp01(1 - bias / 10) * _clamp01(cov / 0.8),
                0.2,
                "(1 − |sesgo de nivel| / 10 pp) × mín(1, cobertura bajista–alcista / 80 %)",
                f"sesgo {bias:.1f} pp, cobertura {cov:.0%}",
            ),
            "datos_fuente": (
                float(x["datos_ok"]) / float(x["datos_total"]),
                0.2,
                "datos de entrada que cuadran con la fuente primaria / revisados (AUDIT, 24 empresas)",
                f"{x['datos_ok']} de {x['datos_total']}",
            ),
            "metodo_tipo": (
                float(x["metodo_ok"]) / float(x["metodo_total"]),
                0.2,
                "tesis con el método del tipo de empresa / tesis (las a medias cuentan 0,5)",
                f"{x['metodo_ok']} de {x['metodo_total']}",
            ),
        }
    )


def grade_dca(x: Mapping[str, Any]) -> dict[str, Any]:
    edge, lo = float(x["ventaja_mediana_pp"]), float(x["ic95_bajo_pp"])
    sig = 1.0 if lo > 0 else 0.5
    return _module(
        {
            "ventaja": (
                _clamp01(edge / 2.0) * sig,
                0.7,
                "mín(1, ventaja mediana sobre DCA plano / 2 pp) × (1 si el IC 95 % excluye 0; si no, 0,5)",
                f"+{edge:.2f} pp, IC 95 % {lo:+.2f} a {float(x['ic95_alto_pp']):+.2f}",
            ),
            "correccion": (
                float(x["tests_ok"]) / float(x["tests_total"]),
                0.3,
                "tests de reglas (zonas, avisos, importes) que pasan / tests",
                f"{x['tests_ok']}/{x['tests_total']}",
            ),
        }
    )


def grade_cerebro(x: Mapping[str, Any]) -> dict[str, Any]:
    inv = int(x["cifras_inventadas"])
    out = _module(
        {
            "aciertos": (
                float(x["aciertos"]) / float(x["casos"]),
                0.6,
                "casos que pasan los controles / casos",
                f"{x['aciertos']}/{x['casos']}",
            ),
            "juez": (
                float(x["juez_5"]) / 5,
                0.2,
                "nota media del juez ciego / 5",
                f"{float(x['juez_5']):.2f}/5",
            ),
            "latencia": (
                _clamp01(10 / float(x["p95_s"])),
                0.2,
                "mín(1, 10 s / latencia p95)",
                f"p95 {float(x['p95_s']):.1f} s",
            ),
        }
    )
    if inv > 0:  # una cifra inventada es un error grave: la nota se parte por la mitad
        out["nota"] = round(out["nota"] / 2, 1)
    out["cifras_inventadas"] = inv
    return out


def grade_equipo(x: Mapping[str, Any]) -> dict[str, Any]:
    return _module(
        {
            "aporte": (
                float(x["roles_con_aporte"]) / float(x["roles_evaluados"]),
                0.5,
                "roles o entradas con aporte medible (juez ciego, p < 0,10) / evaluados",
                f"{x['roles_con_aporte']} de {x['roles_evaluados']}",
            ),
            "suelo_numantia": (
                float(x["tesis_en_suelo"]) / float(x["tesis_juzgadas"]),
                0.5,
                "tesis que igualan o superan el ancla de Numantia en el juez / tesis juzgadas",
                f"{x['tesis_en_suelo']} de {x['tesis_juzgadas']}",
            ),
        }
    )
