import { describe, expect, it } from 'vitest';
import { holdingsVerificationNote } from '@/lib/ownership-display';

describe('holdingsVerificationNote · idioma del aviso de verificación 13F', () => {
    it('traduce los cuatro estados conocidos al inglés', () => {
        expect(holdingsVerificationNote('mismatch', 'en')).toBe('The stored totals do not match the 13F own summary: figures unverified.');
        expect(holdingsVerificationNote('unverified', 'en')).toBe('The 13F summary could not be read to check the totals: figures unverified.');
        expect(holdingsVerificationNote('partial', 'en')).toBe('Partial data: part of the filing could not be downloaded or verified.');
        expect(holdingsVerificationNote('snapshot', 'en')).toBe('Figures served from a local snapshot, not checked against the 13F: unverified.');
    });
    it('mantiene el castellano por defecto y con locale es', () => {
        expect(holdingsVerificationNote('unverified')).toBe('No se pudo leer el resumen del 13F para contrastar los totales: cifras sin verificar.');
        expect(holdingsVerificationNote('unverified', 'es')).toBe(holdingsVerificationNote('unverified'));
    });
    it('un estado desconocido no inventa aviso en ningún idioma', () => {
        expect(holdingsVerificationNote('ok')).toBeNull();
        expect(holdingsVerificationNote('ok', 'en')).toBeNull();
        expect(holdingsVerificationNote('codigo-nuevo', 'en')).toBeNull();
    });
});
