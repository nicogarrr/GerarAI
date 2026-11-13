"""N-PORT cannot observe a portfolio after its filing date or in the future."""
import io
import zipfile

from app.services.connectors.form_nport_dataset import parse_dataset


def _parse(filed, reported):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        archive.writestr('SUBMISSION.tsv', f'ACCESSION_NUMBER\tFILING_DATE\tSUB_TYPE\tREPORT_DATE\nA\t{filed}\tNPORT-P\t{reported}\n')
        for name in ['REGISTRANT.tsv', 'FUND_REPORTED_INFO.tsv']:
            archive.writestr(name, 'ACCESSION_NUMBER\n')
    buffer.seek(0)
    return parse_dataset(buffer, set())


def test_report_date_after_filing_is_not_an_observed_portfolio():
    assert _parse('20-AUG-2026', '30-SEP-2026') == {}


def test_future_filing_is_not_an_observed_portfolio():
    assert _parse('20-AUG-2099', '30-JUN-2099') == {}


def test_observed_report_remains_available():
    assert _parse('20-AUG-2026', '30-JUN-2026')['A'].report_date.isoformat() == '2026-06-30'
