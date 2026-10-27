"""PR-2: persistencia durable e idempotente de Form 4/4-A."""

from uuid import uuid4

from sqlalchemy import select

from app.core.database import SessionLocal, init_db
from app.models.entities import InsiderFiling, InsiderTransaction, Tenant
from app.services import insider_persistence
from app.services.connectors import form4 as form4_connector
from tests.test_insider_signals import CEO_BUY_XML

FILING = {
    "form": "4",
    "accession_number": "0001234567-24-000001",
    "filing_date": "2024-03-16",
    "report_date": "2024-03-15",
    "document_url": "https://www.sec.gov/Archives/edgar/data/1234567/000123456724000001/f4.xml",
    "index_url": "https://www.sec.gov/Archives/edgar/data/1234567/000123456724000001/",
}

AMENDMENT_FILING = {
    **FILING,
    "form": "4/A",
    "accession_number": "0001234567-24-000010",
    "filing_date": "2024-03-20",
    "document_url": "https://www.sec.gov/Archives/edgar/data/1234567/000123456724000010/f4a.xml",
}


def _db():
    init_db()
    return SessionLocal()


def _cleanup(db):
    db.query(InsiderTransaction).delete()
    db.query(InsiderFiling).delete()
    db.commit()


def test_persist_filing_is_idempotent_and_keeps_provenance():
    db = _db()
    try:
        _cleanup(db)
        parsed = form4_connector.parse_form4_xml(CEO_BUY_XML)

        first = insider_persistence.persist_filing(db, FILING, parsed, xml_text=CEO_BUY_XML)
        assert first["filing_created"] is True
        assert first["transactions_created"] == 1

        second = insider_persistence.persist_filing(db, FILING, parsed, xml_text=CEO_BUY_XML)
        assert second["filing_created"] is False
        assert second["transactions_created"] == 0

        filings = db.scalars(select(InsiderFiling)).all()
        assert len(filings) == 1
        record = filings[0]
        assert record.accession_number == FILING["accession_number"]
        assert record.form == "4"
        assert record.is_amendment is False
        assert record.source_url == FILING["document_url"]
        assert record.parser_version == insider_persistence.PARSER_VERSION
        assert record.raw_sha256 is not None

        rows = db.scalars(select(InsiderTransaction)).all()
        assert len(rows) == 1
        tx = rows[0]
        assert tx.code == "P"
        assert tx.acquired_disposed == "A"
        assert tx.insider == "DOE JANE"
        assert tx.value == 5000 * 250
        assert tx.source_url == FILING["document_url"]
        assert len(tx.fingerprint) == 64
    finally:
        _cleanup(db)
        db.close()


def test_amendment_creates_immutable_separate_filing():
    """Un 4/A nunca sobrescribe el filing original: dos filas inmutables."""
    db = _db()
    try:
        _cleanup(db)
        parsed = form4_connector.parse_form4_xml(CEO_BUY_XML)
        insider_persistence.persist_filing(db, FILING, parsed, xml_text=CEO_BUY_XML)
        insider_persistence.persist_filing(db, AMENDMENT_FILING, parsed, xml_text=CEO_BUY_XML)

        filings = {
            f.accession_number: f
            for f in db.scalars(select(InsiderFiling)).all()
        }
        assert set(filings) == {FILING["accession_number"], AMENDMENT_FILING["accession_number"]}
        original = filings[FILING["accession_number"]]
        amendment = filings[AMENDMENT_FILING["accession_number"]]
        assert original.form == "4" and original.is_amendment is False
        assert amendment.form == "4/A" and amendment.is_amendment is True
        # El original no fue mutado por la enmienda.
        assert original.filing_date == FILING["filing_date"]

        rows = db.scalars(select(InsiderTransaction)).all()
        # Una fila por filing: los fingerprints llevan el accession, no colisionan.
        assert len(rows) == 2
        assert {r.accession_number for r in rows} == set(filings)
    finally:
        _cleanup(db)
        db.close()


def test_fingerprint_is_stable_and_field_sensitive():
    parsed = form4_connector.parse_form4_xml(CEO_BUY_XML)
    tx = parsed["transactions"][0]
    fp1 = insider_persistence.transaction_fingerprint("ACC-1", 0, tx)
    fp2 = insider_persistence.transaction_fingerprint("ACC-1", 0, tx)
    assert fp1 == fp2
    changed = {**tx, "shares": 6000.0}
    assert insider_persistence.transaction_fingerprint("ACC-1", 0, changed) != fp1
    assert insider_persistence.transaction_fingerprint("ACC-2", 0, tx) != fp1


def test_get_signals_persists_best_effort(monkeypatch):
    """El pipeline persiste cuando recibe db y sigue funcionando si falla."""
    from app.services import insider_service

    monkeypatch.setattr(insider_service, "_cik_for_ticker", lambda t, client=None: "0001234567")
    monkeypatch.setattr(
        form4_connector, "recent_form4_filings", lambda cik, limit=20, client=None: [FILING]
    )

    db = _db()
    try:
        _cleanup(db)
        result = insider_service.get_signals_for_ticker(
            "ACME", fetcher=lambda f: CEO_BUY_XML, db=db
        )
        assert result["status"] == "ok"
        assert db.scalars(select(InsiderFiling)).all()
        assert db.scalars(select(InsiderTransaction)).all()

        # Una persistencia rota no rompe la lectura.
        _cleanup(db)
        def boom(*args, **kwargs):
            raise RuntimeError("db down")

        monkeypatch.setattr(insider_persistence, "persist_filing", boom)
        result = insider_service.get_signals_for_ticker(
            "ACME", fetcher=lambda f: CEO_BUY_XML, db=db
        )
        # A persistence failure is not a parse failure: the live read worked
        # and the signals stay available, with an explicit warning.
        assert result["status"] == "partial"
        assert result["filings_parsed"] == 1
        assert result["filings_failed"] == 0
        assert result["persist_error_count"] == 1
        assert result["buy_count"] == 1
        assert any("no se pudieron guardar" in warning for warning in result["warnings"])
        # The session must be usable after the error (no PendingRollbackError).
        assert db.scalars(select(InsiderFiling)).all() == []
    finally:
        _cleanup(db)
        db.close()


def test_integrity_error_rolls_back_and_next_filing_is_persisted(monkeypatch):
    """Un IntegrityError en una fila no invalida la sesion ni las siguientes.

    Antes el fallo de escritura se tragaba sin rollback: la sesion quedaba en
    PendingRollback y todo lo posterior (incluido el recuento) fallaba.
    """
    from app.services import insider_service

    monkeypatch.setattr(insider_service, "_cik_for_ticker", lambda t, client=None: "0001234567")
    monkeypatch.setattr(
        form4_connector,
        "recent_form4_filings",
        lambda cik, limit=20, client=None: [FILING, AMENDMENT_FILING],
    )

    db = _db()
    tenant = None
    try:
        _cleanup(db)
        tenant = Tenant(external_id=f"insider-{uuid4().hex}", name="Insider race")
        db.add(tenant)
        db.commit()
        db.info["tenant_id"] = tenant.id

        original_persist = insider_persistence.persist_filing

        def persist_then_collide(session, filing, parsed, **kwargs):
            stats = original_persist(session, filing, parsed, **kwargs)
            if filing["accession_number"] == FILING["accession_number"]:
                # Simula otra peticion que inserto el mismo accession entre el
                # SELECT y el flush de persist_filing: choque real de unicidad.
                session.add(
                    InsiderFiling(
                        tenant_id=kwargs.get("tenant_id"),
                        accession_number=FILING["accession_number"],
                        form="4",
                        issuer_cik="0001234567",
                        parser_version=insider_persistence.PARSER_VERSION,
                    )
                )
                session.flush()
            return stats

        monkeypatch.setattr(insider_persistence, "persist_filing", persist_then_collide)
        result = insider_service.get_signals_for_ticker(
            "ACME",
            fetcher=lambda f: CEO_BUY_XML,
            db=db,
            tenant_id=tenant.id,
        )

        assert result["status"] == "partial"
        assert result["filings_scanned"] == 2
        assert result["filings_parsed"] == 2
        assert result["filings_failed"] == 0
        assert result["persist_error_count"] == 1
        assert result["signals"]
        # La sesion sigue usable: las dos filas (la segunda tras el rollback).
        accessions = {
            row.accession_number for row in db.scalars(select(InsiderFiling)).all()
        }
        assert accessions == {
            FILING["accession_number"],
            AMENDMENT_FILING["accession_number"],
        }
        assert len(db.scalars(select(InsiderTransaction)).all()) == 2
    finally:
        _cleanup(db)
        if tenant is not None:
            db.query(Tenant).filter(Tenant.id == tenant.id).delete()
            db.commit()
        db.close()


def test_live_failure_falls_back_to_persisted_filings(monkeypatch):
    """Si EDGAR no responde (IP baneada) pero el filing esta persistido, las
    senales salen de la copia persistida y el resultado lo declara."""
    from app.services import insider_service

    monkeypatch.setattr(insider_service, "_cik_for_ticker", lambda t, client=None: "0001234567")
    monkeypatch.setattr(
        form4_connector, "recent_form4_filings", lambda cik, limit=20, client=None: [FILING]
    )

    def _edgar_down(filing):
        raise RuntimeError("403 Forbidden")

    db = _db()
    try:
        _cleanup(db)
        # Primera lectura live: persiste el filing.
        live = insider_service.get_signals_for_ticker(
            "ACME", fetcher=lambda f: CEO_BUY_XML, db=db  # pyright: ignore[reportArgumentType]
        )
        assert live["status"] == "ok"
        assert "filings_from_persisted" not in live

        # EDGAR cae: se usa la copia persistida.
        result = insider_service.get_signals_for_ticker("ACME", fetcher=_edgar_down, db=db)
        assert result["status"] == "ok"
        assert result["filings_parsed"] == 1
        assert result["filings_failed"] == 0
        assert result["filings_from_persisted"] == 1
        assert result["latest_persisted_filing_date"] == FILING["filing_date"]
        assert "desde filings persistidos" in result["source_note"]
        assert FILING["filing_date"] in result["provenance"]["note"]
        assert result["buy_count"] == live["buy_count"]
        assert len(result["signals"]) == len(live["signals"])
    finally:
        _cleanup(db)
        db.close()


def test_live_failure_without_persisted_copy_stays_degraded(monkeypatch):
    """Sin lectura live ni copia persistida sigue siendo fallo de lectura."""
    from app.services import insider_service

    monkeypatch.setattr(insider_service, "_cik_for_ticker", lambda t, client=None: "0001234567")
    monkeypatch.setattr(
        form4_connector, "recent_form4_filings", lambda cik, limit=20, client=None: [FILING]
    )

    def _edgar_down(filing):
        raise RuntimeError("403 Forbidden")

    db = _db()
    try:
        _cleanup(db)
        result = insider_service.get_signals_for_ticker("ACME", fetcher=_edgar_down, db=db)
        assert result["status"] == "degraded"
        assert result["filings_parsed"] == 0
        assert result["filings_failed"] == 1
        assert "filings_from_persisted" not in result
        assert result["signals"] == []
    finally:
        _cleanup(db)
        db.close()


def test_partial_fallback_mixes_live_and_persisted(monkeypatch):
    """Un filing live y otro persistido: status ok y el conteo del fallback."""
    from app.services import insider_service

    monkeypatch.setattr(insider_service, "_cik_for_ticker", lambda t, client=None: "0001234567")
    monkeypatch.setattr(
        form4_connector,
        "recent_form4_filings",
        lambda cik, limit=20, client=None: [FILING, AMENDMENT_FILING],
    )

    db = _db()
    try:
        _cleanup(db)
        parsed = form4_connector.parse_form4_xml(CEO_BUY_XML)
        insider_persistence.persist_filing(db, FILING, parsed, xml_text=CEO_BUY_XML)

        def _only_amendment_live(filing):
            if filing["accession_number"] == AMENDMENT_FILING["accession_number"]:
                return CEO_BUY_XML
            raise RuntimeError("403 Forbidden")

        result = insider_service.get_signals_for_ticker(
            "ACME", fetcher=_only_amendment_live, db=db  # pyright: ignore[reportArgumentType]
        )
        assert result["status"] == "ok"
        assert result["filings_scanned"] == 2
        assert result["filings_parsed"] == 2
        assert result["filings_from_persisted"] == 1
    finally:
        _cleanup(db)
        db.close()


def test_public_reason_never_leaks_exception_text():
    import httpx

    from app.services.insider_service import public_reason

    request = httpx.Request("GET", "https://www.sec.gov/files/company_tickers.json")
    forbidden = httpx.HTTPStatusError("403 Forbidden", request=request, response=httpx.Response(403, request=request))
    limited = httpx.HTTPStatusError("429", request=request, response=httpx.Response(429, request=request))
    assert public_reason(forbidden) == "sec_bloquea_datacenter"
    assert public_reason(limited) == "sec_limita_peticiones"
    assert public_reason(RuntimeError("secret sec.gov detail")) == "fuente_no_disponible"
