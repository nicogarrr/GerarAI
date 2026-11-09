"""13F adapters preserve filed fields across supported source shapes."""

from types import SimpleNamespace

import pandas as pd
import pytest

from app.services.connectors import edgartools_thirteenf as adapter


def _frame():
    return pd.DataFrame(
        [
            {
                "Issuer": " Filed issuer ",
                "Class": "BOND",
                "Cusip": "000000001",
                "Value": 0,
                "SharesPrnAmount": 75,
                "Type": "Principal",
                "PutCall": float("nan"),
                "InvestmentDiscretion": None,
                "SoleVoting": " ",
                "SharedVoting": 0,
                "NonVoting": 75,
                "Ticker": "DO_NOT_INFER",
            }
        ]
    )


@pytest.mark.parametrize("shape", ["parse_infotable_xml", "infotable", "holdings", "dataframe"])
def test_supported_shapes_keep_principal_and_null_fields_without_ticker(shape):
    frame = _frame()
    if shape == "dataframe":
        source = frame
    elif shape == "parse_infotable_xml":
        source = SimpleNamespace(parse_infotable_xml=lambda: frame)
    else:
        source = SimpleNamespace(**{shape: frame})
    rows = adapter.infotable_holdings(source)
    assert rows == [
        {
            "name_of_issuer": "Filed issuer",
            "title_of_class": "BOND",
            "cusip": "000000001",
            "value_usd_thousands": "0",
            "ssh_prnamt": "75",
            "ssh_prnamt_type": "PRN",
            "put_call": None,
            "investment_discretion": None,
            "voting_sole": None,
            "voting_shared": "0",
            "voting_none": "75",
        }
    ]
    assert tuple(rows[0]) == adapter.THIRTEENF_ROW_KEYS


def test_typeerror_in_older_method_falls_back_to_holdings():
    calls = []

    def incompatible():
        calls.append("old method")
        raise TypeError("old parser signature requires an argument")

    source = SimpleNamespace(parse_infotable_xml=incompatible, infotable=None, holdings=_frame())
    assert adapter.infotable_holdings(source)[0]["ssh_prnamt_type"] == "PRN"
    assert calls == ["old method"]


def test_bytes_decode_to_xml_with_replacement_and_preserve_parser_result(monkeypatch):
    seen = []
    sentinel = [{"filed": "value"}]

    def parse(xml):
        seen.append(xml)
        return sentinel

    monkeypatch.setattr(adapter.form13f_connector, "parse_information_table", parse)
    assert adapter.infotable_holdings(b"<xml>\xff</xml>") is sentinel
    assert seen == ["<xml>\ufffd</xml>"]


def test_dataframe_conversion_failure_is_empty_and_unsupported_source_is_explicit():
    class BrokenFrame:
        def to_dict(self, *, orient):
            assert orient == "records"
            raise ValueError("corrupt dataframe")

    assert adapter.holdings_from_edgartools_dataframe(BrokenFrame()) == []
    with pytest.raises(TypeError, match="unsupported 13F source: object"):
        adapter.infotable_holdings(object())


def test_unrecognized_position_type_is_not_relabelled():
    frame = _frame()
    frame.loc[0, "Type"] = " OtherFiledType "
    assert adapter.infotable_holdings(frame)[0]["ssh_prnamt_type"] == "OtherFiledType"
