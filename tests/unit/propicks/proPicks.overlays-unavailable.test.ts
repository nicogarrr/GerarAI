import { describe, expect, it, vi } from 'vitest';

vi.mock('@/lib/auth/require-user', () => ({ requireAuthenticatedUser: vi.fn() }));
vi.mock('@/lib/actions/propicks-funnel.actions', () => ({ getLatestFunnelPicks: vi.fn() }));
// El módulo de señales falla al cargarse (p. ej. dependencia rota): el pipeline
// debe seguir devolviendo los picks sin overlays en vez de romper.
vi.mock('@/lib/utils/propicksSignals', () => {
    throw new Error('módulo de señales no disponible');
});

import { attachSignalOverlays, type ProPick } from '@/lib/actions/proPicks.actions';

describe('attachSignalOverlays con el módulo de señales caído', () => {
    it('devuelve los finalistas tal cual, sin overlays ni facts ov_*', async () => {
        const picks = [
            {
                symbol: 'AAPL',
                company: 'Apple',
                score: 80,
                confidence: 70,
                confidenceLevel: 'Media',
                confidenceReasons: [],
                facts: { return12M: 12 },
                categoryScores: {},
            },
        ] as unknown as ProPick[];
        const out = await attachSignalOverlays(picks, '2026-10-27');
        expect(out).toHaveLength(1);
        expect(out[0].symbol).toBe('AAPL');
        expect(out[0].confidence).toBe(70);
        expect(Object.keys(out[0].facts).some((k) => k.startsWith('ov_'))).toBe(false);
        expect(out[0].overlays ?? []).toEqual([]);
    });
});
