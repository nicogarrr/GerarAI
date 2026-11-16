"""Contratos del servicio compartido por pendientes del listado."""

def test_thesis_render_diagnostics_with_and_without_optional_sources():
    from app.services.thesis_service import ThesisService

    service = ThesisService()
    assert service._md_cell(None) == ''
    assert service._md_cell('a|b\nc') == 'a\\|b c'
    for data in (None, {}, {'status': 'disabled'}):
        assert service._consensus_markdown(data) == ''
    for status in ('sin_consenso', 'no_comparable', 'error:fixture'):
        assert status in service._consensus_markdown({'status': status})
    for source in ('', 'https://example.com/fixture'):
        out = service._consensus_markdown({'status': 'revisar', 'reason': 'fixture',
            'consensus': {'mean': 10, 'high': 12, 'source_url': source},
            'steps': [{'name': 'a|b', 'ours': 1, 'theirs': 2, 'effect_per_share': 3}, {}],
            'data_rows': [None, {}, {'method': 'analyst', 'name': 'x', 'value': 1,
                                   'source_quote': 'q|q'},
                          {'method': 'analyst', 'input': 'y', 'value': 2}]})
        assert 'a\\|b' in out and 'Supuestos de analista' in out
        assert 'no bloquea' in out
    assert service._value_drivers_markdown({'status': 'no_tenant'}) == ''
    full = {'name': 'impulsor', 'source_url': 'https://example.com/fixture',
            'source_quote': 'cita|cita', 'as_of': '2026-11-16',
            'value_per_share_marginal': 0, 'model_link': 'fixture',
            'reason_if_not_valued': 'sin tratamiento'}
    out = service._value_drivers_markdown({'publishable': False,
        'blocking': [{'driver_key': 'x', 'why': 'pendiente'}], 'drivers': [full, {}]})
    assert 'Valor marginal' in out and 'cita\\|cita' in out
    assert 'No valorado' in out and 'Recogido en el modelo' in out
    for data in (None, {}, {'status': ''}, {'status': 'disabled'}):
        assert service._expert_inputs_markdown(data) == ''
    for data in ({'status': 'ok'}, {'status': 'error',
         'recopilador': {'status': 'stored', 'stored': 2, 'firms': ['fixture']},
         'analista': {'stored': 1}, 'errors': ['fixture']}):
        assert 'Pipeline de expertos' in service._expert_inputs_markdown(data)
