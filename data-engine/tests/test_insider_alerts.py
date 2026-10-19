"""PR-4: outbox durable de alertas insider (dedupe por fingerprint)."""

from sqlalchemy import select

from app.core.database import SessionLocal, init_db
from app.models.entities import (
    Company,
    InsiderFiling,
    InsiderTransaction,
    ResearchAlert,
)
from app.services import insider_alerts, insider_persistence
from app.services.connectors import form4 as form4_connector
from tests.test_insider_signals import CEO_BUY_XML

FILING = {
    "form": "4",
    "accession_number": "0001234567-24-000201",
    "filing_date": "2024-03-16",
    "report_date": "2024-03-15",
    "document_url": "https://www.sec.gov/Archives/edgar/data/1234567/f4.xml",
    "index_url": "https://www.sec.gov/Archives/edgar/data/1234567/",
}


def _db():
    init_db()
    return SessionLocal()


def _cleanup(db):
    db.query(ResearchAlert).delete()
    db.query(InsiderTransaction).delete()
    db.query(InsiderFiling).delete()
    db.query(Company).filter(Company.ticker.in_(["ACME"])).delete()
    db.commit()


def _seed_big_buy(db, *, accession=FILING["accession_number"], form="4"):
    """Persiste un filing cuyo XML tiene una compra P grande de un CEO."""
    parsed = form4_connector.parse_form4_xml(CEO_BUY_XML)
    filing = {**FILING, "form": form, "accession_number": accession}
    insider_persistence.persist_filing(db, filing, parsed, xml_text=CEO_BUY_XML)
    return parsed


def test_big_buy_and_c_suite_alerts_created_and_deduped():
    db = _db()
    try:
        _cleanup(db)
        _seed_big_buy(db)

        first = insider_alerts.evaluate(db)
        created_types = {
            row.alert_type
            for row in db.scalars(select(ResearchAlert)).all()
        }
        assert "insider_big_buy" in created_types
        assert "insider_c_suite_buy" in created_types
        assert first["alerts_created"] == len(created_types)
        assert first["alerts_created"] >= 2

        second = insider_alerts.evaluate(db)
        assert second["alerts_created"] == 0
        assert second["alerts_existing"] >= 2
        total = len(db.scalars(select(ResearchAlert)).all())
        assert total == len(created_types)

        big = db.scalar(
            select(ResearchAlert).where(ResearchAlert.alert_type == "insider_big_buy")
        )
        assert "puede ser en mercado abierto o privada" in big.message
        assert "XML" not in big.message
        assert big.metadata_["rule_version"] == insider_alerts.RULE_VERSION
        assert big.metadata_["tx_fingerprint"]
        assert big.channels == ["in_app"]
    finally:
        _cleanup(db)
        db.close()


def test_amendment_generates_its_own_alerts():
    """Una 4/A llega con fingerprints propios: nuevas alertas, sin duplicar."""
    db = _db()
    try:
        _cleanup(db)
        _seed_big_buy(db)
        insider_alerts.evaluate(db)
        before = len(db.scalars(select(ResearchAlert)).all())

        _seed_big_buy(db, accession="0001234567-24-000202", form="4/A")
        stats = insider_alerts.evaluate(db)
        after = len(db.scalars(select(ResearchAlert)).all())
        assert stats["alerts_created"] == after - before
        assert after > before
    finally:
        _cleanup(db)
        db.close()


def test_non_p_codes_and_derivatives_never_alert():
    db = _db()
    try:
        _cleanup(db)
        parsed = form4_connector.parse_form4_xml(CEO_BUY_XML)
        insider_persistence.persist_filing(db, FILING, parsed, xml_text=CEO_BUY_XML)
        # Convierte todas las filas persistidas en grants derivados (codigo A).
        for tx in db.scalars(select(InsiderTransaction)).all():
            tx.code = "A"
            tx.is_derivative = True
            db.add(tx)
        db.commit()

        stats = insider_alerts.evaluate(db)
        assert stats["candidates"] == 0
        assert stats["alerts_created"] == 0
        assert len(db.scalars(select(ResearchAlert)).all()) == 0
    finally:
        _cleanup(db)
        db.close()


def test_cluster_buy_requires_three_distinct_insiders():
    db = _db()
    try:
        _cleanup(db)
        parsed = form4_connector.parse_form4_xml(CEO_BUY_XML)
        tx = parsed["transactions"][0]
        company = Company(
            ticker="ACME", name="ACME Test", exchange="NASDAQ",
            company_type="compounders", valuation_model="dcf",
        )
        db.add(company)
        db.flush()
        # Tres compras P de insiders distintos dentro de 30 dias.
        for idx, cik in enumerate(["111", "222", "333"]):
            accession = f"0001234567-24-0003{idx:02d}"
            clone = dict(tx)
            clone["insider_cik"] = cik
            clone["insider"] = f"Insider {cik}"
            clone["value"] = 50_000.0  # por debajo de big_buy: solo cluster
            clone["shares"] = 500.0
            parsed_clone = {"issuer_cik": "1234567", "ticker": "ACME",
                            "issuer_name": "ACME Test", "transactions": [clone]}
            insider_persistence.persist_filing(
                db,
                {**FILING, "accession_number": accession},
                parsed_clone,
                xml_text=None,
            )

        stats = insider_alerts.evaluate(db)
        clusters = db.scalars(
            select(ResearchAlert).where(ResearchAlert.alert_type == "insider_cluster_buy")
        ).all()
        assert len(clusters) == 1
        assert clusters[0].metadata_["insider_count"] == 3
        assert clusters[0].company_id == company.id
        # Sin big_buy: los valores estan por debajo del umbral.
        assert not db.scalars(
            select(ResearchAlert).where(ResearchAlert.alert_type == "insider_big_buy")
        ).all()
        # 3 c_suite (el XML es un CEO) + 1 cluster.
        assert stats["alerts_created"] == 4
        # Todos los importes conocidos: el total es el total.
        assert "$150,000 total" in clusters[0].message
        assert clusters[0].metadata_["window_value_missing"] == 0
        assert clusters[0].metadata_["total_value_is_minimum"] is False
        assert stats["skipped_missing_value"] == 0
        assert stats["partial_cluster_totals"] == 0
    finally:
        _cleanup(db)
        db.close()


def test_a_purchase_without_a_figure_never_alerts_as_zero():
    """Un Form 4 sin cifra no es una compra de $0.

    c_suite_buy no tiene gate de umbral: la alerta se emitia igual y el
    mensaje decia "compro $0" (severidad medium). Sin importe no hay nada que
    afirmar, asi que la transaccion no alerta y el hueco queda como cobertura.
    """
    db = _db()
    try:
        _cleanup(db)
        _seed_big_buy(db)
        for tx in db.scalars(select(InsiderTransaction)).all():
            tx.value = None
            db.add(tx)
        db.commit()

        stats = insider_alerts.evaluate(db)
        assert stats["candidates"] == 1
        assert stats["alerts_created"] == 0
        assert stats["skipped_missing_value"] == 1
        assert db.scalars(select(ResearchAlert)).all() == []
    finally:
        _cleanup(db)
        db.close()


def test_a_cluster_with_a_missing_figure_publishes_a_minimum_total():
    """Un NULL sumado como 0 infravalora el total del cluster en silencio.

    La regla se dispara por numero de insiders, no por dinero, asi que la
    compra sin cifra no invalida el cluster: su importe no suma y el total se
    declara como minimo conocido, con el hueco contado.
    """
    db = _db()
    try:
        _cleanup(db)
        parsed = form4_connector.parse_form4_xml(CEO_BUY_XML)
        tx = parsed["transactions"][0]
        company = Company(
            ticker="ACME", name="ACME Test", exchange="NASDAQ",
            company_type="compounders", valuation_model="dcf",
        )
        db.add(company)
        db.flush()
        for idx, cik in enumerate(["111", "222", "333"]):
            accession = f"0001234567-24-0004{idx:02d}"
            clone = dict(tx)
            clone["insider_cik"] = cik
            clone["insider"] = f"Insider {cik}"
            clone["shares"] = 500.0
            # El tercero llega del XML sin cifra de importe.
            clone["value"] = 50_000.0 if idx < 2 else None
            parsed_clone = {"issuer_cik": "1234567", "ticker": "ACME",
                            "issuer_name": "ACME Test", "transactions": [clone]}
            insider_persistence.persist_filing(
                db,
                {**FILING, "accession_number": accession},
                parsed_clone,
                xml_text=None,
            )

        stats = insider_alerts.evaluate(db)
        cluster = db.scalar(
            select(ResearchAlert).where(ResearchAlert.alert_type == "insider_cluster_buy")
        )
        assert cluster is not None
        # 2 c_suite (la compra sin cifra no alerta) + 1 cluster.
        assert stats["alerts_created"] == 3
        assert stats["skipped_missing_value"] == 1
        assert stats["partial_cluster_totals"] == 1
        # El total son los $100,000 conocidos, NO $100,000 de "$0" contados.
        assert "$100,000" in cluster.message
        assert "$150,000" not in cluster.message
        assert "como minimo" in cluster.message
        assert "1 de 3 compras sin cifra" in cluster.message
        assert cluster.metadata_["window_transactions"] == 3
        assert cluster.metadata_["window_value_missing"] == 1
        assert cluster.metadata_["total_value_is_minimum"] is True
    finally:
        _cleanup(db)
        db.close()



def _fake_tx(i, *, value, shares, price, day, accession="0001193125-26-397059"):
    from types import SimpleNamespace
    return SimpleNamespace(
        issuer_ticker="LEN, LEN.B", insider="BERKSHIRE HATHAWAY INC / BUFFETT WARREN E",
        insider_cik="0001067983", role="Director", officer_title=None, tx_date=day,
        shares=shares, price=price, value=value, code="P", acquired_disposed="A",
        is_derivative=False, source_url="https://www.sec.gov/x.xml", multi_reporter=False,
        accession_number=accession, form="4", data_quality="ok", fingerprint=f"fp{i}",
    )


def test_many_lines_of_one_form4_become_a_single_spanish_alert(monkeypatch):
    monkeypatch.setattr(insider_alerts, "_company_id_for", lambda db, ticker: None)
    txs = [
        _fake_tx(1, value=1_390_347, shares=18146, price=76.62, day="2026-09-21"),
        _fake_tx(2, value=2_477_526, shares=33122, price=74.8, day="2026-09-18"),
        _fake_tx(3, value=37_722_588, shares=483809, price=77.97, day="2026-09-21"),
    ]
    alerts, _ = insider_alerts._build_alerts(None, txs)
    big = [a for a in alerts if a["rule"] == "big_buy"]
    assert len(big) == 1
    msg = big[0]["message"]
    assert "3 operaciones" in msg and "$41.59M" in msg
    assert "entre el 18 sep 2026 y el 21 sep 2026" in msg
    assert "XML" not in msg and "US$" not in msg
    assert big[0]["metadata"]["transactions"] == 3
    # El listado resuelve el emisor por la huella del primer movimiento.
    assert big[0]["metadata"]["tx_fingerprint"] == "fp2"


def test_different_filings_or_insiders_stay_separate(monkeypatch):
    monkeypatch.setattr(insider_alerts, "_company_id_for", lambda db, ticker: None)
    txs = [
        _fake_tx(1, value=2_000_000, shares=1000, price=2000, day="2026-09-21", accession="A"),
        _fake_tx(2, value=3_000_000, shares=1000, price=3000, day="2026-09-22", accession="B"),
    ]
    alerts, _ = insider_alerts._build_alerts(None, txs)
    assert len([a for a in alerts if a["rule"] == "big_buy"]) == 2


def test_spanish_number_and_date_formats():
    assert insider_alerts._es_num(1390347) == "1,390,347"
    assert insider_alerts._es_num(76.62, 2) == "76.62"
    assert insider_alerts._es_money(1_390_347) == "$1.39M"
    assert insider_alerts._es_money(250_000) == "$250,000"
    assert insider_alerts._es_date("2026-09-21") == "21 sep 2026"
