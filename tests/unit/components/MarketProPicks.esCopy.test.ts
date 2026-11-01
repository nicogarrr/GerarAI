/**
 * Copy es-ES en vistas de Mercado/ProPicks:
 * - MarketRegime: «1 sesión» / «N sesiones» (regresión: «1 sesiones»).
 * - WalkForwardResults: «período» con tilde en la métrica SPY y la metodología.
 */
import { readFileSync } from 'node:fs';
import { describe, expect, it, vi } from 'vitest';

vi.mock('@/lib/actions/market-regime.actions', () => ({}));
vi.mock('@/components/system/BackendOffline', () => ({}));

import { trainingSessionsText } from '@/components/market/MarketRegime';

describe('trainingSessionsText', () => {
    it('singular y plural', () => {
        expect(trainingSessionsText(1)).toBe('1 sesión');
        expect(trainingSessionsText(5)).toBe('5 sesiones');
    });
});

describe('WalkForwardResults: tildes', () => {
    it('«mismo período» con tilde en métrica y metodología', () => {
        const source =
            readFileSync('components/proPicks/WalkForwardResults.tsx', 'utf8') +
            readFileSync('lib/i18n/messages/es/propicks.json', 'utf8');
        expect(source).not.toContain('mismo periodo');
        expect(source).toContain('mismo período');
    });
});
