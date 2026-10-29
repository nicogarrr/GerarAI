"""Insider (Form 4) y 13F alimentan la tesis y la ficha (conexion 10b).

``ticker_ownership_signals`` resume lo YA persistido (sin red): compras y
ventas de insiders en mercado abierto (codigos P/S, filas no derivadas) en una
ventana, y los gestores revisados que declaran el valor en su ultimo 13F con
su cambio trimestral. La tesis lo lee como bloque de evidencia y como hechos
citables del paquete del narrador.
"""
from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import Company, FundManager, ManagerHolding, Tenant
from app.models.entities import InsiderFiling, InsiderTransaction
from app.services import ticker_ownership_signals as signals
from app.services.ticker_ownership_signals import (
    holders_signal,
    insider_signal,
    ownership_fact_lines,
    ownership_markdown,
    ownership_signals,
)

AS_OF = date(2026, 10, 27)


def _db() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    tenant = Tenant(external_id=f"own-{uuid4().hex[:8]}", name="Own")
    db.add(tenant)
    db.flush()
    db.info["tenant_id"] = tenant.id
    return db


def _filing(db: Session, ticker: str, filing_date: str = "2026-09-01") -> InsiderFiling:
    filing = InsiderFiling(
        accession_number=uuid4().hex[:20],
        form="4",
        issuer_cik="0000000001",
        issuer_ticker=ticker,
        filing_date=filing_date,
        parser_version="test",
    )
    db.add(filing)
    db.flush()
    return filing


def _tx(db, filing, *, insider, code, shares, price, tx_date, derivative=False, plan=False, ticker="UBER"):
    db.add(
        InsiderTransaction(
            fingerprint=uuid4().hex,
            filing_id=filing.id,
            accession_number=filing.accession_number,
            form="4",
            issuer_ticker=ticker,
            insider=insider,
            role="Director",
            code=code,
            shares=shares,
            price=price,
            value=None if price is None else shares * price,
            tx_date=tx_date,
            is_derivative=derivative,
            rule_10b5_1=plan,
        )
    )


def test_insider_signal_cuenta_solo_mercado_abierto_en_la_ventana():
    db = _db()
    filing = _filing(db, "UBER")
    _tx(db, filing, insider="Ana", code="P", shares=1000, price=70.0, tx_date="2026-09-10")
    _tx(db, filing, insider="Bea", code="P", shares=500, price=72.0, tx_date="2026-08-01")
    _tx(db, filing, insider="Ana", code="P", shares=100, price=71.0, tx_date="2026-09-11")
    _tx(db, filing, insider="Carlos", code="S", shares=2000, price=80.0, tx_date="2026-07-01", plan=True)
    # Fuera: concesion (A), derivado, fuera de ventana, otro ticker.
    _tx(db, filing, insider="Dani", code="A", shares=9999, price=0.0, tx_date="2026-09-01")
    _tx(db, filing, insider="Eva", code="S", shares=9999, price=10.0, tx_date="2026-09-01", derivative=True)
    _tx(db, filing, insider="Fede", code="S", shares=9999, price=10.0, tx_date="2025-01-01")
    _tx(db, filing, insider="Gus", code="P", shares=9999, price=10.0, tx_date="2026-09-01", ticker="POOL")
    db.commit()

    result = insider_signal(db, "uber", as_of=AS_OF, window_days=180)

    assert result["status"] == "ok"
    assert result["window_days"] == 180
    assert result["buys"] == {"trades": 3, "insiders": 2, "shares": 1600.0, "value": 70000.0 + 36000.0 + 7100.0}
    assert result["sells"] == {"trades": 1, "insiders": 1, "shares": 2000.0, "value": 160000.0, "planned_10b5_1": 1}
    assert result["net_value"] == pytest.approx(113100.0 - 160000.0)
    assert result["cluster_buying"] is False
    assert result["last_date"] == "2026-09-11"
    assert result["reading"] == "Ventas netas de insiders"


def test_insider_signal_detecta_compras_en_grupo_y_usa_fecha_del_filing_si_falta():
    db = _db()
    filing = _filing(db, "UBER", filing_date="2026-10-01")
    for name in ("Ana", "Bea", "Carlos"):
        _tx(db, filing, insider=name, code="P", shares=100, price=50.0, tx_date=None)
    db.commit()

    result = insider_signal(db, "UBER", as_of=AS_OF)

    assert result["buys"]["insiders"] == 3
    assert result["cluster_buying"] is True
    assert result["last_date"] == "2026-10-01"
    assert result["reading"] == "Compras en grupo de insiders (3 o más)"


def test_insider_signal_sin_operaciones_es_sin_datos_no_ceros():
    db = _db()
    result = insider_signal(db, "UBER", as_of=AS_OF)
    assert result["status"] == "sin_datos"
    assert "Form 4" in result["detail"]


def _manager(db, cik: str, name: str, report: date) -> FundManager:
    manager = FundManager(cik=cik, name=name, last_report_date=report)
    db.add(manager)
    db.flush()
    return manager


def _holding(db, manager, report: date, cusip: str, shares: int, value_k: int):
    db.add(
        ManagerHolding(
            manager_id=manager.id,
            accession_number=f"{manager.cik}-{report.isoformat()}",
            report_date=report,
            filing_date=report,
            cusip=cusip,
            name_of_issuer="UBER TECHNOLOGIES",
            shares=Decimal(shares),
            value_usd_thousands=Decimal(value_k),
        )
    )


def test_holders_signal_resume_gestores_y_cambio_trimestral(monkeypatch):
    db = _db()
    q2, q3 = date(2026, 6, 30), date(2026, 9, 30)
    cusip = "90353T100"
    db.add(Company(ticker="UBER", name="Uber Technologies", isin=f"US{cusip}5"))
    from app.services.investors import INVESTORS

    with_cik = [inv for inv in INVESTORS if inv.cik][:3]
    monkeypatch.setattr(signals, "REVIEWED_INVESTORS", tuple(with_cik))
    monkeypatch.setattr(
        signals, "holders_by_ticker",
        lambda _db, _t: {
            "status": "ok",
            "cusip": cusip,
            "holders": [
                {"slug": with_cik[0].slug, "name": with_cik[0].name, "report_date": q3.isoformat(), "value_usd": 9_000_000.0, "shares": 150.0},
                {"slug": with_cik[1].slug, "name": with_cik[1].name, "report_date": q3.isoformat(), "value_usd": 1_000_000.0, "shares": 20.0},
            ],
            "managers_with_data": 3,
            "managers_without_data": 0,
            "limitations": ["13F con hasta 45 días de retraso."],
        },
    )
    monkeypatch.setattr(
        signals, "_manager_changes_for_cusip",
        lambda _db, inv, _cusip: {
            with_cik[0].slug: "increased",
            with_cik[1].slug: "new",
            with_cik[2].slug: "closed",
        }[inv.slug],
    )

    result = holders_signal(db, "UBER")

    assert result["status"] == "ok"
    assert result["holders_count"] == 2
    assert result["managers_with_data"] == 3
    assert result["report_date"] == q3.isoformat()
    assert result["total_value_usd"] == 10_000_000.0
    assert result["changes"] == {"new": 1, "increased": 1, "decreased": 0, "closed": 1}
    assert [h["name"] for h in result["top_holders"]] == [with_cik[0].name, with_cik[1].name]
    assert result["top_holders"][1]["change"] == "new"
    assert result["exited"] == [with_cik[2].name]


def test_holders_signal_sin_identificador_no_afirma_nada(monkeypatch):
    db = _db()
    monkeypatch.setattr(
        signals, "holders_by_ticker",
        lambda _db, _t: {"status": "sin_identificador", "identity_source": None, "holders": []},
    )
    result = holders_signal(db, "CGEO.L")
    assert result["status"] == "sin_datos"
    assert "CUSIP" in result["detail"]


def test_holders_signal_ticker_fuera_del_universo(monkeypatch):
    db = _db()
    monkeypatch.setattr(signals, "holders_by_ticker", lambda _db, _t: None)
    assert holders_signal(db, "ZZZZ")["status"] == "sin_datos"


def test_manager_changes_for_cusip_compara_los_dos_ultimos_13f():
    db = _db()
    from app.services.investors import INVESTORS
    from app.services.manager_holding_ingestion_service import REVIEWED_MANAGERS

    inv = next(i for i in INVESTORS if i.cik and i.cik in REVIEWED_MANAGERS)
    q2, q3 = date(2026, 6, 30), date(2026, 9, 30)
    manager = _manager(db, inv.cik, inv.name, q3)
    _holding(db, manager, q2, "90353T100", 100, 7000)
    _holding(db, manager, q3, "90353T100", 150, 11000)
    _holding(db, manager, q2, "OTHER0000", 10, 10)
    db.commit()

    assert signals._manager_changes_for_cusip(db, inv, "90353T100") == "increased"
    assert signals._manager_changes_for_cusip(db, inv, "OTHER0000") == "closed"
    assert signals._manager_changes_for_cusip(db, inv, "NOPE00000") is None


def _sample_signals() -> dict:
    return {
        "ticker": "UBER",
        "insider": {
            "status": "ok", "window_days": 180,
            "buys": {"trades": 3, "insiders": 3, "shares": 300.0, "value": 15000.0},
            "sells": {"trades": 1, "insiders": 1, "shares": 2000.0, "value": 160000.0, "planned_10b5_1": 1},
            "net_value": -145000.0, "cluster_buying": True, "last_date": "2026-10-01",
            "reading": "Compras en grupo de insiders (3 o más)", "source": "SEC EDGAR · Form 4",
        },
        "holders": {
            "status": "ok", "holders_count": 2, "managers_with_data": 5,
            "report_date": "2026-09-30", "total_value_usd": 10_000_000.0,
            "changes": {"new": 1, "increased": 1, "decreased": 0, "closed": 1},
            "top_holders": [{"name": "Fundsmith", "value_usd": 9_000_000.0, "change": "increased"}],
            "exited": ["Pershing Square"], "source": "SEC EDGAR · Form 13F",
            "limitations": ["13F con hasta 45 días de retraso."],
        },
    }


def test_ownership_markdown_en_espanol_con_fuente_y_limites():
    text = ownership_markdown(_sample_signals())
    assert "Insiders (Form 4" in text
    assert "Compras en grupo de insiders" in text
    assert "1 con plan 10b5-1" in text
    assert "Fondos (13F" in text
    assert "Fundsmith" in text and "aumenta" in text
    assert "Pershing Square" in text
    assert "45 días" in text


def test_ownership_markdown_sin_datos_lo_dice():
    text = ownership_markdown({
        "ticker": "UBER",
        "insider": {"status": "sin_datos", "detail": "Sin compras ni ventas Form 4 persistidas."},
        "holders": {"status": "sin_datos", "detail": "Sin CUSIP verificado."},
    })
    assert "Sin compras ni ventas Form 4 persistidas." in text
    assert "Sin CUSIP verificado." in text


def test_ownership_fact_lines_son_hechos_citables_con_fuente():
    lines = ownership_fact_lines(_sample_signals())
    assert len(lines) == 2
    insider_text, insider_source = lines[0]
    assert "UBER" in insider_text and "3 insiders" in insider_text
    assert insider_source.startswith("SEC EDGAR · Form 4")
    holders_text, holders_source = lines[1]
    assert "2 de 5 gestores" in holders_text
    assert holders_source.startswith("SEC EDGAR · Form 13F")
    assert ownership_fact_lines({"insider": {"status": "sin_datos"}, "holders": {"status": "sin_datos"}}) == []


def test_ownership_signals_nunca_lanza(monkeypatch):
    db = _db()

    def boom(*_a, **_k):
        raise RuntimeError("tabla caida")

    monkeypatch.setattr(signals, "holders_by_ticker", boom)
    result = ownership_signals(db, "UBER", as_of=AS_OF)
    assert result["ticker"] == "UBER"
    assert result["insider"]["status"] == "sin_datos"
    assert result["holders"]["status"] == "pendiente"


def test_fact_pack_incluye_hechos_de_insiders_y_13f_con_su_fuente():
    from types import SimpleNamespace

    from app.services.thesis_deep_narrative import fact_pack

    company = SimpleNamespace(currency="USD", ticker="UBER", name="Uber")
    pack = fact_pack(
        company=company,
        valuation={"status": "ok", "current_price": 70.0, "base_value": 90.0},
        long_term_model={},
        hypothesis=None,
        news_items=[],
        ownership_facts=ownership_fact_lines(_sample_signals()),
    )
    insider = next(f for f in pack if f["texto"].startswith("Insiders de UBER"))
    assert insider["fuente"].startswith("SEC EDGAR · Form 4")
    holders = next(f for f in pack if "gestores revisados declaran UBER" in f["texto"])
    assert holders["fuente"].startswith("SEC EDGAR · Form 13F")


def test_fact_pack_sin_ownership_no_cambia():
    from types import SimpleNamespace

    from app.services.thesis_deep_narrative import fact_pack

    company = SimpleNamespace(currency="USD", ticker="UBER", name="Uber")
    kwargs = dict(
        company=company,
        valuation={"status": "ok", "current_price": 70.0, "base_value": 90.0},
        long_term_model={}, hypothesis=None, news_items=[],
    )
    assert fact_pack(**kwargs) == fact_pack(**kwargs, ownership_facts=[])


def test_sources_markdown_de_la_tesis_lista_insiders_y_13f():
    from app.services.thesis_service import ThesisService

    sample = _sample_signals()
    md = ThesisService()._sources_markdown({"insider": sample["insider"], "holders": sample["holders"]})
    assert "Insiders (Form 4): conseguido (SEC EDGAR · Form 4: 3 compras y 1 ventas en 180 días." in md
    assert "Fondos (13F): conseguido (SEC EDGAR · Form 13F: 2 de 5 gestores revisados" in md

    pending = ThesisService()._sources_markdown({
        "insider": {"status": "sin_datos", "detail": "Sin Form 4."},
        "holders": {"status": "sin_datos", "detail": "Sin CUSIP."},
    })
    assert "Insiders (Form 4): pendiente (Sin Form 4.)" in pending
    assert "Fondos (13F): pendiente (Sin CUSIP.)" in pending


def test_evidencia_de_la_tesis_incluye_insider_y_13f_sin_red(monkeypatch):
    from types import SimpleNamespace

    from app.services.thesis_evidence_service import ThesisEvidenceService

    db = _db()
    filing = _filing(db, "UBER")
    _tx(db, filing, insider="Ana", code="P", shares=10, price=50.0, tx_date=date.today().isoformat())
    db.commit()
    monkeypatch.setattr(signals, "holders_by_ticker", lambda _db, _t: None)
    blocks = ThesisEvidenceService._collect_ownership(db, SimpleNamespace(ticker="uber"))
    assert blocks["insider"]["status"] == "ok"
    assert blocks["insider"]["buys"]["value"] == 500.0
    assert blocks["holders"]["status"] == "sin_datos"


def test_el_memo_de_la_tesis_anade_la_seccion_24_de_insiders_y_13f():
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "app/services/thesis_service.py").read_text(encoding="utf-8")
    assert "## 24. Insiders (Form 4) y fondos (13F)" in source
    assert "ownership_markdown(" in source
    assert "ownership_facts=ownership_fact_lines(" in source


def test_api_ownership_signals_resume_por_tenant(monkeypatch):
    from fastapi.testclient import TestClient

    import main
    from app.core import auth as auth_module
    from app.core.database import SessionLocal, init_db
    from app.seed import seed
    from tests.auth_helpers import auth_settings, signed_request

    init_db()
    seed()
    secret = "tenant-test-secret-with-at-least-32-characters"
    monkeypatch.setattr(
        auth_module, "get_settings",
        lambda: auth_settings(strict=True, secret=secret, app_env="local"),
    )
    client = TestClient(main.app)
    suffix = uuid4().hex[:8]
    tenant_a, tenant_b = f"own-a-{suffix}", f"own-b-{suffix}"
    ticker = f"Z{suffix[:4].upper()}"
    db = SessionLocal()
    tenant_row = Tenant(external_id=tenant_a, name="Own A")
    db.add(tenant_row)
    db.flush()
    db.info["tenant_id"] = tenant_row.id
    filing = _filing(db, ticker)
    _tx(db, filing, insider="Ana", code="P", shares=10, price=5.0, tx_date=date.today().isoformat(), ticker=ticker)
    db.commit()
    db.close()

    own = signed_request(client, secret, tenant_a, "user-a", "GET", "/api/insider/ownership-signals", params={"ticker": ticker.lower()})
    assert own.status_code == 200, own.text
    body = own.json()
    assert body["ticker"] == ticker
    assert body["insider"]["status"] == "ok"
    assert body["insider"]["buys"]["value"] == 50.0
    assert body["holders"]["status"] in {"sin_datos", "pendiente"}

    other = signed_request(client, secret, tenant_b, "user-b", "GET", "/api/insider/ownership-signals", params={"ticker": ticker})
    assert other.status_code == 200
    assert other.json()["insider"]["status"] == "sin_datos"


def test_change_labels_for_cusip_equivale_al_diff_completo():
    """La lectura acotada por cusip da las mismas etiquetas que changes().

    La ficha solo necesita un cusip por gestor; cargar la cartera entera de
    cada gestor revisado (~32) superaba el presupuesto de lectura de la ficha
    en valores muy cubiertos (AAPL) y el panel 13F fallaba al cargar.
    """
    db = _db()
    from app.services.investors import INVESTORS
    from app.services.manager_holding_ingestion_service import (
        REVIEWED_MANAGERS,
        ManagerHoldingIngestionService,
    )

    inv = next(i for i in INVESTORS if i.cik and i.cik in REVIEWED_MANAGERS)
    q2, q3 = date(2026, 6, 30), date(2026, 9, 30)
    manager = _manager(db, inv.cik, inv.name, q3)
    _holding(db, manager, q2, "037833100", 100, 7000)  # AAPL: aumenta
    _holding(db, manager, q3, "037833100", 150, 11000)
    _holding(db, manager, q2, "OTHER0000", 10, 10)  # sale
    _holding(db, manager, q3, "NEW00000A", 5, 5)  # nueva
    _holding(db, manager, q2, "SAME00000", 20, 20)  # mantiene
    _holding(db, manager, q3, "SAME00000", 20, 21)
    # Ruido: filas de otros cusips que el diff completo cargaria una a una.
    for n in range(50):
        _holding(db, manager, q2, f"FILL{n:05d}", 1, 1)
        _holding(db, manager, q3, f"FILL{n:05d}", 1, 1)
    db.commit()

    service = ManagerHoldingIngestionService()
    full = {row["cusip"]: row["change"] for row in service.changes(db, cik=inv.cik)["changes"]}
    assert full["037833100"] == "increased"  # el diff completo sigue igual
    for cusip in ("037833100", "OTHER0000", "NEW00000A", "SAME00000"):
        assert service.change_labels_for_cusip(db, cik=inv.cik, cusip=cusip) == [full[cusip]]
    assert service.change_labels_for_cusip(db, cik=inv.cik, cusip="NOPE00000") == []


def test_change_labels_for_cusip_enmienda_que_omite_el_cusip():
    """Una enmienda vigente que omite el cusip marca la posicion cerrada.

    Regresion del PR #3025: elegir el accession solo entre los filings que
    contienen el cusip servia el filing base (mas viejo) y resucitaba una
    posicion que la enmienda mas reciente ya habia retirado; el diff
    completo de changes() la daba por cerrada. Repro del piloto: Q2 AAPL
    100, Q3 base AAPL 150, enmienda Q3 mas nueva con OTHER sin AAPL.
    """
    db = _db()
    from app.services.manager_holding_ingestion_service import ManagerHoldingIngestionService

    q2, q3 = date(2026, 6, 30), date(2026, 9, 30)
    manager = _manager(db, "0000000001", "Example", q3)
    _holding(db, manager, q2, "037833100", 100, 100)
    _holding(db, manager, q3, "037833100", 150, 150)
    db.add(
        ManagerHolding(
            manager_id=manager.id,
            accession_number="amended-latest",
            report_date=q3,
            filing_date=date(2026, 10, 15),
            cusip="OTHER0000",
            name_of_issuer="Other",
            shares=Decimal(10),
            value_usd_thousands=Decimal(10),
        )
    )
    db.commit()

    service = ManagerHoldingIngestionService()
    full = [row["change"] for row in service.changes(db, cik=manager.cik)["changes"] if row["cusip"] == "037833100"]
    narrow = service.change_labels_for_cusip(db, cik=manager.cik, cusip="037833100")
    assert full == ["closed"]  # la enmienda vigente ya no lista AAPL
    assert narrow == full
