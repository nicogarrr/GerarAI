/**
 * Columna «Tipo» de las posiciones 13F: antes pintaba crudos del backend
 * («PUT», «SH», «PRN») y la cabecera «Filing» era un literal en inglés.
 * Regresión: códigos 13F traducidos (SH -> Acciones, PRN -> Principal,
 * PUT/CALL normalizados), desconocidos crudos, cabecera con clave i18n.
 */
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

import { holdingTypeLabel } from '@/lib/ownership-display';
import es from '@/lib/i18n/messages/es/ownership.json';
import en from '@/lib/i18n/messages/en/ownership.json';

describe('holdingTypeLabel: códigos 13F legibles', () => {
    it('SH -> Acciones / Shares', () => {
        expect(holdingTypeLabel(null, 'SH', 'es')).toBe('Acciones');
        expect(holdingTypeLabel(null, 'SH', 'en')).toBe('Shares');
    });
    it('PRN -> Principal (nominal de deuda)', () => {
        expect(holdingTypeLabel(null, 'PRN', 'es')).toBe('Principal');
        expect(holdingTypeLabel(null, 'PRN', 'en')).toBe('Principal');
    });
    it('PUT/CALL normalizados; put_call manda sobre share_type', () => {
        expect(holdingTypeLabel('PUT', 'SH', 'es')).toBe('Put');
        expect(holdingTypeLabel('CALL', null, 'en')).toBe('Call');
    });
    it('minúsculas del backend también se reconocen', () => {
        expect(holdingTypeLabel(null, 'sh', 'es')).toBe('Acciones');
    });
    it('código desconocido: crudo, nunca inventado', () => {
        expect(holdingTypeLabel(null, 'XYZ', 'es')).toBe('XYZ');
    });
    it('sin tipo: null (la página pinta N/D)', () => {
        expect(holdingTypeLabel(null, null, 'es')).toBeNull();
    });
});

describe('la página deja de pintar crudos y literales', () => {
    const source = readFileSync('app/(root)/ownership/page.tsx', 'utf8');
    it('sin el render crudo «row.put_call ?? row.share_type ?? NA»', () => {
        expect(source).not.toContain('{row.put_call ?? row.share_type ?? NA}');
    });
    it('sin la cabecera «Filing» hardcodeada', () => {
        expect(source).not.toContain('>Filing<');
        expect(source).toContain("t('ownership.page.col.filing')");
    });
});

describe('las claves nuevas existen en los dos idiomas', () => {
    it('page.col.filing y page.type.* en es y en', () => {
        expect(es.page.col.filing).toBe('Informe');
        expect(en.page.col.filing).toBe('Filing');
        expect(Object.keys(es.page.type).sort()).toEqual(Object.keys(en.page.type).sort());
        expect(Object.keys(es.page.type).sort()).toEqual(['call', 'principal', 'put', 'shares']);
    });
});
