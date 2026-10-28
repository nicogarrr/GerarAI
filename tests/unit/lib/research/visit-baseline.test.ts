import { describe, expect, it } from 'vitest';
import { resolveVisitBaseline, type StorageLike } from '@/lib/research/visit-baseline';

const store = (init: Record<string, string> = {}): StorageLike & { data: Record<string, string> } => {
    const data = { ...init };
    return { data, getItem: (k) => (k in data ? data[k] : null), setItem: (k, v) => { data[k] = v; } };
};
const t1 = new Date('2026-10-01T10:00:00Z');
const t2 = new Date('2026-10-02T10:00:00Z');

describe('resolveVisitBaseline', () => {
    it('primera visita: sin referencia y se guarda la hora de visita', () => {
        const local = store(); const session = store();
        expect(resolveVisitBaseline(local, session, 'aapl', t1)).toBeNull();
        expect(local.data['cavaai:last-visit:AAPL']).toBe(t1.toISOString());
        expect(session.data['cavaai:visit-baseline:AAPL']).toBe('');
    });
    it('segunda visita (sesión nueva): la referencia es la visita anterior', () => {
        const local = store({ 'cavaai:last-visit:AAPL': t1.toISOString() });
        expect(resolveVisitBaseline(local, store(), 'AAPL', t2)).toBe(t1.toISOString());
        expect(local.data['cavaai:last-visit:AAPL']).toBe(t2.toISOString());
    });
    it('dentro de la misma sesión la referencia queda congelada (recargar no borra los cambios "nuevos")', () => {
        const local = store({ 'cavaai:last-visit:AAPL': t1.toISOString() }); const session = store();
        const first = resolveVisitBaseline(local, session, 'AAPL', t2);
        const reload = resolveVisitBaseline(local, session, 'AAPL', new Date('2026-10-02T10:05:00Z'));
        expect(reload).toBe(first);
    });
    it('congelado como vacío sigue siendo null aunque ya haya visita guardada', () => {
        const local = store(); const session = store();
        resolveVisitBaseline(local, session, 'AAPL', t1);
        expect(resolveVisitBaseline(local, session, 'AAPL', t2)).toBeNull();
    });
    it('fecha guardada corrupta se ignora', () => {
        const local = store({ 'cavaai:last-visit:AAPL': 'basura' });
        expect(resolveVisitBaseline(local, store(), 'AAPL', t1)).toBeNull();
    });
    it('tickers distintos no se mezclan; mayúsculas no importan', () => {
        const local = store({ 'cavaai:last-visit:AAPL': t1.toISOString() });
        expect(resolveVisitBaseline(local, store(), 'msft', t2)).toBeNull();
        expect(resolveVisitBaseline(local, store(), 'aapl', t2)).toBe(t1.toISOString());
    });
});
