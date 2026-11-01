import { describe, expect, it } from 'vitest';
import { groupClaimsByVersion } from '@/lib/research/claim-groups';
import { NOT_VALUABLE, researchValuabilityLabel } from '@/lib/research/coverage-state';
import { missingLayerAction, missingLayerLabel } from '@/lib/research/missing-layer-guidance';
import { createTranslator } from '@/lib/i18n/translate';

// Ficha de empresa con el inglés elegido: aviso de valorabilidad, capas que
// faltan y grupos de afirmaciones ya no salen en español.
describe('ficha en inglés: avisos y grupos', () => {
    const en = createTranslator('en');
    it('aviso de valorabilidad', () => {
        expect(researchValuabilityLabel(NOT_VALUABLE, en)).toBe('Not valuable / missing evidence');
        expect(researchValuabilityLabel('Revisar tesis y supuestos', en)).toBe('Review thesis and assumptions');
        expect(researchValuabilityLabel(NOT_VALUABLE)).toBe('No valorable / falta evidencia');
    });
    it('capas que faltan y su acción', () => {
        expect(missingLayerLabel('financial_facts', en)).toBe('financial facts');
        expect(missingLayerAction('AAPL', 'thesis', en)).toEqual({ href: '/research/AAPL?view=tesis', label: 'Open the thesis to generate it' });
        expect(missingLayerLabel('long_term_model')).toBe('modelo a largo plazo');
    });
    it('grupos de afirmaciones por versión de tesis', () => {
        const claims = [{ thesis_version_id: null }, { thesis_version_id: 7 }, { thesis_version_id: 9 }];
        const labels = groupClaimsByVersion(claims, [{ id: 7, version: 3 }], en).map((g) => g.label);
        expect(labels).toEqual(['No linked thesis version', 'Thesis v3', 'Linked thesis (ID 9, version N/A)']);
        expect(groupClaimsByVersion(claims, [{ id: 7, version: 3 }]).map((g) => g.label))
            .toEqual(['Sin versión de tesis vinculada', 'Tesis v3', 'Tesis vinculada (ID 9, versión N/D)']);
    });
});
