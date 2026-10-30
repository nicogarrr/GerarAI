import { describe, expect, it } from 'vitest';
import { buildPortfolioInsight } from '@/lib/portfolio-insight';

describe('buildPortfolioInsight: coste pendiente de revisión', () => {
    it('una posición con coste por revisar no entra en el % y marca la frase como parcial', () => {
        const insight = buildPortfolioInsight({ holdings: [
            { symbol: 'LIMPIA', cost: 1000, gain: 500, gainPercent: 50 },
            { symbol: 'REVISAR', cost: 3000, gain: -2100, gainPercent: -70, costReviewMessage: 'Divisa del coste sin verificar' },
        ] });
        expect(insight).toMatchObject({ kind: 'movement', direction: 'up', topSymbol: 'LIMPIA', partial: true });
        expect(insight.kind === 'movement' && insight.totalPercent).toBeCloseTo(50, 6);
    });
});
