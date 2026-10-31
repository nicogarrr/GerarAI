import { describe, expect, it } from 'vitest';
import { impliedGrowthView } from '@/lib/research/implied-growth';

describe('Crecimiento implícito (Reverse DCF)', () => {
    it('formatea crecimiento perpetuo, reparto por años y rejilla con la casilla base marcada', () => {
        const view = impliedGrowthView({
            implied_perpetual_growth: 0.04,
            value_split: { years_1_5: 0.2, years_6_10: 0.25, years_11_plus: 0.55 },
            sensitivity: { wacc: [0.08, 0.09, 0.1], fcf_margin: [0.13, 0.15, 0.17], required_growth: [[0.05, 0.03, 0.02], [0.07, 0.05, 0.04], [0.09, 0.07, null]] },
        });
        expect(view.perpetual).toBe('4,0 %');
        expect(view.split.map((p) => [p.label, p.share, p.width])).toEqual([['Años 1–5', '20 %', 20], ['Años 6–10', '25 %', 25], ['Año 11 en adelante', '55 %', 55]]);
        expect(view.grid?.columns).toEqual(['Margen 13,0 %', 'Margen 15,0 %', 'Margen 17,0 %']);
        expect(view.grid?.rows[1].cells[1]).toEqual({ text: '5,0 %', base: true });
        expect(view.grid?.rows[2].cells[2].text).toBe('—');
    });

    it('sin datos no inventa nada', () => {
        expect(impliedGrowthView({})).toEqual({ perpetual: null, split: [], grid: null });
    });
});
