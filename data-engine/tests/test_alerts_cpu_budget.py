"""Alerts quota absorbs short bursts without changing threads or RAM."""
from pathlib import Path

import pytest
import yaml


class ComposeLoader(yaml.SafeLoader):
    pass


ComposeLoader.add_multi_constructor('!', lambda loader, suffix, node:
    loader.construct_sequence(node) if isinstance(node, yaml.SequenceNode)
    else loader.construct_mapping(node) if isinstance(node, yaml.MappingNode)
    else loader.construct_scalar(node))


def test_alerts_burst_cpu_and_other_resources_preserved():
    root = Path(__file__).resolve().parents[2]
    worker = yaml.load((root / 'docker-compose.prod.yml').read_text(), Loader=ComposeLoader)['services']['worker-alerts']
    assert worker['deploy']['resources']['limits'] == {'cpus': '0.75', 'memory': '320M'}
    command = worker['command']
    assert command[command.index('--threads') + 1] == '2'
    assert command[command.index('-Q') + 1:] == ['alerts', 'computed']


@pytest.mark.parametrize('text,expected', [
    ('value: !override [a]', {'value': ['a']}),
    ('value: !override {a: b}', {'value': {'a': 'b'}}),
    ('value: !reset disabled', {'value': 'disabled'}),
])
def test_compose_tag_support(text, expected):
    assert yaml.load(text, Loader=ComposeLoader) == expected
