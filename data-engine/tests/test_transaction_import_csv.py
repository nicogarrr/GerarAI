"""Pruebas exhaustivas para la importación masiva de transacciones (CSV y Excel).

Fulfills: VAL-DATA-006, VAL-DATA-007
Expected Behavior:
- Subida y parseo de CSV (coma, punto y coma, tabulador) y Excel XLSX
- Detección y mapeo automático de columnas en español e inglés
- Soporte para múltiples formatos de fecha (YYYY-MM-DD, DD/MM/YYYY, etc.)
- Validación estricta previa con reporte de errores por fila
- Modo preview para revisión sin impacto en base de datos
- Confirmación e inserción atómica (commit)
"""

from __future__ import annotations

import io
from datetime import UTC, date, datetime, timedelta

import openpyxl
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes.portfolio import router as portfolio_router
from app.core.database import Base, get_db
from app.core.local_date import local_today
from app.models.entities import Company, Portfolio, Position, Tenant, Transaction
from app.services.transaction_import_service import (
    ParsedTransaction,
    TransactionImportService,
    auto_detect_columns,
    parse_flexible_date,
)


@pytest.fixture
def env():
    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)

    with factory() as s:
        tenant = Tenant(external_id="tenant-csv-test", name="Tenant CSV Test", metadata_={})
        s.add(tenant)
        s.commit()
        tenant_id = tenant.id

        company = Company(
            ticker="SAN.MC",
            name="Banco Santander S.A.",
            exchange="BME",
            currency="EUR",
            sector="Financial Services",
            industry="Diversified Banking",
            company_type="operating",
            valuation_model="dcf",
        )
        s.add(company)

        company2 = Company(
            ticker="IBE.MC",
            name="Iberdrola S.A.",
            exchange="BME",
            currency="EUR",
            sector="Utilities",
            industry="Electric Utilities",
            company_type="operating",
            valuation_model="dcf",
        )
        s.add(company2)

        portfolio = Portfolio(
            tenant_id=tenant_id,
            name="Cartera Importaciones",
            base_currency="EUR",
            is_default=True,
            created_at=datetime.now(UTC),
        )
        s.add(portfolio)
        s.commit()
        port_id = portfolio.id

    def _db():
        with factory() as session:
            session.info["tenant_id"] = tenant_id
            yield session

    app = FastAPI()
    app.include_router(portfolio_router, prefix="/api/portfolio")
    app.dependency_overrides[get_db] = _db
    client = TestClient(app, raise_server_exceptions=True)
    yield client, factory, port_id, tenant_id


def test_auto_detect_columns_spanish_and_english():
    """Verifica detección de columnas en español e inglés."""
    headers_es = ["Fecha Operación", "Símbolo", "Tipo", "Títulos", "Precio Unitario", "Comisiones"]
    detected_es = auto_detect_columns(headers_es)
    assert detected_es["ticker"] == "Símbolo"
    assert detected_es["date"] == "Fecha Operación"
    assert detected_es["action"] == "Tipo"
    assert detected_es["quantity"] == "Títulos"
    assert detected_es["price"] == "Precio Unitario"
    assert detected_es["fees"] == "Comisiones"

    headers_en = ["Date", "Ticker", "Action", "Quantity", "Price", "Fees", "Currency"]
    detected_en = auto_detect_columns(headers_en)
    assert detected_en["ticker"] == "Ticker"
    assert detected_en["date"] == "Date"
    assert detected_en["quantity"] == "Quantity"
    assert detected_en["price"] == "Price"


def test_parse_flexible_date():
    """Verifica el soporte para múltiples formatos de fecha."""
    t = local_today()
    assert parse_flexible_date("2026-05-10") == date(2026, 5, 10)
    assert parse_flexible_date("10/05/2026") == date(2026, 5, 10)
    assert parse_flexible_date("10-05-2026") == date(2026, 5, 10)
    assert parse_flexible_date(datetime(2026, 5, 10, 14, 30)) == date(2026, 5, 10)

    # Fecha futura -> error
    future = t + timedelta(days=5)
    with pytest.raises(ValueError, match="futura"):
        parse_flexible_date(future.isoformat())


def test_preview_csv_comma_and_semicolon():
    """Verifica el modo preview con CSV delimitado por coma y punto y coma."""
    service = TransactionImportService()

    csv_comma = (
        b"Date,Ticker,Action,Quantity,Price,Fees\n"
        b"2026-01-15,SAN.MC,BUY,100,4.25,2.50\n"
        b"2026-02-10,IBE.MC,BUY,50,11.20,1.80\n"
    )

    prev1 = service.preview_import(csv_comma, "transactions.csv")
    assert prev1.success is True
    assert prev1.total_rows == 2
    assert prev1.valid_rows_count == 2
    assert prev1.invalid_rows_count == 0
    assert len(prev1.preview_items) == 2
    assert prev1.preview_items[0].ticker == "SAN.MC"
    assert prev1.preview_items[0].quantity == 100.0

    csv_semi = (
        "Fecha;Símbolo;Operación;Cantidad;Precio;Comisión\n"
        "15/01/2026;SAN.MC;COMPRA;200;4,30;3,00\n"
        "20/01/2026;IBE.MC;VENTA;50;11,50;2,00\n"
    ).encode()

    prev2 = service.preview_import(csv_semi, "movimientos.csv")
    assert prev2.success is True
    assert prev2.valid_rows_count == 2
    assert prev2.preview_items[0].quantity == 200.0
    assert prev2.preview_items[0].price == 4.30
    assert prev2.preview_items[1].action == "sell"


def test_preview_excel_xlsx():
    """Verifica el soporte para archivos Excel XLSX."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Transacciones"
    ws.append(["Fecha", "Activo", "Tipo", "Títulos", "Precio"])
    ws.append(["2026-03-01", "SAN.MC", "Compra", 150, 4.40])
    ws.append(["2026-03-05", "IBE.MC", "Compra", 80, 11.35])

    buf = io.BytesIO()
    wb.save(buf)
    excel_bytes = buf.getvalue()

    service = TransactionImportService()
    prev = service.preview_import(excel_bytes, "cartera.xlsx")
    assert prev.success is True
    assert prev.total_rows == 2
    assert prev.valid_rows_count == 2
    assert prev.preview_items[0].ticker == "SAN.MC"
    assert prev.preview_items[0].quantity == 150.0


def test_preview_validation_errors_report():
    """Verifica que las filas inválidas reportan errores detallados."""
    service = TransactionImportService()

    csv_invalid = (
        b"Date,Ticker,Action,Quantity,Price\n"
        b",SAN.MC,BUY,100,4.25\n"  # Fecha vacía
        b"2026-01-15,,BUY,100,4.25\n"  # Ticker vacío
        b"2026-01-15,SAN.MC,BUY,-50,4.25\n"  # Cantidad negativa
        b"2026-01-15,SAN.MC,BUY,50,-4.25\n"  # Precio negativo
        b"2026-01-15,SAN.MC,DESCONOCIDO,50,4.25\n"  # Acción inválida
    )

    prev = service.preview_import(csv_invalid, "test.csv")
    assert prev.success is False
    assert len(prev.errors) >= 5
    assert prev.valid_rows_count == 0


def test_api_import_preview_endpoint(env):
    """Verifica el endpoint HTTP POST /api/portfolio/import/preview."""
    client, _, _, _ = env

    content = "Fecha,Activo,Operacion,Cantidad,Precio\n2026-01-10,SAN.MC,COMPRA,120,4.10"
    payload = {"content": content, "filename": "operaciones.csv"}

    res = client.post("/api/portfolio/import/preview", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["valid_rows_count"] == 1
    assert data["preview_items"][0]["ticker"] == "SAN.MC"


def test_api_import_commit_endpoint(env):
    """Verifica el endpoint HTTP POST /api/portfolio/import/commit."""
    client, factory, port_id, tenant_id = env

    items = [
        ParsedTransaction(
            row_number=2,
            ticker="SAN.MC",
            date="2026-01-10",
            action="buy",
            quantity=300.0,
            price=4.20,
            fees=1.50,
            currency="EUR",
        ),
        ParsedTransaction(
            row_number=3,
            ticker="IBE.MC",
            date="2026-01-12",
            action="buy",
            quantity=100.0,
            price=11.10,
            fees=2.00,
            currency="EUR",
        ),
    ]

    commit_payload = {"transactions": [it.model_dump() for it in items]}
    res = client.post("/api/portfolio/import/commit", json=commit_payload)
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["imported_count"] == 2

    # Verificar que se crearon en la base de datos
    with factory() as s:
        s.info["tenant_id"] = tenant_id
        txs = s.scalars(select(Transaction)).all()
        assert len(txs) >= 2
        tickers = {t.company.ticker for t in txs if t.company}
        assert "SAN.MC" in tickers
        assert "IBE.MC" in tickers

        # Verificar que la posición se actualizó
        positions = s.scalars(select(Position)).all()
        assert len(positions) >= 2


def _csv_bytes(*rows: str) -> bytes:
    header = "ticker;date;action;quantity;price;fees;currency"
    return ("\n".join([header, *rows])).encode("utf-8")


def test_preview_flags_duplicate_rows_as_warning():
    """Veracidad: filas idénticas dentro del archivo se avisan (no se cuelan dos veces en silencio)."""
    service = TransactionImportService()
    content = _csv_bytes(
        "SAN.MC;2024-01-15;compra;100;3.50;1.00;EUR",
        "SAN.MC;2024-01-15;compra;100;3.50;1.00;EUR",
        "IBE.MC;2024-01-16;compra;50;10.00;0;EUR",
    )
    result = service.preview_import(content, "dupes.csv")
    assert result.success is True
    assert result.valid_rows_count == 3
    assert len(result.warnings) == 1
    assert result.warnings[0].row_number == 3
    assert "duplicada" in result.warnings[0].message


def test_preview_empty_action_cell_is_error_not_silent_buy():
    """Una celda de acción vacía en columna mapeada es error: nunca se asume compra."""
    service = TransactionImportService()
    content = _csv_bytes("SAN.MC;2024-01-15;;100;3.50;1.00;EUR")
    result = service.preview_import(content, "venta.csv")
    assert result.success is False
    assert any(e.field == "action" for e in result.errors)
    assert result.valid_rows_count == 0


def test_commit_skips_exact_duplicates_and_records_provenance(env):
    """Reimportar el mismo lote no duplica la cartera; cada pata lleva lote y fichero."""
    _, factory, _, _ = env
    service = TransactionImportService()
    txs = [
        ParsedTransaction(row_number=2, ticker="SAN.MC", date="2024-01-15", action="buy", quantity=100, price=3.5, fees=1.0, currency="EUR"),
    ]
    with factory() as s:
        s.info["tenant_id"] = "tenant-csv-test"
        first = service.commit_import(s, txs, source_filename="broker-enero.csv")
        assert first["imported_count"] == 1
        assert first["duplicates_skipped"] == 0
        assert first["import_batch"].startswith("csv-")
        from app.models.entities import Transaction
        row = s.query(Transaction).filter(Transaction.action == "buy").first()
        assert row.raw_payload["notes"] is not None
        assert "broker-enero.csv" in row.raw_payload["notes"]
        assert first["import_batch"] in row.raw_payload["notes"]

        # Segunda importación del mismo fichero: se omite, no duplica
        second = service.commit_import(s, txs, source_filename="broker-enero.csv")
        assert second["imported_count"] == 0
        assert second["duplicates_skipped"] == 1
        count = s.query(Transaction).filter(Transaction.action == "buy").count()
        assert count == 1


def test_preview_isin_column_warns_and_validates():
    """Una columna ISIN se valida como ISIN y se avisa de la resolución; no pasa como ticker."""
    service = TransactionImportService()
    content = ("isin;date;action;quantity;price\n"
               "ES0113900J37;2024-01-15;compra;100;3.50\n")
    result = service.preview_import(content.encode(), "isin.csv")
    assert result.success is True
    assert any("ISIN" in w.message for w in result.warnings)

    bad = service.preview_import((b"isin;date;action;quantity;price\n"
                                  b"NOTANISIN;2024-01-15;compra;100;3.50\n"), "isin.csv")
    assert bad.success is False
    assert any("ISIN" in e.message for e in bad.errors)


def test_preview_ambiguous_date_warns():
    """01/02/2024 es ambiguo (1 feb vs 2 ene): se interpreta DD/MM y se avisa."""
    service = TransactionImportService()
    content = ("ticker;date;action;quantity;price\n"
               "SAN.MC;01/02/2024;compra;100;3.50\n")
    result = service.preview_import(content.encode(), "fechas.csv")
    assert result.success is True
    assert any("ambigua" in w.message for w in result.warnings)
    assert result.preview_items[0].date == "2024-02-01"


def test_commit_resolves_isin_to_registered_ticker(env):
    """Un ISIN registrado importa sobre el ticker de la empresa; uno desconocido falla."""
    _, factory, _, _ = env
    from app.models.entities import Company

    with factory() as s:
        company = s.query(Company).filter(Company.ticker == "SAN.MC").first()
        company.isin = "ES0113900J37"
        s.commit()
        s.info["tenant_id"] = "tenant-csv-test"

        service = TransactionImportService()
        ok = service.commit_import(s, [ParsedTransaction(
            row_number=2, ticker="ES0113900J37", date="2024-01-15",
            action="buy", quantity=10, price=3.5, fees=0.0, currency="EUR",
        )], source_filename="isin.csv")
        assert ok["imported_count"] == 1
        from app.models.entities import Transaction
        row = s.query(Transaction).filter(Transaction.action == "buy").first()
        assert row.company.ticker == "SAN.MC"

        with pytest.raises(ValueError, match="sin empresa registrada"):
            service.commit_import(s, [ParsedTransaction(
                row_number=3, ticker="US0000000000", date="2024-01-15",
                action="buy", quantity=1, price=1.0, fees=0.0, currency="USD",
            )], source_filename="isin.csv")



def test_commit_inserts_in_chronological_order(env):
    """Una venta anterior a una compra listada después no debe fallar por sobreventa."""
    _, factory, _, _ = env
    service = TransactionImportService()
    with factory() as s:
        s.info["tenant_id"] = "tenant-csv-test"
        # El archivo lista la venta del día 10 antes que la compra del día 5
        txs = [
            ParsedTransaction(row_number=2, ticker="IBE.MC", date="2024-01-10", action="sell", quantity=5, price=11.0, fees=0.0, currency="EUR"),
            ParsedTransaction(row_number=3, ticker="IBE.MC", date="2024-01-05", action="buy", quantity=10, price=10.0, fees=0.0, currency="EUR"),
        ]
        result = service.commit_import(s, txs, source_filename="desordenado.csv")
        assert result["imported_count"] == 2
        assert result["duplicates_skipped"] == 0


def test_dedupe_is_per_portfolio_not_tenant_wide(env):
    """Una compra idéntica en OTRA cartera del mismo tenant es legítima: no se omite."""
    _, factory, _, _ = env
    from datetime import UTC, datetime

    from app.models.entities import Portfolio, Transaction

    service = TransactionImportService()
    with factory() as s:
        s.info["tenant_id"] = "tenant-csv-test"
        s.add(Portfolio(tenant_id="tenant-csv-test", name="Cartera B", base_currency="EUR", is_default=False, created_at=datetime.now(UTC)))
        s.commit()

        # Importar en la cartera por defecto (la crea ensure_portfolio)
        first = service.commit_import(s, [ParsedTransaction(
            row_number=2, ticker="SAN.MC", date="2024-03-01", action="buy",
            quantity=10, price=3.5, fees=0.0, currency="EUR",
        )], source_filename="a.csv")
        assert first["imported_count"] == 1

        # Misma pata dirigida a la otra cartera (mismo tenant): debe importarse
        other = s.query(Portfolio).filter(Portfolio.name == "Cartera B").first()
        s.query(Transaction).filter(Transaction.action == "buy").first().portfolio_id = other.id
        s.commit()

        second = service.commit_import(s, [ParsedTransaction(
            row_number=2, ticker="SAN.MC", date="2024-03-01", action="buy",
            quantity=10, price=3.5, fees=0.0, currency="EUR",
        )], source_filename="a.csv")
        assert second["imported_count"] == 1
        assert second["duplicates_skipped"] == 0

        # Y reimportar en la MISMA cartera sí se omite
        third = service.commit_import(s, [ParsedTransaction(
            row_number=2, ticker="SAN.MC", date="2024-03-01", action="buy",
            quantity=10, price=3.5, fees=0.0, currency="EUR",
        )], source_filename="a.csv")
        assert third["imported_count"] == 0
        assert third["duplicates_skipped"] == 1


def test_identical_legitimate_operations_all_import_and_reimport_skips(env):
    """Dos compras idénticas el mismo día son legítimas: importan las dos.
    Reimportar el mismo CSV no duplica ninguna."""
    _, factory, _, _ = env
    from app.models.entities import Transaction

    service = TransactionImportService()
    rows = [
        ParsedTransaction(row_number=2, ticker="SAN.MC", date="2024-03-01", action="buy",
                          quantity=10, price=3.5, fees=0.0, currency="EUR"),
        ParsedTransaction(row_number=3, ticker="SAN.MC", date="2024-03-01", action="buy",
                          quantity=10, price=3.5, fees=0.0, currency="EUR"),
    ]
    with factory() as s:
        s.info["tenant_id"] = "tenant-csv-test"
        first = service.commit_import(s, rows, source_filename="a.csv")
        assert first["imported_count"] == 2
        assert first["duplicates_skipped"] == 0

        second = service.commit_import(s, rows, source_filename="a.csv")
        assert second["imported_count"] == 0
        assert second["duplicates_skipped"] == 2

        # Importar solo UNA de las patas otra vez: no es duplicado (solo hay 2, se pide la 3a)
        third = service.commit_import(s, rows[:1], source_filename="b.csv")
        assert third["imported_count"] == 1

        count = s.query(Transaction).filter(Transaction.action == "buy").count()
        assert count == 3


def test_reimport_with_new_company_does_not_duplicate(env):
    """Primera importación con empresa NO registrada: la pata recibe identidad
    estable desde el primer momento, así reimportar el mismo CSV no duplica."""
    _, factory, _, _ = env
    from app.models.entities import Company, Transaction

    service = TransactionImportService()
    rows = [ParsedTransaction(row_number=2, ticker="NUEVA.MC", date="2024-03-01", action="buy",
                              quantity=5, price=10.0, fees=0.0, currency="EUR")]
    with factory() as s:
        s.info["tenant_id"] = "tenant-csv-test"
        first = service.commit_import(s, rows, source_filename="a.csv")
        assert first["imported_count"] == 1
        assert s.query(Company).filter(Company.ticker == "NUEVA.MC").count() == 1

        second = service.commit_import(s, rows, source_filename="a.csv")
        assert second["imported_count"] == 0
        assert second["duplicates_skipped"] == 1
        assert s.query(Transaction).filter(Transaction.action == "buy").count() == 1
