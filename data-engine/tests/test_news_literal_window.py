"""Identical recurring headlines do not prove the same story across months."""
from datetime import timedelta

import pytest

from tests.test_news_story_cluster_index import NOW, _event, _indexed, _naive


@pytest.mark.parametrize('cluster', [_naive, _indexed])
def test_short_literal_headlines_respect_48_hour_window(cluster):
    latest = _event(0, 'Quarterly results')
    old = _event(1, 'Quarterly results')
    old.date = NOW - timedelta(days=90)
    assert len(cluster([latest, old])) == 2


@pytest.mark.parametrize('cluster', [_naive, _indexed])
def test_later_literal_group_still_absorbs_nearby_copy(cluster):
    events = [_event(i, 'Quarterly results') for i in range(3)]
    events[1].date = NOW - timedelta(days=90)
    events[2].date = NOW - timedelta(days=90, hours=1)
    groups = cluster(events)
    assert [count for _, count in groups] == [0, 1]
