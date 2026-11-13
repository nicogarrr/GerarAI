import { describe, expect, it } from 'vitest';
import { ipoMonthsLabel } from '@/lib/calendar/ipo-months';

// Meses del backend IPO: el backend los nombra en castellano
// (ipo_calendar.py) y en inglés la página los traduce por índice con Intl.
describe('ipoMonthsLabel', () => {
    it('en español pasa los meses tal como los manda el backend', () => {
        expect(ipoMonthsLabel(['noviembre', 'diciembre'], 'es')).toBe('noviembre, diciembre');
    });

    it('en inglés traduce los meses castellanos', () => {
        expect(ipoMonthsLabel(['noviembre', 'diciembre'], 'en')).toBe('November, December');
        expect(ipoMonthsLabel(['enero'], 'en')).toBe('January');
        expect(ipoMonthsLabel(['agosto'], 'en')).toBe('August');
    });

    it('un mes que no se reconoce pasa tal cual, en cualquier idioma', () => {
        expect(ipoMonthsLabel(['brumaire'], 'en')).toBe('brumaire');
        expect(ipoMonthsLabel(['brumaire'], 'es')).toBe('brumaire');
    });

    it('lista vacía queda vacía', () => {
        expect(ipoMonthsLabel([], 'en')).toBe('');
    });
});
