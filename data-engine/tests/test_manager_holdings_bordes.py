"""Bordes de manager_holding_ingestion_service (MH1): guards de parseo, ratio
de split, sync sin filings, tabla de informacion no encontrada, cobertura
almacenada y servicio de ultimas posiciones sin filas.

Sin red: form13f se dobla con monkeypatch (recent_13f_filings e
information_table_url) y el getter compartido de Redis se dobla con None en los
tests que commitean (None = "sin cliente configurado": no-op, sin clear falso).
BBDD: SQLite real en memoria. Los mensajes y dicts de error se comprueban por
igualdad estricta. Helpers puros por via directa con filas SimpleNamespace:
acotacion, no validan el pipeline completo.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models import FundManager, ManagerHolding, Tenant
from app.models.entities import Base
from app.services.manager_holding_ingestion_service import (
    LIMITATIONS,
    REVIEWED_MANAGERS,
    ManagerHoldingIngestionService,
    _date,
    _decimal,
    _value_dollars,
    implied_split_ratio,
    verification_status,
)


def _fila(shares, value, report=date(2024, 3, 31), share_type="SH"):
    return SimpleNamespace(
        shares=shares, value_usd_thousands=value, report_date=report, share_type=share_type
    )


# ----------------------------------------------------------------- helpers puros


def test_decimal_none_y_vacio() -> None:
    assert _decimal(None) is None  # noqa: SLF001
    assert _decimal("") is None  # noqa: SLF001


def test_decimal_invalido() -> None:
    assert _decimal("abc") is None  # noqa: SLF001


def test_date_vacia() -> None:
    assert _date("") is None  # noqa: SLF001


def test_date_invalida() -> None:
    assert _date("no-es-fecha") is None  # noqa: SLF001


def test_value_dollars_sin_datos() -> None:
    assert _value_dollars(SimpleNamespace(value_usd_thousands=None, report_date=date(2024, 3, 31))) is None  # noqa: SLF001


def test_split_share_type_no_sh() -> None:
    ahora = _fila(200, 1000, share_type="PRN")
    antes = _fila(100, 1000)
    assert implied_split_ratio(ahora, antes) is None
    assert implied_split_ratio(antes, ahora) is None


def test_split_acciones_cero() -> None:
    assert implied_split_ratio(_fila(0, 1000), _fila(100, 1000)) is None
    assert implied_split_ratio(_fila(200, 1000), _fila(-5, 1000)) is None


def test_split_valor_cero() -> None:
    assert implied_split_ratio(_fila(200, 0), _fila(100, 1000)) is None


def test_split_precio_fuera_de_tolerancia() -> None:
    # Acciones 2:1 exactas pero el precio implicito se mueve x0,1: no es split.
    assert implied_split_ratio(_fila(200, 20000), _fila(100, 1000)) is None


def test_split_valido_dos_por_uno() -> None:
    # Referencia: acciones 2:1 y precio implicito partido por dos SI es split.
    assert implied_split_ratio(_fila(200, 1000), _fila(100, 1000)) is not None


# ------------------------------------------------------------------- fixtures DB


@pytest.fixture
def db_tenant():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        tenant = Tenant(external_id="tenant-mh-bordes", name="Tenant MH Bordes")
        db.add(tenant)
        db.flush()
        db.info["tenant_id"] = tenant.id
        yield db


@pytest.fixture
def sin_redis(monkeypatch: pytest.MonkeyPatch):
    # Los commits del sync disparan la invalidacion de cache en after_commit;
    # None = sin cliente configurado (no-op, sin clear falso). Restaura solo.
    monkeypatch.setattr("app.core.cache._redis_client", lambda: None)  # noqa: SLF001


# -------------------------------------------------------------------- sync 13F


_CIK = "0001067983"  # Berkshire en REVIEWED_MANAGERS


def test_sync_sin_filings_marca_unavailable(db_tenant, sin_redis, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.services.connectors.form13f.recent_13f_filings", lambda cik, client=None: [])
    resultado = ManagerHoldingIngestionService().sync_manager(db_tenant, cik=_CIK)
    assert resultado["cik"] == _CIK
    assert resultado["manager"] == "Berkshire Hathaway Inc"
    assert resultado["status"] == "unavailable"
    assert resultado["reason"] == "no 13F-HR filings found"
    manager = db_tenant.scalar(select(FundManager).where(FundManager.cik == _CIK))
    assert manager.coverage == "unavailable"
    assert manager.synced_at is not None


def test_sync_tabla_no_encontrada_registra_error(
    db_tenant, sin_redis, monkeypatch: pytest.MonkeyPatch
) -> None:
    filing = {
        "accession_number": "0001067983-24-000001",
        "form": "13F-HR",
        "is_amendment": False,
        "report_date": "2024-03-31",
        "filing_date": "2024-05-01",
        "primary_document": "doc.xml",
    }
    monkeypatch.setattr(
        "app.services.connectors.form13f.recent_13f_filings", lambda cik, client=None: [filing]
    )
    monkeypatch.setattr(
        "app.services.connectors.form13f.information_table_url",
        lambda cik, accession, primary_document, client=None: None,
    )
    resultado = ManagerHoldingIngestionService().sync_manager(db_tenant, cik=_CIK)
    assert resultado["status"] == "ok"
    assert resultado["ingested_rows"] == 0
    assert resultado["errors"] == [
        {"accession": "0001067983-24-000001", "error": "information_table_not_found"}
    ]
    # Sin filas servidas y con errores: cobertura parcial (motivo exacto).
    assert resultado["verification_status"] == "partial"


def test_stored_coverage_sin_filas_servidas_es_ok(db_tenant) -> None:
    manager = FundManager(cik=_CIK, name="Berkshire Hathaway Inc", last_report_date=date(2024, 3, 31))
    db_tenant.add(manager)
    db_tenant.flush()
    cobertura = ManagerHoldingIngestionService()._stored_coverage(  # noqa: SLF001
        db_tenant, manager, date(2024, 3, 31), [{"accession": "A", "status": "ok"}], []
    )
    assert cobertura == "ok"


# --------------------------------------------------------------- latest_holdings


def test_latest_holdings_sin_filas(db_tenant) -> None:
    manager = FundManager(
        cik=_CIK, name="Berkshire Hathaway Inc", last_report_date=date(2024, 3, 31), coverage="ok"
    )
    db_tenant.add(manager)
    db_tenant.flush()
    resultado = ManagerHoldingIngestionService().latest_holdings(db_tenant, cik=_CIK)
    assert resultado["cik"] == _CIK
    assert resultado["status"] == "ok"
    assert resultado["verification"] == "verified"
    assert resultado["report_date"] == "2024-03-31"
    assert resultado["holdings"] == []


# ----------------------------------------------------------------- cabos sueltos


def test_verification_status_none() -> None:
    assert verification_status(None) is None


def test_sync_all_sin_filings(db_tenant, sin_redis, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.services.connectors.form13f.recent_13f_filings", lambda cik, client=None: [])
    resultado = ManagerHoldingIngestionService().sync_all(db_tenant)
    assert len(resultado["results"]) == len(REVIEWED_MANAGERS)
    assert {item["status"] for item in resultado["results"]} == {"unavailable"}
    assert resultado["limitations"] == LIMITATIONS


def test_stored_coverage_verificacion_no_ok(db_tenant) -> None:
    manager = FundManager(cik=_CIK, name="Berkshire Hathaway Inc")
    db_tenant.add(manager)
    db_tenant.flush()
    cobertura = ManagerHoldingIngestionService()._stored_coverage(  # noqa: SLF001
        db_tenant, manager, None, [{"accession": "A", "status": "mismatch"}], []
    )
    assert cobertura == "partial"


def test_change_labels_gestor_desconocido(db_tenant) -> None:
    assert (
        ManagerHoldingIngestionService().change_labels_for_cusip(db_tenant, cik="9999999999", cusip="X") == []
    )


def _holding(manager_id: int, accession: str, report: date, put_call: str = "") -> ManagerHolding:
    return ManagerHolding(
        manager_id=manager_id,
        accession_number=accession,
        report_date=report,
        filing_date=report,
        cusip="CUSIP001",
        name_of_issuer="EMPRESA",
        title_of_class="COM",
        put_call=put_call,
        shares=Decimal("100"),
    )


def test_change_labels_un_solo_periodo(db_tenant) -> None:
    manager = FundManager(cik=_CIK, name="Berkshire Hathaway Inc")
    db_tenant.add(manager)
    db_tenant.flush()
    db_tenant.add(_holding(manager.id, "ACC1", date(2024, 3, 31)))
    db_tenant.flush()
    assert (
        ManagerHoldingIngestionService().change_labels_for_cusip(db_tenant, cik=_CIK, cusip="CUSIP001") == []
    )


def test_change_labels_put_call_omitido(db_tenant) -> None:
    manager = FundManager(cik=_CIK, name="Berkshire Hathaway Inc")
    db_tenant.add(manager)
    db_tenant.flush()
    db_tenant.add(_holding(manager.id, "ACC1", date(2024, 3, 31), put_call="Put"))
    db_tenant.add(_holding(manager.id, "ACC2", date(2024, 6, 30), put_call="Put"))
    db_tenant.flush()
    # Las puts/calls no son posiciones largas: no generan etiqueta.
    assert (
        ManagerHoldingIngestionService().change_labels_for_cusip(db_tenant, cik=_CIK, cusip="CUSIP001") == []
    )


def test_sync_salto_de_escala_entre_trimestres(db_tenant, sin_redis, monkeypatch: pytest.MonkeyPatch) -> None:
    # Dos periodos base con totales x200: casi seguro un error de escala del filing.
    # Con menos de MIN_PRICED_ROWS filas la inferencia de escala no multiplica:
    # los totales son deterministicos.
    filings = [
        {
            "accession_number": "0001067983-24-000010",
            "form": "13F-HR",
            "is_amendment": False,
            "report_date": "2024-03-31",
            "filing_date": "2024-05-01",
            "primary_document": "doc1.xml",
        },
        {
            "accession_number": "0001067983-24-000020",
            "form": "13F-HR",
            "is_amendment": False,
            "report_date": "2024-06-30",
            "filing_date": "2024-08-01",
            "primary_document": "doc2.xml",
        },
    ]
    filas_por_url = {
        "url-0001067983-24-000010": [
            {
                "cusip": "CUSIP001",
                "title_of_class": "COM",
                "value_usd_thousands": "1000000",
                "ssh_prnamt": "1000",
            }
        ],
        "url-0001067983-24-000020": [
            {
                "cusip": "CUSIP001",
                "title_of_class": "COM",
                "value_usd_thousands": "200000000",
                "ssh_prnamt": "1000",
            }
        ],
    }
    monkeypatch.setattr(
        "app.services.connectors.form13f.recent_13f_filings", lambda cik, client=None: filings
    )
    monkeypatch.setattr(
        "app.services.connectors.form13f.information_table_url",
        lambda cik, accession, primary_document, client=None: f"url-{accession}",
    )
    monkeypatch.setattr(
        "app.services.connectors.form13f.fetch_information_table",
        lambda url, client=None: filas_por_url[url],
    )
    monkeypatch.setattr(
        "app.services.connectors.form13f.fetch_primary_summary", lambda cik, accession, client=None: None
    )
    resultado = ManagerHoldingIngestionService().sync_manager(db_tenant, cik=_CIK)
    assert resultado["ingested_rows"] == 2
    assert resultado["errors"] == [
        {
            "error": "scale_jump_between_quarters",
            "periods": ["2024-03-31", "2024-06-30"],
            "totals": ["1000000", "200000000"],
            "ratio": "200.0",
        }
    ]
    # El filing servido no se pudo contrastar (sin resumen): motivo exacto.
    assert resultado["verification_status"] == "unverified"
