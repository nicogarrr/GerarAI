from app.services.moat_classification import classification, classify_result


def test_mapping_never_forces_ambiguous_types():
    for key in ['network_effects', 'distribution', 'data', 'ecosystem', 'process_advantage', 'new_type']:
        assert classification(key)['type'] is None
        assert classification(key)['label'] == 'Sin clasificar'
    assert classification('switching_costs')['type'] == 'customer_lock'
    assert classification('brand')['type'] == 'perceived_product'


def test_mapping_does_not_change_scores():
    result = classify_result({'moats': [{'type': 'brand', 'strength': 44}], 'unevaluated_moats': [{'type': 'data', 'strength': None}]})
    assert result['moats'][0]['strength'] == 44
    assert result['unevaluated_moats'][0]['strength'] is None
    assert len(result['nico_mapping']['types']) == 5
    assert 'real_product' not in result['nico_mapping']['mapping'].values()
