"""Flujos de dinero por tema: quién gasta → a dónde va → quién cobra.

Diseño reutilizable: un tema es una CONFIGURACIÓN DECLARADA (FLOW_THEMES), no
código ad hoc. Cada empresa/tema lleva su razón verificable, igual que las
cestas de market_themes (REASONS).

Regla de veracidad (la misma que Temas y Cuellos): toda cifra es
- REPORTADA: fuente oficial enlazable (filing SEC/ESEF con accession, o la API
  pública de USAspending), o
- ESTIMACIÓN DE TERCEROS: citada con atribución explícita y nunca presentada
  como dato propio, o
- no se muestra.

Sin inferencia de importes: donde no existe fuente gratuita del reparto (qué
parte del capex de GOOGL llega a NVDA), amount=None con razón declarada;
jamás una ponderación inventada.
"""
from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

import httpx
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from app.models import Company, Document, FinancialFact

# ---------------------------------------------------------------------------
# Configuración declarativa de temas
# ---------------------------------------------------------------------------

# Kinds de fuente admitidos. Cualquier otro valor es un error de configuración.
KIND_REPORTADO = "reportado"
KIND_ESTIMACION_TERCEROS = "estimacion_terceros"


@dataclass(frozen=True)
class SpenderConfig:
    key: str                    # ticker ("GOOGL") o clave externa ("us-dod")
    label: str
    kind: str                   # "sec_capex" | "usaspending_agency"
    ticker: str | None = None
    reason: str | None = None   # hecho verificable sobre su papel
    agency_name: str | None = None  # nombre toptier en USAspending


@dataclass(frozen=True)
class DestinationConfig:
    """Destino estático: sólo estimaciones de terceros citadas con atribución."""
    label: str
    amount: float | None
    source_label: str
    source_url: str | None = None


@dataclass(frozen=True)
class SupplierConfig:
    ticker: str | None
    name: str
    reason: str                 # hecho verificable: por qué cobra de este flujo


@dataclass(frozen=True)
class FlowTheme:
    id: str
    name: str
    tagline: str
    spenders: tuple[SpenderConfig, ...]
    suppliers: tuple[SupplierConfig, ...]
    # Destinos estáticos (terceros, atribuidos). Si destinations_live es
    # "usaspending_psc", los destinos salen en vivo de la API oficial.
    destinations: tuple[DestinationConfig, ...] = ()
    destinations_live: str | None = None
    # Si suppliers_live es "usaspending_recipients", los cobradores salen en
    # vivo de USAspending y se mapean a tickers con RECIPIENT_TICKER_MAP.
    suppliers_live: str | None = None
    agency_name: str | None = None
    agency_slug: str | None = None
    method: str = ""
    limitation: str = ""


# --- Tema 1: capex de IA (hyperscalers y neoclouds) -------------------------

_CAPEX_IA_SPENDERS = (
    SpenderConfig("GOOGL", "Alphabet (Google)", "sec_capex", ticker="GOOGL",
                  reason="Reporta su capex trimestral en el 10-Q (infraestructura técnica: servidores y centros de datos)."),
    SpenderConfig("MSFT", "Microsoft", "sec_capex", ticker="MSFT",
                  reason="Reporta su capex trimestral en el 10-Q; la guía de la empresa lo vincula a la demanda de Azure e IA."),
    SpenderConfig("AMZN", "Amazon", "sec_capex", ticker="AMZN",
                  reason="Reporta el capex como 'productive assets' en el 10-Q, mayoritariamente AWS."),
    SpenderConfig("META", "Meta", "sec_capex", ticker="META",
                  reason="Reporta su capex trimestral en el 10-Q y da guía anual ligada a IA en sus presentaciones de resultados."),
    SpenderConfig("ORCL", "Oracle", "sec_capex", ticker="ORCL",
                  reason="Reporta su capex trimestral en el 10-Q; su backlog (RPO) lo vincula a contratos de nube e IA."),
    SpenderConfig("CRWV", "CoreWeave", "sec_capex", ticker="CRWV",
                  reason="Neocloud cotizada: reporta su capex en el 10-Q; su negocio es alquilar GPUs a terceros."),
    SpenderConfig("NBIS", "Nebius", "sec_capex", ticker="NBIS",
                  reason="Neocloud cotizada: reporta su capex en sus filings (20-F/6-K); negocio de infraestructura de IA."),
)

# Estimación de Morgan Stanley Research (2027E) aportada por el usuario como
# captura el 2026-10-20. Es modelado de analistas: no existe fuente gratuita
# que la replique y su propia nota excluye 136 B$ de HBM. Se cita SIEMPRE con
# atribución y nunca como dato propio. La suma de destinos (1.734 B$) supera
# la de fuentes (1.583 B$): inconsistencia interna del gráfico original, que
# declaramos en `limitation` en vez de ocultarla.
_CAPEX_IA_DESTINATIONS = (
    DestinationConfig("Chips de IA y servidores", 672e9, "Morgan Stanley Research 2027E"),
    DestinationConfig("Internacional", 511e9, "Morgan Stanley Research 2027E"),
    DestinationConfig("Memoria (HBM y otra)", 217e9, "Morgan Stanley Research 2027E"),
    DestinationConfig("Red y óptica", 215e9, "Morgan Stanley Research 2027E"),
    DestinationConfig("Infraestructura de centros de datos y energía", 119e9, "Morgan Stanley Research 2027E"),
)

_CAPEX_IA_SUPPLIERS = (
    SupplierConfig("NVDA", "NVIDIA", "Sus GPUs y el ecosistema CUDA son el acelerador dominante en los centros de datos de IA."),
    SupplierConfig("AVGO", "Broadcom", "Diseña chips de red (Tomahawk/Jericho) y aceleradores a medida (XPU) para hyperscalers."),
    SupplierConfig("MRVL", "Marvell", "Chips a medida e interconexión óptica (DSP) para centros de datos de IA."),
    SupplierConfig("ANET", "Arista Networks", "Switches Ethernet de centros de datos; sus mayores clientes son hyperscalers."),
    SupplierConfig("VRT", "Vertiv", "Refrigeración y distribución eléctrica de centros de datos."),
    SupplierConfig("ETN", "Eaton", "Equipos eléctricos de media tensión y distribución para centros de datos."),
    SupplierConfig("MU", "Micron", "Único fabricante estadounidense de memoria; vende HBM para aceleradores de IA."),
    SupplierConfig("TSM", "TSMC", "Fabrica (foundry) la mayoría de los chips avanzados de IA diseñados por terceros."),
    SupplierConfig("ASML", "ASML", "Monopolio de la litografía EUV necesaria para fabricar chips avanzados."),
    SupplierConfig("DELL", "Dell Technologies", "Servidores con GPUs para IA; monta racks para empresas y neoclouds."),
    SupplierConfig("SMCI", "Super Micro Computer", "Servidores y racks con GPUs, gran parte ligada a NVIDIA."),
    SupplierConfig("SNPS", "Synopsys", "Herramientas EDA: software necesario para diseñar chips."),
)

# --- Tema 2: defensa de EE. UU. (fuente oficial: USAspending) ----------------

# Mapeo curado recipiente → ticker. La razón de cada entrada es verificable en
# el 10-K de la matriz (filial) o en la propia USAspending. None = no mapeamos
# a ticker (privada o fuera del universo cubierto); se muestra el nombre oficial.
# Claves en MAYÚSCULAS; casa por subcadena, de más específica a más genérica.
RECIPIENT_TICKER_MAP: tuple[tuple[str, str | None, str | None], ...] = (
    ("SIKORSKY", "LMT", "Filial de Lockheed Martin (helicópteros)."),
    ("LOCKHEED MARTIN", "LMT", "Mayor contratista de defensa de EE. UU. por obligaciones."),
    ("ELECTRIC BOAT", "GD", "Filial de General Dynamics (submarinos)."),
    ("GENERAL DYNAMICS", "GD", "Contratista de defensa (Gulfstream, combat systems, GDIT)."),
    ("RAYTHEON", "RTX", "Filial de RTX (misiles y defensa aérea)."),
    ("RTX CORPORATION", "RTX", "Matriz de Raytheon, Collins y Pratt & Whitney."),
    ("BOEING", "BA", "Defensa (cazas, misiles, espacio) dentro de Boeing."),
    ("NORTHROP GRUMMAN", "NOC", "Contratista de defensa (bombarderos, espacio, misiles)."),
    ("HUNTINGTON INGALLS", "HII", "Astilleros militares (portaaviones y destructores)."),
    ("L3HARRIS", "LHX", "Electrónica de defensa y comunicaciones."),
    ("GENERAL ELECTRIC", "GE", "GE Aerospace: motores de aviación militar."),
    ("LEIDOS", "LDOS", "Servicios de defensa e inteligencia."),
    ("AMERISOURCEBERGEN", "COR", "Filial de Cencora: distribución farmacéutica al sistema sanitario militar."),
    ("HUMANA", "HUM", "Gestiona parte del seguro sanitario militar (TRICARE)."),
    ("TRIWEST", None, "Gestora de TRICARE; empresa privada, sin ticker."),
    ("BAE SYSTEMS", None, "Contratista británica (BA. en Londres), fuera del universo US."),
    ("GENERAL ATOMICS", None, "Drones MQ-9; empresa privada, sin ticker."),
    ("MCKESSON", "MCK", "Distribución farmacéutica al sistema sanitario militar."),
    ("ATLANTIC DIVING", None, "Suministros; empresa privada, sin ticker."),
)

# Etiquetas en español para las categorías PSC más frecuentes. Las no mapeadas
# se muestran con su etiqueta oficial en inglés (es el nombre de la fuente).
PSC_LABELS_ES: dict[str, str] = {
    "1510": "Aviones de ala fija",
    "1905": "Buques de guerra",
    "1410": "Misiles guiados",
    "2840": "Motores de aviación militar",
    "R425": "Servicios de ingeniería y soporte técnico",
    "R499": "Otros servicios profesionales",
    "Q201": "Sanidad militar (TRICARE)",
    "AC13": "I+D de defensa (desarrollo experimental)",
    "1680": "Componentes de aeronaves",
    "4920": "Mantenimiento de aeronaves",
}

_USASPENDING_BASE = "https://api.usaspending.gov/api/v2"
_USASPENDING_AGENCY_URL = "https://www.usaspending.gov/agency/department-of-defense"
_CACHE_TTL = 3600.0
_NEGATIVE_CACHE_TTL = 120.0  # fallos de USAspending: no martillear la API
_cache: dict[str, tuple[float, object]] = {}
_cache_lock = threading.RLock()


def _fy_window(today: date | None = None) -> tuple[str, str, str]:
    """Último año fiscal federal COMPLETO y publicado con margen.

    El DoD publica sus contratos con 90 días de retraso (declarado en la propia
    ficha de la agencia en USAspending), así que se exige que el FY terminase
    hace >=120 días; si no, se usa el anterior. Devuelve (inicio, fin, etiqueta).
    """
    today = today or datetime.now(UTC).date()
    fy_end_year = today.year if today > date(today.year, 9, 30) else today.year - 1
    if (today - date(fy_end_year, 9, 30)).days < 120:
        fy_end_year -= 1
    start = date(fy_end_year - 1, 10, 1)
    end = date(fy_end_year, 9, 30)
    label = f"FY{fy_end_year} federal (oct {start.year}–sep {end.year})"
    return start.isoformat(), end.isoformat(), label


def _usaspending_post(path: str, payload: dict) -> dict:
    response = httpx.post(f"{_USASPENDING_BASE}{path}", json=payload, timeout=25)
    response.raise_for_status()
    return response.json()


def _agency_filter(agency_name: str, start: str, end: str) -> dict:
    return {
        "time_period": [{"start_date": start, "end_date": end}],
        "agencies": [{"type": "awarding", "tier": "toptier", "name": agency_name}],
    }


def fetch_agency_obligations(agency_name: str, start: str, end: str) -> float:
    """Obligaciones (contratos + ayudas) de la agencia en la ventana.

    OJO: el dato de 'awards' de USAspending NO incluye personal ni operaciones
    internas; por eso la UI lo etiqueta como obligaciones de contratos/ayudas,
    nunca como 'presupuesto del Pentágono'.
    """
    payload = {
        "filters": _agency_filter(agency_name, start, end),
        "group": "fiscal_year",
        "spending_type": "obligations",
    }
    data = _usaspending_post("/search/spending_over_time/", payload)
    results = data.get("results") or []
    if not results:
        raise RuntimeError("USAspending no devolvió obligaciones para la ventana")
    return float(results[0]["aggregated_amount"])


def fetch_top_categories(agency_name: str, start: str, end: str, limit: int = 8) -> list[dict]:
    payload = {"filters": _agency_filter(agency_name, start, end), "limit": limit}
    data = _usaspending_post("/search/spending_by_category/psc/", payload)
    return data.get("results") or []


def fetch_top_recipients(agency_name: str, start: str, end: str, limit: int = 30) -> list[dict]:
    payload = {"filters": _agency_filter(agency_name, start, end), "limit": limit}
    data = _usaspending_post("/search/spending_by_category/recipient/", payload)
    return data.get("results") or []


_NORMALIZE_RE = re.compile(r"[^A-Z0-9 ]+")


def normalize_recipient(name: str) -> str:
    """Mayúsculas, sin puntuación ni sufijos societarios redundantes."""
    folded = _NORMALIZE_RE.sub(" ", name.upper())
    folded = re.sub(r"\b(CORPORATION|CORP|INCORPORATED|INC|LLC|COMPANY|CO)\b", "", folded)
    return re.sub(r"\s+", " ", folded).strip()


def aggregate_recipients(results: list[dict], top: int = 12) -> list[dict]:
    """Suma los recipientes con el mismo nombre normalizado.

    USAspending devuelve entidades jurídicas distintas que comparten nombre
    (p. ej. LOCKHEED MARTIN CORPORATION aparece con varios recipient_id); sin
    esta agregación el mismo gastador saldría tres veces.
    """
    totals: dict[str, float] = {}
    display: dict[str, str] = {}
    for row in results:
        name = (row.get("name") or "").strip()
        if not name:
            continue
        key = normalize_recipient(name)
        if not key:
            continue
        # nosemgrep: gerarai-money-none-to-zero -- agregado informativo de filings/flujos (ranking/listado): una fila sin cifra no suma; no es un importe del usuario
        totals[key] = totals.get(key, 0.0) + float(row.get("amount") or 0.0)
        display.setdefault(key, name)
    ordered = sorted(totals.items(), key=lambda item: item[1], reverse=True)[:top]
    return [{"name": display[key], "amount": amount} for key, amount in ordered]


def map_recipient_to_ticker(name: str) -> tuple[str | None, str | None]:
    """(ticker, nota) por subcadena, clave más específica primero."""
    folded = name.upper()
    for key, ticker, note in RECIPIENT_TICKER_MAP:
        if key in folded:
            return ticker, note
    return None, None


def _cached(key: str, loader) -> Any:
    now = time.monotonic()
    with _cache_lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < _CACHE_TTL:
            return hit[1]
    value = loader()
    with _cache_lock:
        _cache[key] = (now, value)
    return value


# ---------------------------------------------------------------------------
# Lectura de capex reportado (SEC/ESEF vía financial_facts compartidos)
# ---------------------------------------------------------------------------

def _latest_quarterly_fact(
    db: Session, company_id: int, metric: str, tenant: int | None
) -> FinancialFact | None:
    tenant_clause = (
        or_(FinancialFact.tenant_id == tenant, FinancialFact.tenant_id.is_(None))
        if isinstance(tenant, int)
        else FinancialFact.tenant_id.is_(None)
    )
    rows = db.scalars(
        select(FinancialFact)
        .where(
            tenant_clause,
            FinancialFact.company_id == company_id,
            FinancialFact.metric == metric,
            FinancialFact.source_type.in_(["SEC", "ESEF"]),
            FinancialFact.is_reported.is_(True),
            FinancialFact.fiscal_quarter.in_(["Q1", "Q2", "Q3", "Q4"]),
        )
        .options(selectinload(FinancialFact.source))
        .order_by(
            # SEC quarterly ingestion leaves fiscal_year=None. The canonical
            # ISO period end is comparable across fiscal calendars and sources.
            FinancialFact.period.desc(),
            FinancialFact.id.desc(),
        )
    ).all()
    return rows[0] if rows else None


def period_label(fact: FinancialFact) -> str:
    """'2026-03-31:Q1' → 'Q1 2026' (etiqueta legible, sin inventar periodo)."""
    try:
        end, fp = fact.period.rsplit(":", 1)
        year = end[:4]
        return f"{fp} {year}" if fp != "FY" else f"FY {year}"
    except (ValueError, IndexError):
        return fact.period


def fact_source(fact: FinancialFact) -> dict:
    document: Document | None = fact.source
    url = document.source_url if document is not None else None
    accn = fact.accession_number
    return {
        "kind": KIND_REPORTADO,
        "label": f"{fact.source_type} · {period_label(fact)}"
        + (f" · accession {accn}" if accn else ""),
        "url": url,
        "note": None if url else "Filing referenciado por accession; sin enlace directo guardado",
    }


# ---------------------------------------------------------------------------
# Construcción del payload
# ---------------------------------------------------------------------------

def build_sec_spender(db: Session, cfg: SpenderConfig, tenant: int | None) -> dict:
    base = {
        "key": cfg.key,
        "label": cfg.label,
        "ticker": cfg.ticker,
        "amount": None,
        "unit": "USD",
        "period_label": None,
        "source": None,
        "reason": cfg.reason,
        "note": None,
        "extra_amount": None,
        "extra_label": None,
        "extra_source": None,
    }
    company = db.scalar(select(Company).where(Company.ticker == cfg.ticker))
    if company is None:
        base["note"] = "Sin datos SEC en la app todavía"
        return base
    capex = _latest_quarterly_fact(db, company.id, "capital_expenditure", tenant)
    if capex is None:
        base["note"] = "Sin capex trimestral reportado en los datos de la app"
        return base
    base.update(
        # Both legacy positive capex and SEC negative cash-flow outflows
        # represent spending here. Do not subtract a spender from the total.
        amount=abs(float(capex.value)),
        unit=capex.unit,
        period_label=period_label(capex),
        source=fact_source(capex),
    )
    lease = _latest_quarterly_fact(db, company.id, "finance_lease_additions", tenant)
    if lease is not None and lease.period == capex.period:
        base.update(
            extra_amount=float(lease.value),
            extra_label="Leases financieros nuevos (mismo periodo)",
            extra_source=fact_source(lease),
        )
    return base


def build_usaspending_theme(
    theme: FlowTheme,
) -> tuple[list[dict], list[dict], list[dict], str, list[str], str | None, str | None]:
    """Tema alimentado por la API oficial de USAspending (defensa)."""
    start, end, fy_label = _fy_window()
    agency = theme.agency_name
    spenders: list[dict] = []
    destinations: list[dict] = []
    suppliers: list[dict] = []
    notes: list[str] = []
    for cfg in theme.spenders:
        spender = {
            "key": cfg.key,
            "label": cfg.label,
            "ticker": cfg.ticker,
            "amount": None,
            "unit": "USD",
            "period_label": fy_label,
            "source": {
                "kind": KIND_REPORTADO,
                "label": f"USAspending.gov · {fy_label}",
                "url": _USASPENDING_AGENCY_URL,
                "note": "Obligaciones de contratos y ayudas; no incluye personal ni operaciones internas",
            },
            "reason": cfg.reason,
            "note": None,
            "extra_amount": None,
            "extra_label": None,
            "extra_source": None,
        }
        spenders.append(spender)
    try:
        with _cache_lock:
            failure = _cache.get(f"fail:{agency}")
        if failure is not None and time.monotonic() - failure[0] < _NEGATIVE_CACHE_TTL:
            raise RuntimeError("USAspending falló hace <2 min (caché negativa)")
        total = _cached(f"oblig:{agency}:{start}", lambda: fetch_agency_obligations(agency, start, end))
        spenders[0]["amount"] = total
        psc = _cached(f"psc:{agency}:{start}", lambda: fetch_top_categories(agency, start, end))
        for row in psc:
            code = str(row.get("code") or "")
            label = PSC_LABELS_ES.get(code, row.get("name") or code)
            destinations.append({
                "label": label,
                # nosemgrep: gerarai-money-none-to-zero -- agregado informativo de filings/flujos (ranking/listado): una fila sin cifra no suma; no es un importe del usuario
                "amount": float(row.get("amount") or 0.0),
                "unit": "USD",
                "source": {
                    "kind": KIND_REPORTADO,
                    "label": f"USAspending.gov · categoría PSC {code} · {fy_label}",
                    "url": _USASPENDING_AGENCY_URL,
                    "note": None if code in PSC_LABELS_ES else "Etiqueta oficial de la fuente, en inglés",
                },
            })
        recipients = _cached(
            f"recip:{agency}:{start}", lambda: fetch_top_recipients(agency, start, end)
        )
        for row in aggregate_recipients(recipients):
            ticker, note = map_recipient_to_ticker(row["name"])
            suppliers.append({
                "ticker": ticker,
                "name": row["name"],
                "amount": float(row["amount"]),
                "unit": "USD",
                "reason": note
                or ("Sin mapeo a ticker declarado" if ticker is None else "Contratista según USAspending"),
                "note": f"Obligaciones {fy_label}" ,
                "source": {
                    "kind": KIND_REPORTADO,
                    "label": f"USAspending.gov · {fy_label}",
                    "url": _USASPENDING_AGENCY_URL,
                    "note": None,
                },
            })
    except (httpx.HTTPError, RuntimeError, ValueError, KeyError) as exc:
        with _cache_lock:
            _cache[f"fail:{agency}"] = (time.monotonic(), None)
        notes.append(f"USAspending no disponible ahora mismo ({type(exc).__name__}); sin cifras en lugar de inventarlas")
        spenders[0]["note"] = "USAspending no disponible ahora mismo"
    # (5) cobertura declarada: los tops son "principales", no el total
    total_amount = spenders[0]["amount"]
    if total_amount:
        psc_sum = sum(item["amount"] for item in destinations)
        rec_sum = sum(item["amount"] for item in suppliers if item["amount"] is not None)
        destinations_note = (
            f"Principales categorías: cubren el {psc_sum / total_amount * 100:.0f} % de lo obligado"
            if destinations else None
        )
        suppliers_note = (
            f"Principales recipientes: cubren el {rec_sum / total_amount * 100:.0f} % de lo obligado"
            if suppliers else None
        )
    else:
        destinations_note = None
        suppliers_note = None
    return spenders, destinations, suppliers, fy_label, notes, destinations_note, suppliers_note


def build_theme_payload(db: Session, theme: FlowTheme, tenant: int | None) -> dict:
    if theme.destinations_live == "eia_retail_revenue":
        from app.services.energy_flows import build_energy_flow

        return build_energy_flow(theme)
    if theme.suppliers_live == "usaspending_recipients":
        spenders, destinations, suppliers, fy_label, notes, destinations_note, suppliers_note = (
            build_usaspending_theme(theme)
        )
        generated_at = datetime.now(UTC)
    else:
        spenders = [build_sec_spender(db, cfg, tenant) for cfg in theme.spenders]
        destinations = [
            {
                "label": item.label,
                "amount": item.amount,
                "unit": "USD",
                "source": {
                    "kind": KIND_ESTIMACION_TERCEROS,
                    "label": item.source_label,
                    "url": item.source_url,
                    "note": "Estimación de analistas; no verificable con fuentes gratuitas",
                },
            }
            for item in theme.destinations
        ]
        suppliers = [
            {
                "ticker": item.ticker,
                "name": item.name,
                "amount": None,
                "unit": "USD",
                "reason": item.reason,
                "note": "Sin reparto público verificable: no hay fuente gratuita de cuánto le compra cada gastador",
                "source": None,
            }
            for item in theme.suppliers
        ]
        fy_label = None
        notes = []
        destinations_note = None
        suppliers_note = "Sin importes: no hay fuente gratuita del reparto por proveedor"
        generated_at = datetime.now(UTC)
    # (3)+(4) total solo de importes en USD, declarando cuántos gastadores entran
    usd_amounts = [
        s["amount"] for s in spenders if s["amount"] is not None and s["unit"] == "USD"
    ]
    total = None
    if usd_amounts and theme.suppliers_live != "usaspending_recipients":
        included = len(usd_amounts)
        total = {
            "amount": sum(usd_amounts),
            "unit": "USD",
            "note": (
                f"{included} de {len(spenders)} gastadores incluidos (solo USD reportado); "
                "los periodos no coinciden necesariamente entre empresas"
            ),
        }
    return {
        "id": theme.id,
        "name": theme.name,
        "tagline": theme.tagline,
        "generated_at": generated_at,
        "period_label": fy_label,
        "spenders": spenders,
        "spenders_total": total,
        "destinations": destinations,
        "suppliers": suppliers,
        "method": theme.method,
        "limitation": theme.limitation,
        "notes": notes,
        "destinations_note": destinations_note,
        "suppliers_note": suppliers_note,
    }


FLOW_THEMES: dict[str, FlowTheme] = {
    "utilities": FlowTheme(
        id="utilities", name="Electricidad de EE. UU.",
        tagline="Gasto eléctrico por sector y quién lo recibe, sin repartirlo entre empresas",
        spenders=(), suppliers=(), destinations_live="eia_retail_revenue",
        method="EIA API v2, retail-sales: ingresos anuales reportados, US Total, millones de dólares convertidos a USD",
        limitation="Solo electricidad al por menor en EE. UU., no todo el sector energético ni capex. Gasto del cliente e ingreso del vendedor son el mismo flujo: no se suman. Sin reparto verificable por empresa ni exposición cuantificada de cartera. Datos revisables.",
    ),
    # Clave = id de la cesta de Temas (market_themes.BASKETS): el flujo se
    # muestra dentro del detalle del tema, no como página aparte.
    "centros-de-datos": FlowTheme(
        id="centros-de-datos",
        name="Capex de IA",
        tagline="Quién financia la buildout de IA y quién cobra de ella",
        spenders=_CAPEX_IA_SPENDERS,
        destinations=_CAPEX_IA_DESTINATIONS,
        suppliers=_CAPEX_IA_SUPPLIERS,
        method="Capex trimestral reportado (SEC/ESEF, enlazado a su filing) + reparto estimado por Morgan Stanley Research 2027E, citado con atribución",
        limitation=(
            "El reparto por categorías es estimación de analistas: su propia fuente suma 1.583 B$ contra "
            "destinos por 1.734 B$ (+151 B$ sin explicar) y excluye 136 B$ de memoria HBM. No hay fuente "
            "gratuita del reparto por proveedor: las empresas de 'quién cobra' van con su razón declarada, sin importe."
        ),
    ),
    "defensa": FlowTheme(
        id="defensa",
        name="Defensa de EE. UU.",
        tagline="Del presupuesto federal a los contratistas",
        spenders=(
            SpenderConfig(
                "us-dod",
                "Departamento de Defensa de EE. UU.",
                "usaspending_agency",
                reason="Mayor agencia federal por obligaciones de contratos y ayudas.",
                agency_name="Department of Defense",
            ),
        ),
        suppliers=(),
        suppliers_live="usaspending_recipients",
        destinations_live="usaspending_psc",
        agency_name="Department of Defense",
        agency_slug="department-of-defense",
        method="Obligaciones de contratos y ayudas de USAspending.gov (API oficial), último año fiscal completo",
        limitation=(
            "USAspending no incluye personal ni operaciones internas del DoD (solo 'awards'), y los contratos "
            "del DoD se publican con 90 días de retraso declarado. Obligado no es desembolsado. El mapeo de "
            "recipiente a ticker es curado y declarado empresa a empresa."
        ),
    ),
}


def theme_summaries() -> list[dict]:
    return [
        {"id": theme.id, "name": theme.name, "tagline": theme.tagline}
        for theme in FLOW_THEMES.values()
    ]
