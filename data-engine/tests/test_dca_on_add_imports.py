"""Importar (fichero genérico o IBKR) encola la señal DCA de lo que estrena,
después de confirmar, sin cambiar la respuesta ni romperla si la cola falla."""
from __future__ import annotations

from datetime import date

from app.api.routes import portfolio as portfolio_module
from app.services.transaction_import_service import TransactionImportService
from tests.auth_helpers import signed_request
from tests.test_portfolio_import_ibkr_xml_route import SECRET, _client


def _spy(monkeypatch):
    calls = []
    monkeypatch.setattr("app.services.dca_on_add.enqueue_dca_for_new_tracked",
                        lambda db: calls.append(db.info.get("tenant_id")) or 1)
    return calls


def test_importar_xml_ibkr_encola_la_senal_dca(monkeypatch):
    client, tenant, user, tenant_id = _client(monkeypatch)
    calls = _spy(monkeypatch)
    day = date.today().strftime("%Y%m%d")
    xml = (
        '<FlexQueryResponse><FlexStatements><FlexStatement accountId="U1" '
        f'toDate="{day}"><Trade symbol="AAPL" tradeID="X1" buySell="BUY" '
        f'quantity="1" tradePrice="10" tradeDate="{day}"/>'
        "</FlexStatement></FlexStatements></FlexQueryResponse>"
    )
    res = signed_request(client, SECRET, tenant, user, "POST", "/api/portfolio/import/ibkr/xml", json_body={"xml": xml})
    assert res.status_code == 200, res.text
    assert calls == [tenant_id]


def test_importar_fichero_encola_solo_si_se_importo_algo(monkeypatch):
    client, tenant, user, tenant_id = _client(monkeypatch)
    calls = _spy(monkeypatch)
    results = iter([
        {"success": True, "message": "ok", "imported_count": 2, "duplicates_skipped": 0, "import_batch": "b1"},
        {"success": True, "message": "ok", "imported_count": 0, "duplicates_skipped": 2, "import_batch": "b1"},
    ])
    monkeypatch.setattr(TransactionImportService, "commit_import", lambda self, db, txs, source_filename=None: next(results))
    body = {"transactions": [{"row_number": 1, "date": "2026-10-01", "ticker": "AAPL", "action": "buy", "quantity": 1, "price": 10, "currency": "USD"}]}
    for _ in range(2):
        res = signed_request(client, SECRET, tenant, user, "POST", "/api/portfolio/import/commit", json_body=body)
        assert res.status_code == 200, res.text
    assert calls == [tenant_id]
    assert portfolio_module.commit_transaction_import is not None
