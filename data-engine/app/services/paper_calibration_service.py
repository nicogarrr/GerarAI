"""Calibracion de la conviction de las propuestas LLM (paper trading).

Mide si la conviction declarada se corresponde con la tasa de acierto observada.
Acierto = retorno bruto > 0 al cierre (el mismo criterio que hit_rate del
scoreboard). Todo es INFERIDO: la conviction la declara el LLM. Sin muestra
suficiente se devuelve N/D con aviso, nunca un 0 ni un porcentaje de 2 casos.
"""
from collections import defaultdict
from datetime import UTC, datetime
from decimal import Decimal

from app.models.paper_trading import PaperTrade
from app.services.paper_trading_service import pnl

MIN_CLOSED = 30  # por debajo, la calibracion es orientativa y se avisa
MIN_BIN = 5  # por debajo, la tasa del bin es N/D
LABEL = "INFERIDO"
BASIS = (
    "acierto = retorno bruto > 0 al cierre; comisiones y spread modelados aparte "
    "(supuesto persistido por trade, ver scoreboard neto); dividendos declarados "
    "aplicados con fuente (Yahoo/FMP; eventos inciertos excluidos; otra divisa "
    "nunca convertida); splits en abierto ajustados con fuente (una cerrada con "
    "split no se reescribe y queda excluida del acierto); sin FX, cash ledger ni "
    "financiación de cortos; conviction declarada por el LLM"
)


def _bin_edges(n_closed: int) -> list[tuple[float, float]]:
    if n_closed >= MIN_CLOSED:
        return [(i / 10, (i + 1) / 10) for i in range(10)]
    return [(0.0, 0.5), (0.5, 0.75), (0.75, 1.0)]


def _bin_label(low: float, high: float) -> str:
    return f"{low:.2f}-{high:.2f}"


def calibration(rows: list[PaperTrade], now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    llm = [r for r in rows if r.author == "LLM"]
    closed: list[tuple[PaperTrade, Decimal]] = []
    for row in llm:
        if row.status != "closed":
            continue
        if row.corporate_action_warning:
            continue  # misma regla que scoreboard(): una cerrada con split no es comparable
        result = pnl(row, row.exit_price)
        if result is not None:
            closed.append((row, result))
    n = len(closed)
    out: dict = {
        "etiqueta": LABEL,
        "base": BASIS,
        "calculado_en": now.astimezone(UTC).isoformat(),
        "propuestas_llm": len(llm),
        "cerradas_con_resultado": n,
        "muestra_insuficiente": n < MIN_CLOSED,
        "minimo_cerradas": MIN_CLOSED,
        "aviso": (
            f"Muestra insuficiente ({n} cerradas, mínimo {MIN_CLOSED}): la calibración es orientativa"
            if n < MIN_CLOSED
            else None
        ),
        "brier": None,
        "brier_referencia_sin_informacion": None,
        "bins": [],
        "pnl_por_horizonte": [],
        "cierres_por_motivo": {},
    }
    if not closed:
        return out
    hits = [(float(r.conviction), 1.0 if res > 0 else 0.0) for r, res in closed]
    out["brier"] = sum((p - y) ** 2 for p, y in hits) / n
    base_rate = sum(y for _, y in hits) / n
    # Brier de predecir siempre la tasa media: referencia para saber si la conviction aporta.
    out["brier_referencia_sin_informacion"] = sum((base_rate - y) ** 2 for _, y in hits) / n

    reasons: dict[str, int] = defaultdict(int)
    for row, _ in closed:
        reasons[f"{row.horizon}:{row.close_reason or 'sin_dato'}"] += 1
    out["cierres_por_motivo"] = dict(sorted(reasons.items()))

    edges = _bin_edges(n)
    for index, (low, high) in enumerate(edges):
        last = index == len(edges) - 1
        sample = [
            (r, res) for r, res in closed
            # nosemgrep: gerarai-float-equality -- limite superior inclusivo del ultimo tramo de conviccion (valores discretos); igualdad intencionada
            if low <= float(r.conviction) < high or (last and float(r.conviction) == high)
        ]
        size = len(sample)
        enough = size >= MIN_BIN
        mean_conviction = sum(float(r.conviction) for r, _ in sample) / size if size else None
        observed = sum(res > 0 for _, res in sample) / size if enough else None
        pnl_by_currency: dict[str, list[Decimal]] = defaultdict(list)
        for r, res in sample:
            pnl_by_currency[r.currency or "sin_datos"].append(res)
        out["bins"].append({
            "rango": _bin_label(low, high),
            "cerradas": size,
            "conviction_media": mean_conviction if enough else None,
            "tasa_acierto": observed,
            "hueco": (observed - mean_conviction) if observed is not None and mean_conviction is not None else None,
            "pnl_medio_por_divisa": (
                {c: sum(v, Decimal(0)) / len(v) for c, v in sorted(pnl_by_currency.items())} if enough else None
            ),
            "etiqueta": LABEL if enough else "N/D",
            "aviso": None if enough else f"menos de {MIN_BIN} cerradas: tasa N/D",
        })

    groups: dict[tuple[str, str], list[Decimal]] = defaultdict(list)
    for row, res in closed:
        groups[(row.horizon, row.currency or "sin_datos")].append(res)
    out["pnl_por_horizonte"] = [
        {
            "horizonte": horizon,
            "divisa": currency,
            "cerradas": len(values),
            "pnl_realizado": sum(values, Decimal(0)),
            "pnl_medio": sum(values, Decimal(0)) / len(values),
            "tasa_acierto": (sum(v > 0 for v in values) / len(values)) if len(values) >= MIN_BIN else None,
        }
        for (horizon, currency), values in sorted(groups.items())
    ]
    return out
