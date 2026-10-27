"""Tabla de ratios ADR: acciones ordinarias que representa cada ADS/ADR.

Los hechos de un emisor extranjero (20-F) vienen en acciones ORDINARIAS y el
precio es el del ADR. Sin el ratio, el valor por accion y el precio no son
comparables (BABA: 1 ADS = 8 ordinarias). Hasta ahora el ratio solo existia si
alguien ponia la etiqueta ``adr:N`` en ``factor_tags``; una ficha creada por
el enriquecimiento no la tenia. Esta tabla es el respaldo: la etiqueta, si
existe, sigue mandando.

Cada fila cita la fuente primaria (emisor o depositario) y la fecha en que se
comprobo. Un ratio cambia con splits o con un cambio de ratio del
depositario: actualizar la fila y su fuente cuando ocurra. La tabla da el
ratio VIGENTE; no reconstruye ratios historicos.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AdrRatio:
    ordinary_per_adr: float
    source: str
    verified: str  # fecha ISO de la comprobacion


ADR_RATIOS: dict[str, AdrRatio] = {
    # China
    "BABA": AdrRatio(
        8,
        "Alibaba Group, FAQ inversores: cada ADS representa ocho acciones "
        "ordinarias (cambio de ratio de 2019, 20-F FY2020 ex. 2.25)",
        "2026-10-27",
    ),
    "BIDU": AdrRatio(
        8,
        "Baidu IR: «One Baidu ADS represents eight Class A ordinary shares»",
        "2026-10-27",
    ),
    "JD": AdrRatio(
        2,
        "JD.com IR: ADS «each representing two Class A ordinary shares»",
        "2026-10-27",
    ),
    "PDD": AdrRatio(
        4,
        "PDD Holdings IR: «Each ADS represents four Class A ordinary shares»",
        "2026-10-27",
    ),
    "NTES": AdrRatio(
        5,
        "NetEase IR: cambio de ratio de 1 ADS = 25 a 1 ADS = 5 acciones ordinarias",
        "2026-10-27",
    ),
    # Taiwan
    "TSM": AdrRatio(
        5,
        "TSMC: «Each TSMC ADR represents five common shares» (SEC F-3)",
        "2026-10-27",
    ),
    # Japon
    "TM": AdrRatio(
        10,
        "NYSE / Toyota, cambio de ratio efectivo 1-oct-2021: de 1 ADS = 2 a "
        "1 ADS = 10 acciones ordinarias",
        "2026-10-27",
    ),
    "HMC": AdrRatio(
        3,
        "Honda Motor ADS «each representing three (3) shares of Common Stock» "
        "(tras el split 3:1 del 1-oct-2023)",
        "2026-10-27",
    ),
    "SONY": AdrRatio(
        1,
        "Sony Group IR: el split 5:1 de 1-oct-2024 se aplico tambien al ADR; "
        "1 ADS = 1 accion ordinaria",
        "2026-10-27",
    ),
}


def table_adr_ratio(ticker: str | None) -> AdrRatio | None:
    """Ratio de la tabla para un ticker de la linea US, o None."""
    key = (ticker or "").strip().upper()
    return ADR_RATIOS.get(key)
