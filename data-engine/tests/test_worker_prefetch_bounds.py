"""Explicit local reservations for long-running workers, not extra threads."""
from pathlib import Path

import pytest
import yaml


class ComposeLoader(yaml.SafeLoader):
    pass


def tagged(loader, suffix, node):
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node)
    return loader.construct_scalar(node)


ComposeLoader.add_multi_constructor('!', tagged)


@pytest.mark.parametrize('name,ready,delayed', [
    ('worker', '${WORKER_THREADS:-4}', '1'),
    ('worker-prices', '${WORKER_THREADS:-2}', '1'),
    ('worker-yahoo', '${YAHOO_THREADS:-2}', '1'),
    ('worker-thesis', '2', '1'),
])
def test_long_workers_bound_reservations_without_reducing_threads(name, ready, delayed):
    root = Path(__file__).resolve().parents[2]
    services = yaml.load((root / 'docker-compose.prod.yml').read_text(), Loader=ComposeLoader)['services']
    service = services[name]
    assert service['environment'].get('dramatiq_queue_prefetch') == ready
    assert service['environment'].get('dramatiq_delay_queue_prefetch') == delayed
    command = service['command']
    assert command[command.index('--threads') + 1] == ready


@pytest.mark.parametrize('text,expected', [
    ('value: !override [a, b]', {'value': ['a', 'b']}),
    ('value: !override {a: b}', {'value': {'a': 'b'}}),
    ('value: !reset disabled', {'value': 'disabled'}),
])
def test_compose_tags_are_read_as_structures(text, expected):
    assert yaml.load(text, Loader=ComposeLoader) == expected
