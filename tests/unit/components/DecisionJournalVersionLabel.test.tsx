import { describe, expect, it, vi } from 'vitest';

vi.mock('@/lib/actions/research.actions', () => ({
    createResearchDecision: vi.fn(),
    linkResearchDecisionTrade: vi.fn(),
    reviewResearchExpectations: vi.fn(),
}));

import { journalVersionLabel } from '@/components/research/FundamentalModelPanels';

describe('Decision journal version label', () => {
    it('names the thesis and model versions instead of internal database ids', () => {
        const label = journalVersionLabel({ thesis_version_id: 4817, model_version_id: 922, metadata: { thesis_version: 3, model_version: 2 } });
        expect(label).toBe('Contra tesis v3 · modelo v2');
        expect(label).not.toMatch(/4817|922/);
    });
    it('does not invent a version number when only the internal link exists', () => {
        expect(journalVersionLabel({ thesis_version_id: 4817, model_version_id: null, metadata: {} }))
            .toBe('Contra tesis registrada · sin modelo');
    });
    it.each([0, -1, 2.5, '3', null])('ignores an unusable stored version %s', (value) => {
        expect(journalVersionLabel({ thesis_version_id: 7, model_version_id: 8, metadata: { thesis_version: value, model_version: value } }))
            .toBe('Contra tesis registrada · modelo registrado');
    });
    it('says when the decision was recorded without thesis or model', () => {
        expect(journalVersionLabel({ thesis_version_id: null, model_version_id: null, metadata: {} })).toBe('Contra sin tesis · sin modelo');
    });
});
