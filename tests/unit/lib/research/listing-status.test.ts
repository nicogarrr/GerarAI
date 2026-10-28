import { describe, expect, it } from 'vitest';
import { healthText, listingStatus } from '@/lib/research/listing-status';

const now = new Date('2026-10-28T12:00:00Z');

describe('listingStatus', () => {
    it('cotización vigente: no obsoleta', () => {
        expect(listingStatus('NASDAQ', '2026-10-27', now)).toEqual({ stale: false });
    });
    it('cierre de hace más de 30 días: obsoleta con fecha en es-ES', () => {
        expect(listingStatus('NASDAQ', '2026-09-01', now)).toEqual({ stale: true, message: 'Ticker sin cotización vigente (último cierre 01/09/2026)' });
    });
    it('límite: 29,5 días vale, 31,5 no (la edad se mide a medianoche UTC)', () => {
        expect(listingStatus('NYSE', '2026-09-29', now).stale).toBe(false);
        expect(listingStatus('NYSE', '2026-09-27', now).stale).toBe(true);
    });
    it.each([null, undefined, '', ' unknown ', 'UNKNOWN_EXCHANGE'])('bolsa desconocida (%s) es obsoleta aunque el precio sea de hoy', (ex) => {
        expect(listingStatus(ex, '2026-10-28', now).stale).toBe(true);
    });
    it('sin cierre válido: mensaje sin fecha', () => {
        expect(listingStatus('', null, now)).toEqual({ stale: true, message: 'Ticker sin cotización vigente (sin cierre conocido)' });
        expect(listingStatus('', 'ayer', now)).toMatchObject({ message: expect.stringContaining('sin cierre conocido') });
    });
    it('bolsa conocida sin fecha de precio no se marca como obsoleta', () => {
        expect(listingStatus('NASDAQ', null, now)).toEqual({ stale: false });
    });
});

describe('healthText', () => {
    it('obsoleta o sin puntuación: Sin datos (un 0 real sí se muestra)', () => {
        expect(healthText(80, { stale: true, message: 'x' })).toBe('Sin datos');
        expect(healthText(null, { stale: false })).toBe('Sin datos');
        expect(healthText(undefined, { stale: false })).toBe('Sin datos');
        expect(healthText(0, { stale: false })).toBe('0/100');
        expect(healthText(72, { stale: false })).toBe('72/100');
    });
});
