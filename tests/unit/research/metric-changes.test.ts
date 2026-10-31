import { describe, expect, it } from 'vitest';
import { metricChangeParts } from '@/lib/research/metric-changes';
import { markVisitRead, resolveVisitBaseline } from '@/lib/research/visit-baseline';

const store = () => { const m = new Map<string, string>(); return { getItem: (k: string) => m.get(k) ?? null, setItem: (k: string, v: string) => { m.set(k, v); } }; };

describe('Qué ha cambiado', () => {
    it('muestra anterior → nuevo con el periodo y marca revisiones y datos nuevos', () => {
        expect(metricChangeParts({ metric: 'revenue', unidad: 'USD', anterior: { valor: 100, periodo: 'FY2025' }, nuevo: { valor: 104, periodo: 'FY2025' } }))
            .toEqual({ before: '100 USD', after: '104 USD', note: 'FY2025, revisado' });
        expect(metricChangeParts({ metric: 'fcf', anterior: { valor: 20, periodo: 'Q2' }, nuevo: { valor: 26.5, periodo: 'Q3' } }))
            .toEqual({ before: '20', after: '26,5', note: 'Q2 → Q3' });
        expect(metricChangeParts({ metric: 'eps', anterior: null, nuevo: { valor: 1.5, periodo: 'Q3' } }).before).toBeNull();
    });

    it('«Marcar como leído» mueve la referencia a ahora en este navegador', () => {
        const local = store(); const session = store();
        local.setItem('cavaai:last-visit:CHG', '2026-10-01T00:00:00.000Z');
        expect(resolveVisitBaseline(local, session, 'chg', new Date('2026-10-31T10:00:00Z'))).toBe('2026-10-01T00:00:00.000Z');
        markVisitRead(local, session, 'chg', new Date('2026-10-31T11:00:00Z'));
        expect(resolveVisitBaseline(local, session, 'CHG', new Date('2026-10-31T12:00:00Z'))).toBe('2026-10-31T11:00:00.000Z');
    });
});
