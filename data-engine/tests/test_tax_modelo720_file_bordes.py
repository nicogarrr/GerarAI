"""Bordes del generador del fichero Modelo 720.

Lo que demuestra:
- ``_num`` falla en voz alta cuando el redondeo desborda la parte entera
  (96): un importe que no cabe en el campo no se recorta en silencio.
- Un valor no-dict dentro de ``custody_entities`` se descarta y la partida
  queda sin entidad: fail-closed con el motivo exacto (rama 233->232).
- Con el chequeo de umbrales doblado (es un colaborador ya probado en
  tests/test_modelo720_service*.py), el bucle de valores: posición sin
  ISIN -> excluded exacto (366-370, rama 347->345 del bucle de duplicados);
  ISIN sin custodia declarada -> excluded exacto (404-408); custodia "ES"
  -> excluded exacto (410-414); categoría cuentas por encima del umbral ->
  manual_review exacto (450). La línea 435 (bajas de previous_year_isins)
  no se cubre: es inalcanzable, porque las puertas de historial (283-303)
  retornan antes siempre que ``previous_isins`` no es vacío.
- ``first_acquisition_dates`` como lista con una sola fecha no activa el
  guarda de lotes (rama 377->389) pero llega como cadena mal formada a la
  validación YYYYMMDD, que falla en voz alta con el motivo exacto (392).
- Una fecha "15/01/2023" se rechaza con el motivo exacto (392).

SQLite real en memoria; sin red.
"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import (
    Company,
    Portfolio,
    PortfolioDailySnapshot,
    Position,
    PositionDailySnapshot,
    Tenant,
)
from app.services.tax_modelo720_file import Modelo720FileService, _num
from app.services.tax_modelo720_service import Modelo720Service

DECLARANT = {
    "nif": "12345678Z",
    "apellidos_nombre": "FICTICIO FISCAL, TEST",
    "telefono": "600111222",
    "numero_declaracion": "7202025000001",
    "custody": {"US0378331005": "IE"},
    "custody_entities": {
        "US0378331005": {
            "name": "BROKER FICTICIO DE PRUEBAS",
            "nif": "IE-FICTICIO-0",
            "street": "CALLE FICTICIA 1",
            "city": "DUBLIN",
            "zip": "D01 FAKE",
            "country": "IE",
        },
    },
    "filed_720_before": False,
    "first_acquisition_dates": {"US0378331005": "20230115"},
}


@pytest.fixture()
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _seed(db, declarant):
    tenant = Tenant(external_id="m720fb-test", name="M720F bordes")
    db.add(tenant)
    db.flush()
    db.info["tenant_id"] = tenant.id
    tenant.metadata_ = {"tax_declarant": declarant}
    portfolio = Portfolio(tenant_id=tenant.id, name="Main", base_currency="EUR", is_default=True)
    db.add(portfolio)
    db.flush()
    company = Company(
        ticker="AAPL",
        name="APPLE INC",
        exchange="NASDAQ",
        currency="USD",
        sector="S",
        industry="I",
        company_type="imported_holding",
        valuation_model="unassigned",
        isin="US0378331005",
    )
    db.add(company)
    db.flush()
    db.add(
        Position(
            tenant_id=tenant.id,
            company_id=company.id,
            portfolio_id=portfolio.id,
            quantity=Decimal("10"),
            average_cost=Decimal("150"),
            market_value=Decimal("1800"),
            base_currency="EUR",
            source="ibkr_flex",
        )
    )
    snap = PortfolioDailySnapshot(
        tenant_id=tenant.id,
        portfolio_id=portfolio.id,
        snapshot_date=date(2025, 12, 31),
        base_currency="EUR",
        positions_value_base=Decimal("60000"),
        cash_value_base=Decimal("0"),
        total_value_base=Decimal("60000"),
        metadata_={"missing_pricing": []},
    )
    db.add(snap)
    db.flush()
    db.add(
        PositionDailySnapshot(
            tenant_id=tenant.id,
            portfolio_snapshot_id=snap.id,
            portfolio_id=portfolio.id,
            company_id=company.id,
            snapshot_date=date(2025, 12, 31),
            quantity=Decimal("10"),
            market_price_native=Decimal("180"),
            currency="USD",
            fx_rate=Decimal("1"),
            market_value_native=Decimal("60000"),
            market_value_base=Decimal("60000"),
        )
    )
    db.commit()
    return tenant


def test_num_desborde_falla_en_voz_alta():
    with pytest.raises(ValueError) as excinfo:
        _num("123", 2, 2)
    assert str(excinfo.value) == "Modelo 720: importe 123.00 excede el campo de 2 dígitos enteros"


def test_custody_entities_con_valor_no_dict(db):
    _seed(db, {**DECLARANT, "custody_entities": {"US0378331005": "no-es-dict"}})
    result = Modelo720FileService().generate(db, 2025)
    assert result["available"] is False
    assert result["reason"] == (
        "Falta 'custody_entities' para 'US0378331005' en "
        "tax_declarant (name, nif, street, city, zip, country "
        "de la entidad depositaria REAL de ESA partida): la "
        "entidad se liga a cada ISIN/cuenta, no se agrupa por "
        "país."
    )


def _thresholds_bordes():
    return {
        "unvalued": [],
        "foreign_unverified": [],
        "short_positions": [],
        "stale_snapshots": [],
        "categories": {
            "valores": {
                "exceeds": True,
                "positions": [
                    {"ticker": "AAPL", "isin": "US0378331005", "value_base": "60000.00", "quantity": "10"},
                    {"ticker": "PRIV", "isin": None, "value_base": "5000.00", "quantity": "1"},
                    {"ticker": "SINCUST", "isin": "IE0000000002", "value_base": "5000.00", "quantity": "1"},
                    {"ticker": "DOMEST", "isin": "IE0000000003", "value_base": "5000.00", "quantity": "1"},
                ],
            },
            "cuentas": {"exceeds": True},
        },
    }


def test_bordes_del_bucle_de_valores(db, monkeypatch):
    declarant = {
        **DECLARANT,
        "custody": {"US0378331005": "IE", "IE0000000003": "ES"},
        "custody_entities": {
            **DECLARANT["custody_entities"],
            "IE0000000003": {
                "name": "BANCO FICTICIO NACIONAL",
                "nif": "ES-FICTICIO-0",
                "street": "CALLE FICTICIA 2",
                "city": "MADRID",
                "zip": "28001",
                "country": "ES",
            },
        },
        "first_acquisition_dates": {
            "US0378331005": "20230115",
            "IE0000000002": "20230115",
            "IE0000000003": "20230115",
        },
    }
    _seed(db, declarant)
    monkeypatch.setattr(
        Modelo720Service,
        "check_thresholds",
        lambda self, db, fiscal_year: _thresholds_bordes(),
    )
    result = Modelo720FileService().generate(db, 2025)
    assert result["available"] is True
    assert result["detail_records"] == 1
    assert result["excluded"] == [
        {
            "ticker": "PRIV",
            "reason": "Sin ISIN: la clave 2 (valores sin ISIN) exige 'Z'+país emisor, dato no disponible. Declarar manualmente.",
        },
        {
            "ticker": "SINCUST",
            "reason": "Sin país de custodia declarado para este ISIN en tax_declarant.custody: el campo 129-130 no se infiere. Declarar manualmente.",
        },
        {
            "ticker": "DOMEST",
            "reason": "Custodia declarada en España: no es bien en el extranjero, no va en el 720.",
        },
    ]
    assert result["manual_review"] == [
        {
            "ticker": "cuentas",
            "reason": (
                "La categoría CUENTAS supera el umbral, pero el registro C "
                "exige identificador de cuenta, identidad de la entidad y "
                "saldo medio del 4.º trimestre: no se genera fichero para "
                "cuentas. Declarar manualmente."
            ),
        },
    ]


def test_lotes_lista_una_fecha_llega_mal_formada(db):
    # Una lista con una sola fecha no activa el guarda de lotes (377->389),
    # pero first_dates guarda str(v) de la lista: no es YYYYMMDD (392).
    _seed(
        db,
        {
            **DECLARANT,
            "first_acquisition_dates": {"US0378331005": ["20230115"]},
        },
    )
    result = Modelo720FileService().generate(db, 2025)
    assert result["available"] is False
    assert result["reason"] == (
        "La fecha de primera adquisición de AAPL ('['20230115']') no es "
        "YYYYMMDD: corrígela en tax_declarant.first_acquisition_dates."
    )


def test_fecha_mal_formada_rechazada(db):
    _seed(
        db,
        {
            **DECLARANT,
            "first_acquisition_dates": {"US0378331005": "15/01/2023"},
        },
    )
    result = Modelo720FileService().generate(db, 2025)
    assert result["available"] is False
    assert result["reason"] == (
        "La fecha de primera adquisición de AAPL ('15/01/2023') no es "
        "YYYYMMDD: corrígela en tax_declarant.first_acquisition_dates."
    )
