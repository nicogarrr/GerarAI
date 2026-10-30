"""Tests herméticos del generador del fichero Modelo 720 (sin red).

Layout verificado contra la spec oficial AEAT (modelo_720.pdf): registros
de 500 posiciones, valoraciones 12+2, ISIN en 132-143.

Run from data-engine/:
    pytest tests/test_tax_modelo720_file.py -v
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
from app.services.tax_modelo720_file import RECORD_LEN, Modelo720FileService


@pytest.fixture()
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _seed(db, declarant=None, value="60000"):
    tenant = Tenant(external_id="m720f-test", name="M720F test")
    db.add(tenant)
    db.flush()
    db.info["tenant_id"] = tenant.id
    if declarant is not None:
        tenant.metadata_ = {"tax_declarant": declarant}
    portfolio = Portfolio(
        tenant_id=tenant.id, name="Main", base_currency="EUR", is_default=True
    )
    db.add(portfolio)
    db.flush()
    company = Company(
        ticker="AAPL", name="APPLE INC", exchange="NASDAQ", currency="USD",
        sector="S", industry="I", company_type="imported_holding",
        valuation_model="unassigned", isin="US0378331005",
    )
    db.add(company)
    db.flush()
    db.add(Position(
        tenant_id=tenant.id, company_id=company.id, portfolio_id=portfolio.id,
        quantity=Decimal("10"), average_cost=Decimal("150"),
        market_value=Decimal("1800"), base_currency="EUR", source="ibkr_flex",
    ))
    snap = PortfolioDailySnapshot(
        tenant_id=tenant.id, portfolio_id=portfolio.id,
        snapshot_date=date(2025, 12, 31), base_currency="EUR",
        positions_value_base=Decimal(value), cash_value_base=Decimal("0"),
        total_value_base=Decimal(value),
        # El servicio de snapshots siempre escribe la clave: provenance probada.
        metadata_={"missing_pricing": []},
    )
    db.add(snap)
    db.flush()
    db.add(PositionDailySnapshot(
        tenant_id=tenant.id, portfolio_snapshot_id=snap.id,
        portfolio_id=portfolio.id, company_id=company.id,
        snapshot_date=date(2025, 12, 31), quantity=Decimal("10"),
        market_price_native=Decimal("180"), currency="USD",
        fx_rate=Decimal("1"), market_value_native=Decimal(value),
        market_value_base=Decimal(value),
    ))
    db.commit()
    return tenant


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


def test_unavailable_without_declarant(db):
    _seed(db, declarant=None)
    result = Modelo720FileService().generate(db, 2025)
    assert result["available"] is False
    assert "tax_declarant" in result["reason"]


def test_unavailable_below_threshold(db):
    _seed(db, declarant=DECLARANT, value="40000")
    result = Modelo720FileService().generate(db, 2025)
    assert result["available"] is False


def test_unavailable_when_category_unknown(db):
    # Snapshot de junio (stale) → categoría "desconocido": no se genera
    # fichero sobre datos no concluyentes.
    tenant = _seed(db, declarant=DECLARANT)
    snap = db.query(PositionDailySnapshot).one()
    snap.snapshot_date = date(2025, 6, 30)
    db.query(PortfolioDailySnapshot).one().snapshot_date = date(2025, 6, 30)
    db.commit()
    result = Modelo720FileService().generate(db, 2025)
    assert result["available"] is False


def test_generates_spec_layout_records(db):
    _seed(db, declarant=DECLARANT)
    result = Modelo720FileService().generate(db, 2025)

    assert result["available"] is True
    assert result["detail_records"] == 1
    lines = result["content"].rstrip("\n").split("\n")
    assert len(lines) == 2
    for line in lines:
        assert len(line) == RECORD_LEN
        line.encode("iso-8859-1")  # codificable en la spec

    summary, detail = lines
    # Tipo 1: cabecera y contador.
    assert summary[0] == "1"
    assert summary[1:4] == "720"
    assert summary[4:8] == "2025"
    assert summary[8:17] == "12345678Z"             # 9-17: NIF (9 posiciones exactas)
    assert summary[17:57].rstrip() == "FICTICIO FISCAL, TEST"
    assert summary[57] == "T"
    assert summary[58:67] == "600111222"
    assert summary[107:120] == "7202025000001"      # 108-120: nº declaración
    assert summary[135:144] == "000000001"          # 1 registro de detalle
    # Suma valoración 1 = 60.000,00 → signo espacio + 15+2 dígitos.
    assert summary[144] == " "
    assert summary[145:162] == "00000000006000000"
    # Tipo 2 (V): campos oficiales en sus posiciones exactas.
    assert detail[0] == "2"
    assert detail[101] == "V"                        # 102: clave bien
    assert detail[102] == "1"                        # 103: subclave participación
    assert detail[128:130] == "IE"                   # 129-130: país de DEPÓSITO declarado por partida (no el prefijo del ISIN)
    assert detail[130] == "1"                        # 131: identificación por ISIN
    assert detail[131:143].rstrip() == "US0378331005"  # 132-143: ISIN
    assert detail[189:230].rstrip() == "BROKER FICTICIO DE PRUEBAS"  # 190-230: entidad depositaria REAL
    assert detail[230:250].rstrip() == "IE-FICTICIO-0"               # 231-250: NIF de la entidad
    # Domicilio ESTRUCTURADO por subcampos (spec pág. 26):
    assert detail[250:302].rstrip() == "CALLE FICTICIA 1"            # 251-302: vía y número
    assert detail[302:342].rstrip() == ""                            # 303-342: complemento (opcional)
    assert detail[342:372].rstrip() == "DUBLIN"                      # 343-372: ciudad
    assert detail[402:412].rstrip() == "D01 FAKE"                    # 403-412: código postal
    assert detail[412:414] == "IE"                                   # 413-414: país de la entidad
    assert detail[414:422] == "20230115"             # 415-422: fecha incorporación
    assert detail[422] == "A"                        # 423: origen (primera vez)
    assert detail[431] == " "                        # 432: signo valoración 1
    assert detail[432:446] == "000000060000" + "00"   # 433-446: 60.000,00 (12+2)
    assert detail[447:461] == "00000000000000"       # 448-461: valoración 2 a ceros (V)
    assert detail[461] == "A"                        # 462: anotaciones en cuenta
    assert detail[462:474] == "000000001000"         # 463-474: 10 valores (10+2)
    assert detail[475:480] == "10000"                # 476-480: 100,00 %
    assert detail[480:] == " " * 20                  # 481-500: blancos


def test_missing_isin_excluded_with_reason(db):
    _seed(db, declarant=DECLARANT)
    db.query(Company).one().isin = None
    db.commit()
    result = Modelo720FileService().generate(db, 2025)
    assert result["available"] is False
    assert any("ISIN" in e["reason"] for e in result["excluded"])


def test_unavailable_without_numero_declaracion(db):
    d = {k: v for k, v in DECLARANT.items() if k != "numero_declaracion"}
    _seed(db, declarant=d)
    result = Modelo720FileService().generate(db, 2025)
    assert result["available"] is False
    assert "numero_declaracion" in result["reason"]


def test_unavailable_with_malformed_numero_declaracion(db):
    _seed(db, declarant={**DECLARANT, "numero_declaracion": "0000000000000"})
    result = Modelo720FileService().generate(db, 2025)
    assert result["available"] is False
    assert "720" in result["reason"]


def test_unavailable_without_custody_map(db):
    d = {k: v for k, v in DECLARANT.items() if k != "custody"}
    _seed(db, declarant=d)
    result = Modelo720FileService().generate(db, 2025)
    assert result["available"] is False
    assert "custody" in result["reason"]


def test_unavailable_without_custody_entity(db):
    d = {k: v for k, v in DECLARANT.items() if k != "custody_entities"}
    _seed(db, declarant=d)
    result = Modelo720FileService().generate(db, 2025)
    assert result["available"] is False
    assert "custody_entities" in result["reason"]


def test_unavailable_without_filed_720_before(db):
    # Ausencia de historial NO confirma primera declaración: fail-closed.
    d = {k: v for k, v in DECLARANT.items() if k != "filed_720_before"}
    _seed(db, declarant=d)
    result = Modelo720FileService().generate(db, 2025)
    assert result["available"] is False
    assert "filed_720_before" in result["reason"]


def test_unavailable_when_filed_720_before_true(db):
    # Con declaraciones previas, el origen A/M exige los importes de la
    # última declaración (incremento conjunto >20.000 €): no se decide
    # sin ellos.
    _seed(db, declarant={**DECLARANT, "filed_720_before": True})
    result = Modelo720FileService().generate(db, 2025)
    assert result["available"] is False
    assert "20.000" in result["reason"]


def test_unavailable_on_contradictory_filing_history(db):
    _seed(db, declarant={
        **DECLARANT,
        "filed_720_before": False,
        "previous_year_isins": ["IE00B4L5Y983"],
    })
    result = Modelo720FileService().generate(db, 2025)
    assert result["available"] is False
    assert "Contradicción" in result["reason"]


def test_unavailable_with_multi_date_lots(db):
    # Lotes con fechas distintas exigen un registro por fecha y no tenemos
    # cantidades por lote: no se genera un registro comprimido.
    _seed(db, declarant={
        **DECLARANT,
        "first_acquisition_dates": {"US0378331005": ["20230115", "20240610"]},
    })
    result = Modelo720FileService().generate(db, 2025)
    assert result["available"] is False
    assert "lotes" in result["reason"]


def test_unavailable_without_first_acquisition_date(db):
    _seed(db, declarant={**DECLARANT, "first_acquisition_dates": {}})
    result = Modelo720FileService().generate(db, 2025)
    assert result["available"] is False
    assert "AAPL" in result["reason"]


def test_origin_a_is_legitimate_first_declaration(db):
    # filed_720_before=false: origen "A" legítimo (primera declaración).
    _seed(db, declarant=DECLARANT)
    result = Modelo720FileService().generate(db, 2025)
    assert result["available"] is True
    detail = result["content"].rstrip("\n").split("\n")[1]
    assert detail[422] == "A"


def test_unavailable_with_non_boolean_filed_720_before(db):
    # "false" (string), 0 o {} pasarían por primera declaración: fail-closed.
    _seed(db, declarant={**DECLARANT, "filed_720_before": "false"})
    result = Modelo720FileService().generate(db, 2025)
    assert result["available"] is False
    assert "booleano" in result["reason"]


def test_unavailable_on_entity_country_mismatch(db):
    # El país del domicilio de la entidad debe ser el de la custodia de su
    # partida: una entidad "ES" para custodia "IE" es incoherente.
    bad = {
        "US0378331005": {
            **DECLARANT["custody_entities"]["US0378331005"],
            "country": "ES",
        },
    }
    _seed(db, declarant={**DECLARANT, "custody_entities": bad})
    result = Modelo720FileService().generate(db, 2025)
    assert result["available"] is False
    assert "Incoherencia" in result["reason"]


def test_unavailable_same_isin_in_two_portfolios(db):
    # El mismo ISIN en dos carteras puede estar en custodios distintos:
    # no representable por ISIN -> fail-closed.
    tenant = _seed(db, declarant=DECLARANT)
    other = Portfolio(tenant_id=tenant.id, name="Other", base_currency="EUR")
    db.add(other)
    db.flush()
    company = db.query(Company).one()
    db.add(Position(
        tenant_id=tenant.id, company_id=company.id, portfolio_id=other.id,
        quantity=Decimal("5"), average_cost=Decimal("150"),
        market_value=Decimal("900"), base_currency="EUR", source="ibkr_flex",
    ))
    snap = PortfolioDailySnapshot(
        tenant_id=tenant.id, portfolio_id=other.id,
        snapshot_date=date(2025, 12, 31), base_currency="EUR",
        positions_value_base=Decimal("20000"), cash_value_base=Decimal("0"),
        total_value_base=Decimal("20000"), metadata_={"missing_pricing": []},
    )
    db.add(snap)
    db.flush()
    db.add(PositionDailySnapshot(
        tenant_id=tenant.id, portfolio_snapshot_id=snap.id,
        portfolio_id=other.id, company_id=company.id,
        snapshot_date=date(2025, 12, 31), quantity=Decimal("5"),
        market_price_native=Decimal("180"), currency="USD",
        fx_rate=Decimal("1"), market_value_native=Decimal("20000"),
        market_value_base=Decimal("20000"),
    ))
    db.commit()
    result = Modelo720FileService().generate(db, 2025)
    assert result["available"] is False
    assert "no representable" in result["reason"]


def test_text_field_keeps_spanish_names_readable():
    """Alphanumeric fields: uppercase, no accented vowels, Ñ/Ç kept.

    AEAT "Modelo 720. Diseños físicos y lógicos" (Orden HAP/72/2013, anexo
    II), normas generales: alphanumeric fields go in "mayúsculas, sin
    caracteres especiales y sin vocales acentuadas"; Ñ and Ç are valid
    ISO-8859-1 characters of the spec. "Muñoz Pérez José" must become
    "MUÑOZ PEREZ JOSE", not "MU OZ P REZ JOS " (letters lost to blanks,
    which no longer matches the declarant's census name).
    """
    from app.services.tax_modelo720_file import CODING, _text

    assert _text("Muñoz Pérez José", 20) == "MUÑOZ PEREZ JOSE    "
    assert _text("Peña Ibáñez Begoña", 18) == "PEÑA IBAÑEZ BEGOÑA"
    assert _text("Àlex Gonçalves Lüdke", 20) == "ALEX GONÇALVES LUDKE"
    assert _text("ÁNGEL", 5) == "ANGEL"
    # Width is preserved in the 1-byte encoding of the file.
    assert len(_text("Muñoz Pérez José", 40).encode(CODING)) == 40
    # Control characters still become blanks without shifting columns.
    assert _text("A\tB", 3) == "A B"
