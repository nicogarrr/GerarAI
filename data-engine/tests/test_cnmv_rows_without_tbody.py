"""Rows directly below a CNMV table are not proof of zero positions."""
from datetime import UTC, datetime

import pytest

from app.services.connectors.cnmv_shorts import parse_positions
from tests.test_cnmv_shorts_fetch_edges import ISSUER, _page


@pytest.mark.parametrize('tbody', [False, True])
def test_current_position_read_with_or_without_tbody(tbody):
    body = _page('<tr><td>Fund</td><td>1,25</td><td>01/01/2026</td><td></td></tr>')
    if not tbody:
        body = body.replace('<tbody>', '').replace('</tbody>', '')
    body = body.replace('<caption>', '<thead><tr><th>Holder</th><th>Percent</th><th>Date</th><th>Other</th></tr></thead><caption>')
    result = parse_positions(body, ISSUER, now=datetime(2026, 1, 2, tzinfo=UTC))
    assert result == [{'holder': 'Fund', 'percent': 1.25, 'position_date': '2026-01-01'}]
