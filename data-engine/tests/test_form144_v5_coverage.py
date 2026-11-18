from __future__ import annotations

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine

from app.services.connectors import form144
from tests.test_0137_form144_migration import _create_table, _load
from tests.test_form144_connector import SLGN_XML as REAL_144_XML


def _create_table_nullable_flipped(conn):
    metadata = sa.MetaData()
    cols = []
    from app.models.entities import Form144Notice

    for column in Form144Notice.__table__.columns:
        nullable = (not column.nullable) if column.name == "accession_number" else column.nullable
        cols.append(sa.Column(column.name, column.type, nullable=nullable, primary_key=(column.name == "id")))
    sa.Table("form144_notices", metadata, *cols)
    metadata.create_all(conn)


def test_adoption_rejects_nullable_mismatch(monkeypatch):
    module = _load()
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        monkeypatch.setattr(module, "op", Operations(MigrationContext.configure(conn)))
        _create_table_nullable_flipped(conn)
        with pytest.raises(RuntimeError, match="schema mismatch"):
            module.upgrade()


def test_adoption_rejects_string_length_mismatch(monkeypatch):
    module = _load()
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        monkeypatch.setattr(module, "op", Operations(MigrationContext.configure(conn)))
        conn.exec_driver_sql(
            "CREATE TABLE form144_notices (id INTEGER PRIMARY KEY, accession_number VARCHAR(41))"
        )
        with pytest.raises(RuntimeError, match="schema mismatch"):
            module.upgrade()


def test_adoption_rejects_missing_pk(monkeypatch):
    module = _load()
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        monkeypatch.setattr(module, "op", Operations(MigrationContext.configure(conn)))
        _create_table(conn, with_pk=False)
        with pytest.raises(RuntimeError, match="sin PK"):
            module.upgrade()


def test_adoption_with_full_constraints_marks_adopted(monkeypatch):
    module = _load()
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE tenants (id INTEGER PRIMARY KEY)")
        _create_table(conn)
        ops = Operations(MigrationContext.configure(conn))
        with ops.batch_alter_table("form144_notices") as batch:
            batch.create_unique_constraint("uq_existing", ["tenant_id", "accession_number"])
            batch.create_foreign_key("fk_ok", "tenants", ["tenant_id"], ["id"])
        monkeypatch.setattr(module, "op", ops)
        module.upgrade()
        mode = conn.scalar(
            sa.text(
                "SELECT mode FROM migration_table_provenance "
                "WHERE revision='0137_form144_notices' AND table_name='form144_notices'"
            )
        )
        assert mode == "adopted"
        module.downgrade()
        assert sa.inspect(conn).has_table("form144_notices")  # adoptada: no se borra


def test_downgrade_without_provenance_row_keeps_table(monkeypatch):
    module = _load()
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        monkeypatch.setattr(module, "op", Operations(MigrationContext.configure(conn)))
        module.upgrade()  # created + marca created
        conn.execute(
            sa.text(
                "DELETE FROM migration_table_provenance "
                "WHERE revision='0137_form144_notices' AND table_name='form144_notices'"
            )
        )
        module.downgrade()  # sin marca: lo seguro es conservar
        assert sa.inspect(conn).has_table("form144_notices")




def test_sleep_and_get_text_delegate(monkeypatch):
    form144._sleep(0)
    seen = {}
    monkeypatch.setattr(
        form144.edgar_common,
        "get_text",
        lambda url, client, headers=None, throttle=None, sleep=None: seen.update(
            url=url, headers=headers, throttle=throttle
        )
        or "TXT",
    )
    assert form144._get_text("https://www.sec.gov/x", None) == "TXT"
    assert seen["url"] == "https://www.sec.gov/x"
    assert seen["throttle"] is not None


def test_is_form144_xml_accepts_defusedxml_rejected_xml():
    hostile = '<!DOCTYPE edgarSubmission [<!ENTITY a "x">]><edgarSubmission><formData/></edgarSubmission>'
    assert form144._is_form144_xml(hostile) is True  # la decision es del parser (unparsed)
    assert form144._is_form144_xml("<div>AccessDenied</div>") is False


def test_fetch_filing_xml_retries_rendered_html_with_raw(monkeypatch):
    responses = iter(["<html>rendered</html>", REAL_144_XML])
    monkeypatch.setattr(form144, "_get_text", lambda url, client=None: next(responses))
    rendered = (
        "https://www.sec.gov/Archives/edgar/data/849869/000084986926000005/"
        "xsl144X01/primary_doc.xml"
    )
    assert form144.fetch_filing_xml(rendered) == REAL_144_XML


def test_fetch_filing_xml_rejects_non_sec_host():
    with pytest.raises(ValueError, match="sec.gov"):
        form144.fetch_filing_xml("https://evil.example.com/doc.xml")


def test_fetch_filing_xml_raises_when_no_xml_variant(monkeypatch):
    monkeypatch.setattr(form144, "_get_text", lambda url, client=None: "<html>nope</html>")
    with pytest.raises(ValueError, match="no es un Form 144"):
        form144.fetch_filing_xml(
            "https://www.sec.gov/Archives/edgar/data/849869/000084986926000005/primary_doc.xml"
        )


def test_parse_helpers_never_invent():
    assert form144._children(None, "x") == []
    assert form144._to_int("1,234") == 1234
    assert form144._to_int(None) is None
    assert form144._to_int("abc") is None
    assert form144._to_float("3.5") == 3.5
    assert form144._to_float(None) is None
    assert form144._to_float("abc") is None
    assert form144._yes_no("Y") is True
    assert form144._yes_no("N") is False
    assert form144._yes_no("X") is None
    totals = form144.proposed_sale_totals(
        {
            "securities": [
                {
                    "shares": 10.0,
                    "market_value": 100.0,
                    "shares_outstanding": 1000.0,
                    "approx_sale_date": "11/16/2026",
                    "exchange": "NASDAQ",
                    "broker_name": "BROKER",
                    "securities_class_title": "Common",
                }
            ]
        }
    )
    assert totals["shares_to_sell"] == 10  # entero declarado: int
    assert form144.proposed_sale_totals({"securities": []})["shares_to_sell"] is None


