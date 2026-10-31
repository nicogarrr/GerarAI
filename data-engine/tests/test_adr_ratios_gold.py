"""Tabla ADR pineada contra fuente primaria (oro, verificado 2026-10-31).

Un ratio mal puesto es un error de factor N en TODO valor por accion de ese
emisor (hechos del 20-F en acciones ordinarias, precio del ADR en la linea
US). Estos pines fijan los 9 ratios de la tabla de respaldo contra la fuente
primaria citada en cada fila, comprobada una a una el 2026-10-31:

- BABA 8: Alibaba investor FAQ; 20-F FY2020 (ratio de 2019).
- BIDU 8: anuncio Baidu EGM 1-mar-2021 (SEC 6-K, ex-99.1): de 10 ADS = 1
  ordinaria a 1 ADS = 8 ordinarias.
- JD 2: 20-F 2024 (SEC): "each of which represents two Class A ordinary
  shares".
- PDD 4: PDD Holdings IR / 20-F: "Each ADS represents four Class A ordinary
  shares".
- NTES 5: NetEase IR 18-sep-2020: de 1 ADS = 25 a 1 ADS = 5 ordinarias.
- TSM 5: TSMC Annual Report / SEC F-3: "one ADS represents five common
  shares".
- TM 10: BNY Mellon Corporate Action Notice 3-sep-2021: split 5:1 local,
  ratio de 1 ADS = 2 a 1 ADS = 10, efectivo 1-oct-2021.
- HMC 3: Honda 20-F (SEC): "Each ADS represents three shares of Common
  Stock"; adr.com (JPMorgan) ratio DR/underlying 1:3.
- SONY 1: Citibank DR notice 1-oct-2024: split 5:1 aplicado tambien al ADR,
  ratio ORD:ADR 1:1.

Si una fila cambia (split, cambio de ratio del depositario), actualizar el
ratio, la fuente, la fecha ``verified`` y este pin a la vez.
"""

from __future__ import annotations

import re
from datetime import date

from app.valuation.adr_ratios import ADR_RATIOS, table_adr_ratio

EXPECTED: dict[str, float] = {
    "BABA": 8.0,
    "BIDU": 8.0,
    "JD": 2.0,
    "PDD": 4.0,
    "NTES": 5.0,
    "TSM": 5.0,
    "TM": 10.0,
    "HMC": 3.0,
    "SONY": 1.0,
}


def test_los_nueve_ratios_coinciden_con_la_fuente_primaria() -> None:
    assert set(ADR_RATIOS) == set(EXPECTED)
    for ticker, expected in EXPECTED.items():
        row = table_adr_ratio(ticker)
        assert row is not None, ticker
        assert row.ordinary_per_adr == expected, (
            f"{ticker}: la tabla dice {row.ordinary_per_adr} y la fuente "
            f"primaria ({row.source}) dice {expected}"
        )


def test_toda_fila_declara_fuente_y_fecha_de_comprobacion() -> None:
    today = date.today()
    for ticker, row in ADR_RATIOS.items():
        assert row.source.strip(), f"{ticker}: fuente vacia"
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", row.verified), (
            f"{ticker}: verified {row.verified!r} no es fecha ISO"
        )
        verified = date.fromisoformat(row.verified)
        assert verified <= today, f"{ticker}: verified {verified} en el futuro"
        assert row.ordinary_per_adr > 0, f"{ticker}: ratio no positivo"


def test_lookup_normaliza_minusculas_y_espacios() -> None:
    assert table_adr_ratio(" baba ") == ADR_RATIOS["BABA"]
    assert table_adr_ratio("tsm") == ADR_RATIOS["TSM"]
    assert table_adr_ratio(None) is None
    assert table_adr_ratio("") is None
    assert table_adr_ratio("AAPL") is None
