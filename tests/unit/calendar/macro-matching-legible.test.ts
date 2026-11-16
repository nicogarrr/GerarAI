/**
 * Chips «matching» del digest 8-K en /macro-calendar: pintaban el código SEC
 * crudo en mayúsculas («2.02»). Regresión: el chip debe leerse
 * «Item 2.02 · Resultados de explotación…» usando el título ya traducido
 * (entry.items en es; tabla ITEM_TITLES_EN en en); código desconocido: crudo.
 */
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

import { eightKItemTitle, eightKMatchingLabel, eightKReason } from '@/lib/calendar/eight-k-text';

const items = [{ code: '2.02', title: 'Resultados de explotación y situación financiera', official_title: null, excerpts: [] }];

describe('eightKMatchingLabel', () => {
    it('es: título del propio digest cuando el apartado tiene detalle', () => {
        expect(eightKMatchingLabel('2.02', items, 'es')).toBe('Item 2.02 · Resultados de explotación y situación financiera');
    });
    it('en: tabla oficial de títulos SEC aunque el apartado no tenga detalle', () => {
        expect(eightKMatchingLabel('2.02', [], 'en')).toBe('Item 2.02 · Results of Operations and Financial Condition');
    });
    it('en: el título del digest se traduce con la misma regla que los items', () => {
        expect(eightKMatchingLabel('2.02', items, 'en')).toBe('Item 2.02 · Results of Operations and Financial Condition');
    });
    it('código sin título conocido: crudo, nunca inventado', () => {
        expect(eightKMatchingLabel('9.99', items, 'es')).toBe('9.99');
        expect(eightKMatchingLabel('9.99', items, 'en')).toBe('9.99');
    });
});

describe('la página deja de pintar el código crudo en mayúsculas', () => {
    const source = readFileSync('app/(root)/macro-calendar/page.tsx', 'utf8');
    it('usa eightKMatchingLabel para los chips', () => {
        expect(source).toContain('eightKMatchingLabel(');
    });
    it('sin el chip crudo «uppercase ... {m}»', () => {
        expect(source).not.toMatch(/uppercase[^>]*>\{m\}</);
    });
});


describe('existing eight-k text boundaries', () => {
  it('preserves unknown titles and translates generic unknown items only in English', () => {
    expect(eightKItemTitle({ code: '9.99', title: 'Apartado 9.99' }, 'en')).toBe('Item 9.99');
    expect(eightKItemTitle({ code: '9.99', title: 'Custom disclosure' }, 'en')).toBe('Custom disclosure');
    expect(eightKItemTitle({ code: '2.02', title: 'Texto local' }, 'es')).toBe('Texto local');
  });
  it('preserves absent and unrecognized reasons, translates only known English reasons', () => {
    expect(eightKReason(null, 'en')).toBeNull();
    expect(eightKReason(undefined, 'en')).toBeUndefined();
    expect(eightKReason('', 'en')).toBe('');
    expect(eightKReason('Sin posiciones ni watchlist.', 'en')).toBe('No positions or watchlist.');
    expect(eightKReason('Sin posiciones ni watchlist.', 'es')).toBe('Sin posiciones ni watchlist.');
    expect(eightKReason('New reason', 'en')).toBe('New reason');
    expect(eightKReason('constructor', 'en')).toBe('constructor');
  });
});
