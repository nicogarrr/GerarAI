import { describe, expect, it } from 'vitest';

import { insiderRole, signalLabel, signalTooltip } from '@/lib/insider/format';

describe('Insiders en inglés', () => {
    it('cargo: título original de la SEC en inglés, traducido en español', () => {
        expect(insiderRole('Officer', 'Chief Financial Officer', 'en')).toBe('Chief Financial Officer');
        expect(insiderRole('Officer', 'Chief Financial Officer')).toBe('CFO');
        expect(insiderRole('Director, 10% Owner', null, 'en')).toBe('Director · 10% owner');
        expect(insiderRole('Officer', '', 'en')).toBe('Officer');
        expect(insiderRole('Multiple insiders', null, 'en')).toBe('Multiple insiders');
        expect(insiderRole(null, null, 'en')).toBe('Insider');
    });

    it('señales y su umbral según idioma', () => {
        expect(signalLabel('cluster_buy', 'en')).toBe('Cluster buy');
        expect(signalLabel('cluster_buy')).toBe('Cluster de compra');
        expect(signalTooltip('big_buy', 'en')).toBe('A single purchase above $1M');
        expect(signalTooltip('big_buy')).toBe('Una compra supera 1 M$');
        expect(signalLabel('otra', 'en')).toBe('otra');
        expect(signalTooltip('otra', 'en')).toBeUndefined();
    });
});
