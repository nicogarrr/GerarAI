"""Fuentes reviewed de paquetes ESEF del emisor (para paises que el indice
filings.xbrl.org no cubre, p.ej. Irlanda: filter[country]=IE devuelve 0
filings, verificado 2026-10-19).

Mismo contrato que las tablas reviewed de cnmv_mapping / esef_issuer_mapping:
cada URL se verifica a mano contra la web del emisor (pagina de resultados,
enlace "Annual Report - ESEF tagged Zip File") antes de entrar; nunca se
generan URLs por patron ni se aproximan. La procedencia del snapshot guarda
la URL, el sha256 real del zip descargado y la fecha de captura.

Kerry Group plc (IE, LEI 635400TLVVBNXLFHWC59): URLs verificadas 2026-10-19
contra https://www.kerry.com/investors/results--presentations (HTTP 200 las
cinco). El paquete FY2025 lleva dentro xbrli:identifier=635400TLVVBNXLFHWC59
(esquema ISO 17442) e ifrs-full:NameOfReportingEntity... = Kerry Group.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EsefPackageSource:
    lei: str
    period_end: str
    url: str


REVIEWED_PACKAGES: tuple[EsefPackageSource, ...] = (
    EsefPackageSource(
        "635400TLVVBNXLFHWC59", "2025-12-31",
        "https://www.kerry.com/content/dam/kerry/en/pdf/investors/results-presentations/2026/635400TLVVBNXLFHWC59-2025-12-31-en.zip",
    ),
    EsefPackageSource(
        "635400TLVVBNXLFHWC59", "2024-12-31",
        "https://www.kerry.com/content/dam/kerry/en/pdf/investors/results-presentations/2025/635400TLVVBNXLFHWC59-2024-12-31-en.zip",
    ),
    EsefPackageSource(
        "635400TLVVBNXLFHWC59", "2023-12-31",
        "https://www.kerry.com/content/dam/kerry/docs/annual-report-2023/esef-tagged.zip",
    ),
    EsefPackageSource(
        "635400TLVVBNXLFHWC59", "2022-12-31",
        "https://www.kerry.com/content/dam/kerry/docs/annual-report-2022/635400TLVVBNXLFHWC59-2022-12-31-en.zip",
    ),
    EsefPackageSource(
        "635400TLVVBNXLFHWC59", "2021-12-31",
        "https://www.kerry.com/content/dam/kerry/docs/annual-report-2021/kerrygroup.zip",
    ),
)
