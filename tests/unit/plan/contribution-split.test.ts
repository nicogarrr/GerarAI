import { describe, expect, it } from 'vitest';

import { isContributionSplit, levelTone } from '@/lib/plan/contribution-split';

describe('reparto de la aportación: forma y color del nivel', () => {
    it('valida la forma de la respuesta', () => {
        expect(isContributionSplit({ plan_exists: true })).toBe(true);
        expect(isContributionSplit({ plan_exists: false })).toBe(true);
        expect(isContributionSplit({ detail: 'Not Found' })).toBe(false);
        expect(isContributionSplit(null)).toBe(false);
        expect(isContributionSplit('plan')).toBe(false);
    });

    it('colorea el nivel DCA: recorte en ámbar, compra fuerte en teal', () => {
        expect(levelTone(null)).toBe('text-gray-500');
        expect(levelTone(-2)).toBe('text-amber-300');
        expect(levelTone(0)).toBe('text-amber-300');
        expect(levelTone(3)).toBe('text-teal-300');
        expect(levelTone(4)).toBe('text-teal-300');
        expect(levelTone(1)).toBe('text-gray-200');
    });
});
