"""Sector e industria de la SEC (código SIC de ``data.sec.gov/submissions``) para fichas en «Unknown».

Fuente gratuita y ya usada por GerarAI (conectores de EDGAR, tasas base). Solo rellena placeholders:
nunca pisa un sector o una industria curados.

- **Industria**: «<sicDescription> (SIC nnnn)», el mismo formato de ``company_master`` («Pharmaceutical
  preparations (SIC 2834)»), con la descripción de la SEC tal cual (solo cambia a minúsculas).
- **Sector**: primero el sector MAYORITARIO de las fichas ya clasificadas de la base con el MISMO código SIC
  (empate → orden alfabético): así la base decide, por ejemplo, dónde cae SIC 7370 (datos y programación),
  que la SEC no separa entre plataformas de internet y servicios informáticos. Sin ninguna ficha con ese
  SIC, la tabla declarada :data:`SIC_SECTOR_RANGES` (aproximación SIC → sector de 11, documentada abajo;
  el SIC no es GICS). Sin rango, el sector sigue «Unknown» (honesto, nunca inventado).
"""
from __future__ import annotations

import json
import logging
import re
from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from typing import Any

logger = logging.getLogger(__name__)

RULES_VERSION = "sic-sector-v1"
PLACEHOLDERS = {None, "", "unknown", "n/a", "none"}

#: (desde, hasta inclusive, sector). El primer rango que contiene el SIC gana: los específicos van antes.
SIC_SECTOR_RANGES: tuple[tuple[int, int, str], ...] = (
    (100, 999, "Consumer Staples"),          # agricultura, ganadería, pesca
    (1000, 1099, "Materials"),               # minería metálica
    (1200, 1399, "Energy"),                  # carbón, petróleo y gas
    (1400, 1499, "Materials"),               # minería no metálica
    (1531, 1531, "Consumer Discretionary"),  # promotores de vivienda
    (1500, 1799, "Industrials"),             # construcción
    (2000, 2199, "Consumer Staples"),        # alimentación, bebidas, tabaco
    (2200, 2399, "Consumer Discretionary"),  # textil y confección
    (2400, 2499, "Materials"),               # madera
    (2500, 2599, "Consumer Discretionary"),  # muebles
    (2600, 2699, "Materials"),               # papel
    (2700, 2799, "Communication Services"),  # edición e impresión
    (2830, 2836, "Health Care"),             # farmacia y biotecnología
    (2840, 2844, "Consumer Staples"),        # jabones y cosmética
    (2800, 2899, "Materials"),               # química
    (2900, 2999, "Energy"),                  # refino
    (3000, 3099, "Materials"),               # caucho y plásticos
    (3100, 3199, "Consumer Discretionary"),  # cuero
    (3200, 3399, "Materials"),               # vidrio, cemento, metales primarios
    (3570, 3579, "Information Technology"),  # ordenadores y equipos de oficina
    (3630, 3639, "Consumer Discretionary"),  # electrodomésticos
    (3651, 3652, "Consumer Discretionary"),  # electrónica de consumo
    (3660, 3679, "Information Technology"),  # equipos de comunicaciones, semiconductores, componentes
    (3710, 3716, "Consumer Discretionary"),  # vehículos de motor
    (3750, 3751, "Consumer Discretionary"),  # motocicletas y bicicletas
    (3400, 3799, "Industrials"),             # metal, maquinaria, equipo eléctrico, aeronáutico y espacial
    (3826, 3826, "Health Care"),             # instrumentos de análisis de laboratorio (ciencias de la vida)
    (3840, 3851, "Health Care"),             # equipos médicos y ópticos
    (3800, 3899, "Information Technology"),  # instrumentos de medida y control
    (3900, 3999, "Consumer Discretionary"),  # manufacturas diversas (joyería, juguetes…)
    (4800, 4899, "Communication Services"),  # telecomunicaciones y radiodifusión
    (4900, 4999, "Utilities"),               # electricidad, gas, agua
    (4000, 4799, "Industrials"),             # transporte
    (5120, 5122, "Health Care"),             # mayoristas de fármacos
    (5140, 5149, "Consumer Staples"),        # mayoristas de alimentación
    (5000, 5199, "Industrials"),             # mayoristas
    (5400, 5499, "Consumer Staples"),        # alimentación al por menor
    (5912, 5912, "Consumer Staples"),        # farmacias
    (5200, 5999, "Consumer Discretionary"),  # comercio minorista
    (6500, 6553, "Real Estate"),             # inmobiliarias
    (6798, 6798, "Real Estate"),             # REIT
    (6000, 6799, "Financials"),              # banca, seguros, inversión
    (7310, 7319, "Communication Services"),  # publicidad
    (7370, 7379, "Information Technology"),  # programación, proceso de datos, software
    (7000, 7299, "Consumer Discretionary"),  # hoteles y servicios personales
    (7300, 7399, "Industrials"),             # servicios a empresas
    (7800, 7899, "Communication Services"),  # cine y vídeo
    (7900, 7999, "Consumer Discretionary"),  # ocio
    (8000, 8099, "Health Care"),             # servicios sanitarios
    (8200, 8299, "Consumer Discretionary"),  # educación
    (8731, 8731, "Health Care"),             # investigación física y biológica comercial
    (8700, 8799, "Industrials"),             # ingeniería y consultoría
)

_SIC_IN_TEXT = re.compile(r"\(SIC (\d{3,4})\)")


def known(text: Any) -> str | None:
    t = str(text or "").strip()
    return None if t.lower() in PLACEHOLDERS else t


def declared_sector(sic: int | None) -> str | None:
    if sic is None:
        return None
    for lo, hi, sector in SIC_SECTOR_RANGES:
        if lo <= sic <= hi:
            return sector
    return None


def industry_label(sic: int, description: str | None) -> str:
    desc = " ".join(str(description or "").split())
    desc = (desc[:1].upper() + desc[1:].lower()) if desc else "Sin descripción en la SEC"
    return f"{desc} (SIC {sic})"


def sic_in_text(industry: str | None) -> int | None:
    m = _SIC_IN_TEXT.search(str(industry or ""))
    return int(m.group(1)) if m else None


def calibration(pairs: Iterable[tuple[int | None, str | None]]) -> dict[int, str]:
    """{SIC: sector mayoritario} de las fichas YA clasificadas (empate → orden alfabético). Puro."""
    votes: dict[int, Counter[str]] = {}
    for sic, sector in pairs:
        sec = known(sector)
        if sic is None or sec is None:
            continue
        votes.setdefault(int(sic), Counter())[sec] += 1
    return {sic: sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))[0][0] for sic, c in votes.items()}


def classify(sic: int | None, description: str | None, calib: Mapping[int, str]) -> dict[str, Any]:
    """Sector, de dónde sale e industria para un SIC. Puro."""
    if sic is None:
        return {"sector": None, "sector_source": None, "industry": None}
    if sic in calib:
        sector, source = calib[sic], f"sector mayoritario de las fichas de la base con SIC {sic}"
    else:
        sector = declared_sector(sic)
        source = f"tabla SIC→sector declarada ({RULES_VERSION})" if sector else None
    return {"sector": sector, "sector_source": source, "industry": industry_label(sic, description)}


def apply(company: Any, sic: int | None, description: str | None, calib: Mapping[int, str]) -> dict[str, Any]:
    """Escribe SOLO los campos en placeholder. Devuelve lo que cambió (vacío si nada)."""
    if sic is None:
        return {}
    got = classify(sic, description, calib)
    changed: dict[str, Any] = {}
    if known(getattr(company, "industry", None)) is None and got["industry"]:
        company.industry = got["industry"]
        changed["industry"] = got["industry"]
    if known(getattr(company, "sector", None)) is None:
        from app.services.company_enrichment_service import sector_for_industry

        # Una industria ya presente en la ficha (de Finnhub) manda sobre el SIC (UNH: «Health Care», SIC 6324).
        by_industry = sector_for_industry(known(getattr(company, "industry", None)))
        sector, source = (by_industry, "industria de la ficha") if by_industry else (got["sector"], got["sector_source"])
        if sector:
            company.sector = sector
            changed["sector"] = sector
            changed["sector_source"] = source
    return changed


def sec_submissions_sic(cik: Any, get_text: Callable[[str], str] | None = None) -> tuple[int | None, str | None]:
    """(sic, sicDescription) de ``data.sec.gov/submissions`` (ritmo y UA de la SEC del conector de Form 4)."""
    from app.services.connectors.edgar_common import SUBMISSIONS_URL

    if get_text is None:
        from app.services.connectors import form4

        def _sec_get(url: str) -> str:
            return form4._get_text(url, None)  # noqa: SLF001 - mismo ritmo y UA que Form 4

        fetch: Callable[[str], str] = _sec_get
    else:
        fetch = get_text

    try:
        data = json.loads(fetch(SUBMISSIONS_URL.format(cik=str(int(str(cik))).zfill(10))))
    except Exception as exc:  # noqa: BLE001 - sin SIC, el sector sigue «Unknown»
        logger.info("SIC de la SEC %s: %s", cik, type(exc).__name__)
        return None, None
    if not isinstance(data, dict):
        return None, None
    try:
        sic = int(str(data.get("sic") or "").strip())
    except ValueError:
        return None, None
    return sic, (data.get("sicDescription") or None)


def base_calibration(db: Any, extra: Iterable[tuple[int | None, str | None]] = ()) -> dict[int, str]:
    """Calibración con lo persistido (industrias «… (SIC nnnn)» con sector conocido) y ``extra``."""
    from sqlalchemy import select

    from app.models.entities import Company

    rows = db.execute(select(Company.industry, Company.sector)).all()
    return calibration([*((sic_in_text(ind), sec) for ind, sec in rows), *extra])


def fill_from_sic(db: Any, *, lookup: Callable[[Any], tuple[int | None, str | None]] | None = None,
                  companies: Iterable[Any] | None = None) -> dict[str, Any]:
    """Barrido: SIC de cada ficha con CIK; calibra con las ya clasificadas y rellena las «Unknown».

    No hace commit: lo decide quien llama."""
    from sqlalchemy import select

    from app.models.entities import Company

    lookup = lookup or sec_submissions_sic
    rows = list(companies) if companies is not None else list(db.scalars(select(Company).order_by(Company.ticker)).all())
    sics: dict[int, tuple[int | None, str | None]] = {}
    for c in rows:
        if getattr(c, "cik", None):
            sics[c.id] = lookup(c.cik)
    calib = base_calibration(db, [(sics.get(c.id, (None, None))[0], c.sector) for c in rows])
    changed: dict[str, Any] = {}
    for c in rows:
        sic, desc = sics.get(c.id, (None, None))
        got = apply(c, sic, desc, calib)
        if tag_sic(c, sic):
            got = {**got, "tag": f"{SIC_TAG_PREFIX}{sic}"}
        if got:
            changed[c.ticker] = {**got, "sic": sic}
    return {"rules": RULES_VERSION, "with_sic": sum(1 for v in sics.values() if v[0] is not None),
            "changed": changed, "calibration": {str(k): v for k, v in sorted(calib.items())}}


# --- Grupos de industria por SIC (regla «comparables-sic-v1», pre-registrada el 9-nov-2026) -----------------
#
# Algunos competidores directos caen en códigos SIC distintos de la SEC: un operador de satélites
# (4899, servicios de comunicaciones), un fabricante de satélites y equipos (3663), un lanzador o una nave
# (3760–3769) o un sistema de navegación o alunizaje (3812). El grupo declarado los junta; cualquier emisor de
# esos códigos entra igual (no hay lista de tickers). Dentro del grupo, los comparables son los de
# capitalización más cercana (ver ``pre_revenue_valuation.mature_peers``), para que un gigante del mismo código
# (defensa, redes) no fije el múltiplo.
SIC_INDUSTRY_GROUPS: tuple[tuple[str, tuple[tuple[int, int], ...]], ...] = (
    ("espacio y satélite", ((3663, 3663), (3760, 3769), (3812, 3812), (4899, 4899))),
)
#: Etiqueta en ``Company.factor_tags`` con el SIC de la SEC (mismo patrón que ``adr:N``).
SIC_TAG_PREFIX = "sic:"


def sic_from_tags(tags: Iterable[Any] | None) -> int | None:
    for tag in tags or []:
        text = str(tag).strip().lower()
        if text.startswith(SIC_TAG_PREFIX):
            try:
                return int(text[len(SIC_TAG_PREFIX):])
            except ValueError:
                return None
    return None


def company_sic(company: Any) -> int | None:
    """SIC de la ficha: la etiqueta ``sic:nnnn`` o el «(SIC nnnn)» de la industria."""
    return sic_from_tags(getattr(company, "factor_tags", None)) or sic_in_text(getattr(company, "industry", None))


def industry_group(sic: int | None) -> tuple[str, tuple[tuple[int, int], ...]] | None:
    if sic is None:
        return None
    for label, ranges in SIC_INDUSTRY_GROUPS:
        if any(lo <= sic <= hi for lo, hi in ranges):
            return label, ranges
    return None


def group_label(group: tuple[str, tuple[tuple[int, int], ...]]) -> str:
    label, ranges = group
    codes = ", ".join(str(lo) if lo == hi else f"{lo}–{hi}" for lo, hi in ranges)
    return f"{label} (SIC {codes})"


def tag_sic(company: Any, sic: int | None) -> bool:
    """Guarda ``sic:nnnn`` en las etiquetas de la ficha (sustituye otra ``sic:``). True si cambió."""
    if sic is None:
        return False
    tags = [t for t in list(getattr(company, "factor_tags", None) or []) if not str(t).lower().startswith(SIC_TAG_PREFIX)]
    new = [*tags, f"{SIC_TAG_PREFIX}{int(sic)}"]
    if list(getattr(company, "factor_tags", None) or []) == new:
        return False
    company.factor_tags = new
    return True


__all__ = [
    "SIC_INDUSTRY_GROUPS",
    "SIC_SECTOR_RANGES",
    "SIC_TAG_PREFIX",
    "apply",
    "base_calibration",
    "calibration",
    "classify",
    "company_sic",
    "declared_sector",
    "fill_from_sic",
    "group_label",
    "industry_group",
    "industry_label",
    "sec_submissions_sic",
    "sic_from_tags",
    "sic_in_text",
    "tag_sic",
]
