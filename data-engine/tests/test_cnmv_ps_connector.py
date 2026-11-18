"""Conector CNMV PS: parser de la vista real de notificaciones (18-nov-2026)."""

from datetime import date
from pathlib import Path

import pytest

from app.services.connectors import cnmv_ps

FIXTURE = (
    Path(__file__).parent / "fixtures" / "cnmv" / "ps_notificaciones_acerinox_2026-11.html"
).read_text(encoding="utf-8")


def test_parse_real_issuer_page():
    report = cnmv_ps.parse_issuer_page(FIXTURE, "A-28250777", "ACERINOX, S.A.")
    assert report.total_voting_rights == 249335371
    assert report.loyalty_voting_rights == 0
    assert len(report.holders) == 6

    by_name = {h.holder_name: h for h in report.holders}
    alba = by_name["CORPORACION FINANCIERA ALBA, S.A."]
    assert alba.pct_shares_total == 18.958
    assert alba.pct_direct == 18.958
    assert alba.pct_indirect == 0.0
    assert alba.pct_instruments == 0.0
    assert alba.pct_total == 18.958
    assert alba.registry_date == date(2017, 3, 7)
    assert alba.document_url.startswith("https://www.cnmv.es/webservices/verdocumento/ver?e=")

    goldman = by_name["THE GOLDMAN SACHS GROUP, INC."]
    assert goldman.pct_direct == 0.0
    assert goldman.pct_indirect == 2.202
    assert goldman.pct_instruments == 2.074
    assert goldman.pct_total == 4.276
    assert goldman.registry_date == date(2026, 11, 17)


def test_identity_mismatch_degrades_instead_of_attributing():
    with pytest.raises(cnmv_ps.CNMVPSParseError):
        cnmv_ps.parse_issuer_page(FIXTURE, "A-28250777", "OTRA EMPRESA, S.A.")


def test_missing_table_degrades_instead_of_inventing():
    broken = FIXTURE.replace("gridAccionistasSignificativos", "gridOtraCosa")
    with pytest.raises(cnmv_ps.CNMVPSParseError):
        cnmv_ps.parse_issuer_page(broken, "A-28250777", "ACERINOX, S.A.")


def test_spanish_number_formats():
    assert cnmv_ps._parse_pct("3,000") == 3.0
    assert cnmv_ps._parse_pct("18,958") == 18.958
    assert cnmv_ps._parse_pct("") is None
    assert cnmv_ps._parse_pct("texto") is None
    assert cnmv_ps._parse_int("249.335.371") == 249335371


def test_result_issuers_list_and_empty():
    listed = (
        '<html><body><select name="ctl00$ContentPrincipal$wbusqueda$lstSeleccion">'
        '<option value="A-28250777">ACERINOX, S.A.</option>'
        '<option value="A02850956">EDREAMS ODIGEO, S.A.</option>'
        "</select></body></html>"
    )
    assert cnmv_ps._result_issuers(listed) == [
        ("A-28250777", "ACERINOX, S.A."),
        ("A02850956", "EDREAMS ODIGEO, S.A."),
    ]
    empty = "<html><body>Han sido encontrados: 0 resultados</body></html>"
    assert cnmv_ps._result_issuers(empty) == []
    with pytest.raises(cnmv_ps.CNMVPSParseError):
        cnmv_ps._result_issuers("<html><body>estructura nueva</body></html>")
