"""Unverifiable 13F counts cannot become infinite totals or false exits."""
import io
import zipfile

import pytest

from app.services.connectors.form13f_dataset import parse_dataset

CUSIP = '037833100'


def _dataset(amount):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        archive.writestr('SUBMISSION.tsv', 'ACCESSION_NUMBER\tFILING_DATE\tSUBMISSIONTYPE\tCIK\tPERIODOFREPORT\nA\t13-AUG-2026\t13F-HR\t1\t30-JUN-2026\n')
        archive.writestr('COVERPAGE.tsv', 'ACCESSION_NUMBER\tFILINGMANAGER_NAME\nA\tManager\n')
        archive.writestr('INFOTABLE.tsv', f'ACCESSION_NUMBER\tCUSIP\tSSHPRNAMT\tSSHPRNAMTTYPE\tPUTCALL\nA\t{CUSIP}\t{amount}\tSH\t\n')
    buffer.seek(0)
    return buffer


@pytest.mark.parametrize('amount', ['NaN', 'sNaN', 'Infinity', '-Infinity'])
def test_nonfinite_count_rejects_dataset_instead_of_persisting_false_holdings(amount):
    with pytest.raises(ValueError, match='13F'):
        parse_dataset(_dataset(amount), {CUSIP})


@pytest.mark.parametrize('amount,expected', [('0', None), ('12', '12'), ('1,234', '1234')])
def test_finite_counts_keep_existing_semantics(amount, expected):
    from decimal import Decimal
    parsed = parse_dataset(_dataset(amount), {CUSIP})
    assert parsed.filings['A'].shares.get(CUSIP) == (Decimal(expected) if expected else None)
