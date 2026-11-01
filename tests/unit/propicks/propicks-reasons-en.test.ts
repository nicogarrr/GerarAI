import { describe, expect, it } from 'vitest';
import { reasonDisplayText } from '@/components/proPicks/monthlyRebalance';

// Los motivos de Pro Picks (embudo y señales de mercado) se guardan en
// español con cifras es-ES; con el inglés elegido se traducen al pintarlos.
describe('Pro Picks en inglés: motivos y detalle de señales', () => {
    const cases: Array<[string, string]> = [
        ['Marco de calidad 7/9 criterios superados según fundamentales auditados',
            'Quality framework: 7/9 criteria passed on audited fundamentals'],
        ['CFROI 18,4 % vs WACC 8,1 %: spread de 10,3 puntos', 'CFROI 18.4% vs WACC 8.1%: spread of 10.3 points'],
        ['Ingresos creciendo al 50,2 % anual (5 años)', 'Revenue growing 50.2% a year (5 years)'],
        ['Margen FCF medio del 21,7 % (5 años)', 'Average FCF margin of 21.7% (5 years)'],
        ['Sorpresa media de beneficios +4,2 % en 4 trimestres hasta 2026-Q3 (valor 4.2)',
            'Average earnings surprise +4.2% over 4 quarters through 2026-Q3 (value 4.2)'],
        ['Sorpresa media de beneficios -1,0 % en 1 trimestre hasta 2026-Q3 (valor -1)',
            'Average earnings surprise -1.0% over 1 quarter through 2026-Q3 (value -1)'],
        ['Compra neta insider: 3 compras frente a 1 venta en 90 días hasta 2026-10-20 (valor 2)',
            'Net insider buying: 3 buys vs 1 sale in 90 days through 2026-10-20 (value 2)'],
        ['Interés en corto FINRA de 12.345.678 acciones a 2026-10-15 (valor 12345678)',
            'FINRA short interest of 12,345,678 shares as of 2026-10-15 (value 12345678)'],
        ['VIX en 31,2 el 2026-10-28 (régimen de aversión al riesgo alta) (valor 31.2)',
            'VIX at 31.2 on 2026-10-28 (high risk aversion regime) (value 31.2)'],
        ['VIX en 13,9 el 2026-10-28 (régimen de complacencia/calma) (valor 13.9)',
            'VIX at 13.9 on 2026-10-28 (complacency/calm regime) (value 13.9)'],
    ];
    it.each(cases)('«%s» sale en inglés', (es, en) => {
        expect(reasonDisplayText(es, 'en')).toBe(en);
    });
    it('en español el motivo queda tal cual', () => {
        for (const [es] of cases) expect(reasonDisplayText(es, 'es')).toBe(es);
    });
    it('un motivo desconocido no se toca', () => {
        expect(reasonDisplayText('Algo nuevo del backend', 'en')).toBe('Algo nuevo del backend');
    });
});
