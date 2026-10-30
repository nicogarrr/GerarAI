"""13F: un split entre dos trimestres no es una compra.

NVDA hizo split 10:1 el 2024-06-10. Un gestor con 1.000 acciones a 31/03/2024
(precio 903,56 → valor 903.560 $) que no opera tiene 10.000 a 30/06/2024
(precio 123,54 → valor 1.235.400 $). Por acciones a pelo salia «increased»
(+900 %) y el gestor contaba como comprador en «lo que mas compran».

A mano: ratio de acciones 10.000/1.000 = 10 exacto; precio implicito
903,56/123,54 = 7,31, dentro de 10/1,5 = 6,67 .. 15 ⇒ split ⇒ «unchanged».
Un gestor que de verdad duplica (1.000 → 2.000) con el precio casi igual
(100 → 105) tiene ratio 2 pero precio 0,95, fuera de 1,33 .. 3 ⇒ «increased».
"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, FundManager, ManagerHolding
from app.services.manager_holding_ingestion_service import ManagerHoldingIngestionService

CIK = "0001067983"


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _holding(manager, accession, report, cusip, name, shares, value):
    return ManagerHolding(
        manager_id=manager.id,
        accession_number=accession,
        report_date=report,
        filing_date=date(report.year, report.month, 28) if report.month != 6 else date(2024, 8, 14),
        is_amendment=False,
        name_of_issuer=name,
        title_of_class="COM",
        cusip=cusip,
        value_usd_thousands=Decimal(value),
        value_scale="dollars_raw",
        shares=Decimal(shares),
        share_type="SH",
        put_call="",
    )


def _seed(db, rows):
    manager = FundManager(cik=CIK, name="Test Manager", coverage="ok")
    db.add(manager)
    db.flush()
    q1, q2 = date(2024, 3, 31), date(2024, 6, 30)
    for cusip, name, before, now in rows:
        db.add(_holding(manager, "0000000000-24-000001", q1, cusip, name, *before))
        db.add(_holding(manager, "0000000000-24-000002", q2, cusip, name, *now))
    db.commit()


def _labels(db):
    result = ManagerHoldingIngestionService().changes(db, cik=CIK)
    assert result["status"] == "ok", result
    return {row["cusip"]: row["change"] for row in result["changes"]}


def test_split_10_por_1_sin_operar_no_es_compra(db):
    _seed(db, [("67066G104", "NVIDIA CORP", ("1000", "903560"), ("10000", "1235400"))])
    assert _labels(db)["67066G104"] == "unchanged"
    assert ManagerHoldingIngestionService().change_labels_for_cusip(
        db, cik=CIK, cusip="67066G104"
    ) == ["unchanged"]


def test_contrasplit_1_por_10_no_es_venta(db):
    # 10.000 acciones a 2 $ → 1.000 a 19 $ (contrasplit con caida del 5 %).
    _seed(db, [("000000001", "REVERSE CO", ("10000", "20000"), ("1000", "19000"))])
    assert _labels(db)["000000001"] == "unchanged"


def test_duplicar_de_verdad_sigue_siendo_compra(db):
    _seed(db, [
        ("000000002", "BUYER CO", ("1000", "100000"), ("2000", "210000")),
        ("000000003", "SELLER CO", ("3000", "300000"), ("1000", "100000")),
    ])
    labels = _labels(db)
    assert labels["000000002"] == "increased"
    assert labels["000000003"] == "decreased"


def test_split_y_luego_compra_no_exacta_sigue_siendo_compra(db):
    # 1.000 → 12.500 acciones (split 10:1 y compra de 2.500): ratio 12,5 = 25/2,
    # precio 903,56/123,54 = 7,31 fuera de 12,5/1,5 = 8,33 ⇒ no se toma por split.
    _seed(db, [("67066G104", "NVIDIA CORP", ("1000", "903560"), ("12500", "1544250"))])
    assert _labels(db)["67066G104"] == "increased"
