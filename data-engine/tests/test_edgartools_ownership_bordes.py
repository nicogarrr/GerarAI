"""Bordes herméticos del adaptador Form 4, sin SEC ni red."""

from datetime import date, datetime

import pandas as pd
import pytest

from app.services.connectors import edgartools_ownership as svc


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, None),
        (float("nan"), None),
        ("nan", None),
        ("error", None),
        (object(), None),
        ("3.5", 3.5),
        (0, 0.0),
    ],
)
def test_conversion_numerica(value, expected):
    assert svc._to_float(value) == expected


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, None),
        (date(2026, 1, 2), "2026-01-02"),
        (datetime(2026, 1, 2, 12), "2026-01-02"),
        (" 01/02/2026 ", "2026-01-02"),
        ("2026-01-02T12:30:00+01:00", "2026-01-02"),
        ("no-date", None),
    ],
)
def test_fecha(value, expected):
    assert svc._iso_date(value) == expected


def test_dataframe_roto_no_inventa_filas():
    class Broken:
        def to_dict(self, *, orient):
            raise ValueError("malformed")

    out = svc.transactions_from_edgartools_dataframe(Broken(), ticker="ABC")
    assert out["transactions"] == [] and out["ticker"] == "ABC"
    assert out["reporters"] == []


def test_derivado_sin_codigo_y_valor_derivado():
    df = pd.DataFrame(
        [
            {
                "Transaction Type": "Derivative Purchase",
                "Shares": 3,
                "Price": 4,
                "Date": None,
                "Form": "Form 4",
                "Insider": "A",
            },
            {
                "Transaction Type": "Purchase",
                "Code": " p ",
                "Shares": 0,
                "Price": 4,
                "Position": "Chief Financial Officer",
                "Value": None,
            },
            {"Transaction Type": "Sale", "Shares": 2, "Price": 5, "Value": 99},
        ]
    )
    df = df.astype(object).where(pd.notna(df), None)
    out = svc.transactions_from_edgartools_dataframe(
        df, ticker="ABC", issuer_name="Issuer", issuer_cik="42", reporters=[{"name": "A"}, {"name": "B"}]
    )
    first, second, third = out["transactions"]
    assert first["is_derivative"] is True and first["acquired_disposed"] is None
    assert first["value"] == 12 and first["type"] is None
    assert first["multi_reporter"] is True and first["reporters_count"] == 2
    assert first["attribution"] == "joint_filing"
    assert second["type"] == "P" and second["value"] == 0
    assert second["acquired_disposed"] == "A" and second["is_officer"] is True
    assert third["acquired_disposed"] == "D" and third["value"] == 99


def test_fuentes_dataframe_fallback_y_fuente_incompatible():
    df = pd.DataFrame(
        [{"Transaction Type": "Purchase", "Shares": 2, "Price": 4, "Ticker": "ABC", "Issuer": "Issuer"}]
    )

    class Ownership:
        def to_dataframe(self, detailed):
            assert detailed is True
            return df

    out = svc.ownership_transactions(Ownership())
    assert out["transactions"][0]["value"] == 8
    assert out["transactions"][0]["ticker"] == "ABC"
    assert svc.ownership_transactions(df) == out
    with pytest.raises(TypeError, match="unsupported Form 4 source: object"):
        svc.ownership_transactions(object())


def test_enriquecer_fechas_y_ticker_sin_pisar_fecha_propia():
    rows = [{"date": None}, {"date": "2026-01-01", "ticker": "OWN"}]
    filing = {
        "ticker": " abc ",
        "accession_number": "acc",
        "filing_date": "2026-02-01",
        "document_url": "https://example.test/filing",
        "form": "4",
    }
    assert svc.enrich_like_insider_service(rows, filing) is rows
    assert rows == [
        {
            "ticker": "ABC",
            "date": "2026-02-01",
            "accession_number": "acc",
            "tx_line": 0,
            "filing_date": "2026-02-01",
            "source_url": "https://example.test/filing",
            "form": "4",
        },
        {
            "ticker": "OWN",
            "date": "2026-01-01",
            "accession_number": "acc",
            "tx_line": 1,
            "filing_date": "2026-02-01",
            "source_url": "https://example.test/filing",
            "form": "4",
        },
    ]
