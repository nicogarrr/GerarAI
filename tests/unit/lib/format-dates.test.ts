import { describe, expect, it } from 'vitest';

import {
    formatDate,
    formatMarketDate,
    formatUserDate,
    formatDateTime,
    formatMarketDateTime,
    naFor,
    noCorridoFor,
} from '@/lib/format';

/**
 * Fechas de formato: YYYY-MM-DD es día de calendario, no instante; la zona
 * del mercado (America/New_York) y la del usuario (Europe/Madrid) no deben
 * desplazar el día. Estos tests pinchan los casos que antes restaban un día.
 */

describe('naFor y noCorridoFor', () => {
    it('español', () => {
        expect(naFor('es')).toBe('N/D');
        expect(noCorridoFor('es')).toBe('No corrido');
    });
    it('inglés', () => {
        expect(naFor('en')).toBe('N/A');
        expect(noCorridoFor('en')).toBe('Not run');
    });
});

describe('formatDate (zona local del runtime)', () => {
    it('YYYY-MM-DD se renderiza como ese día, no el anterior', () => {
        expect(formatDate('2026-11-13', { day: 'numeric', month: 'short', year: 'numeric' }, undefined, 'es')).toBe('13 nov 2026');
        expect(formatDate('2026-11-13', { day: 'numeric', month: 'short', year: 'numeric' }, undefined, 'en')).toBe('Nov 13, 2026');
    });
    it('null devuelve el fallback', () => {
        expect(formatDate(null, {}, 'sin fecha', 'es')).toBe('sin fecha');
        expect(formatDate(undefined, {}, undefined, 'es')).toBe('N/D');
    });
    it('cadena vacía devuelve N/D', () => {
        expect(formatDate('', {}, undefined, 'es')).toBe('N/D');
    });
});

describe('formatMarketDate (zona America/New_York)', () => {
    it('YYYY-MM-DD es el día literal, sin restar un día por la zona', () => {
        // Un string YYYY-MM-DD parseado como UTC midnight y convertido a
        // America/New_York daría el día anterior (tarde del día anterior).
        expect(formatMarketDate('2026-11-13', { day: 'numeric', month: 'short', year: 'numeric' }, undefined, 'es')).toBe('13 nov 2026');
        expect(formatMarketDate('2026-01-01', { day: 'numeric', month: 'short', year: 'numeric' }, undefined, 'es')).toBe('1 ene 2026');
    });
    it('instante ISO se convierte a la zona del mercado', () => {
        // 2026-11-13T23:00Z es 18:00 en NY: mismo día.
        expect(formatMarketDate('2026-11-13T23:00:00Z', { day: 'numeric', month: 'short', year: 'numeric' }, undefined, 'es')).toBe('13 nov 2026');
    });
    it('null devuelve N/D', () => {
        expect(formatMarketDate(null, {}, undefined, 'es')).toBe('N/D');
    });
});

describe('formatUserDate (zona Europe/Madrid)', () => {
    it('YYYY-MM-DD es el día literal', () => {
        expect(formatUserDate('2026-11-13', { day: 'numeric', month: 'short', year: 'numeric' }, undefined, 'es')).toBe('13 nov 2026');
    });
});

describe('formatDateTime', () => {
    it('incluye hora', () => {
        const result = formatDateTime('2026-11-13T15:30:00Z', undefined, undefined, 'es');
        expect(result).toContain('13');
        expect(result).toContain('2026');
        // Hora presente (formato 24h o 12h según ICU, pero siempre dos dígitos).
        expect(result).toMatch(/\d{1,2}:\d{2}/);
    });
});

describe('formatMarketDateTime', () => {
    it('convierte a la zona del mercado', () => {
        // 2026-11-13T23:00Z es 18:00 en NY.
        const result = formatMarketDateTime('2026-11-13T23:00:00Z', undefined, undefined, 'es');
        expect(result).toContain('13');
    });
});

// ── Bloque 2: resto de lib/format.ts ─────────────────────────────────────────

import {
    formatNumber,
    formatMoney,
    formatPrice,
    formatCompact,
    formatMoneyCompact,
    formatMarketCapUsd,
    formatMarketCap,
    formatPercent,
    formatConfidence,
    formatCountEs,
    currencySymbolEs,
    formatGeneratedDate,
    formatUserDateTime,
    todayLocal,
    formatAgeShort,
    formatTimeAgo,
    marginOfSafetyDisplay,
    formatCompanyName,
    isValidCurrencyCode,
} from '@/lib/format';

describe('formatNumber', () => {
    it('agrupa con separador español', () => {
        expect(formatNumber(1234.56, {}, undefined, 'es')).toBe('1.234,56');
    });
    it('acepta string numérico', () => {
        expect(formatNumber('42', {}, undefined, 'es')).toBe('42');
    });
    it('null y no finito devuelven N/D', () => {
        expect(formatNumber(null, {}, undefined, 'es')).toBe('N/D');
        expect(formatNumber('abc', {}, undefined, 'es')).toBe('N/D');
        expect(formatNumber(NaN, {}, undefined, 'es')).toBe('N/D');
    });
    it('respeta fallback', () => {
        expect(formatNumber(null, {}, 'sin dato', 'es')).toBe('sin dato');
    });
});

describe('formatMoney', () => {
    it('USD en es-ES', () => {
        expect(formatMoney(1234.56, 'USD', {}, undefined, 'es')).toBe(`1.234,56\u00a0US$`);
    });
    it('EUR en es-ES', () => {
        expect(formatMoney(1234.56, 'EUR', {}, undefined, 'es')).toBe(`1.234,56\u00a0€`);
    });
    it('null devuelve N/D', () => {
        expect(formatMoney(null, 'USD', {}, undefined, 'es')).toBe('N/D');
    });
});

describe('formatPrice', () => {
    it('precio normal con 2 decimales', () => {
        expect(formatPrice(93.9, 'USD', {}, undefined, 'es')).toBe(`93,90\u00a0US$`);
    });
    it('precio muy pequeño con dígitos significativos', () => {
        const result = formatPrice(0.0011, 'USD', {}, undefined, 'es');
        expect(result).not.toBe('0,00 US$');
        expect(result).toContain('0,0011');
    });
    it('null devuelve N/D', () => {
        expect(formatPrice(null, 'USD', {}, undefined, 'es')).toBe('N/D');
    });
});

describe('formatCompact', () => {
    it('millones', () => {
        expect(formatCompact(1_500_000, {}, undefined, 'es')).toBe('1,5 M');
    });
    it('miles de millones', () => {
        expect(formatCompact(4_870_000_000, {}, undefined, 'es')).toBe('4,87 mil M');
    });
    it('billones (1e12)', () => {
        expect(formatCompact(3_414_000_000_000, {}, undefined, 'es')).toBe('3,41 B');
    });
    it('null devuelve N/D', () => {
        expect(formatCompact(null, {}, undefined, 'es')).toBe('N/D');
    });
    it('en-US usa notación compacta nativa', () => {
        expect(formatCompact(4_870_000_000, {}, undefined, 'en')).toBe('4.87B');
    });
});

describe('formatMoneyCompact', () => {
    it('USD en es-ES', () => {
        expect(formatMoneyCompact(4_870_000_000, 'USD', {}, undefined, 'es')).toBe(`4,87 mil M\u00a0US$`);
    });
    it('GBp (peniques) en es-ES', () => {
        expect(formatMoneyCompact(120_000_000, 'GBp', {}, undefined, 'es')).toBe(`120 M\u00a0p`);
    });
    it('null devuelve N/D', () => {
        expect(formatMoneyCompact(null, 'USD', {}, undefined, 'es')).toBe('N/D');
    });
});

describe('formatMarketCapUsd', () => {
    it('delega en formatMoneyCompact con USD', () => {
        expect(formatMarketCapUsd(4_870_000_000, undefined, 'es')).toBe(`4,87 mil M\u00a0US$`);
    });
});

describe('formatMarketCap', () => {
    it('con divisa real', () => {
        expect(formatMarketCap(4_870_000_000, 'EUR', undefined, 'es')).toBe(`4,87 mil M\u00a0€`);
    });
    it('sin divisa: número pelado', () => {
        expect(formatMarketCap(4_870_000_000, null, undefined, 'es')).toBe('4,87 mil M');
    });
    it('divisa inválida: número pelado', () => {
        expect(formatMarketCap(4_870_000_000, 'XX', undefined, 'es')).toBe('4,87 mil M');
    });
    it('peniques', () => {
        expect(formatMarketCap(120_000_000, 'GBp', undefined, 'es')).toBe(`120 M\u00a0p`);
    });
});

describe('formatPercent', () => {
    it('ratio por defecto', () => {
        expect(formatPercent(0.15, {}, undefined, 'es')).toBe(`15,0\u00a0%`);
    });
    it('fromRatio: false', () => {
        expect(formatPercent(15, { fromRatio: false }, undefined, 'es')).toBe(`15,0\u00a0%`);
    });
    it('digits', () => {
        expect(formatPercent(0.123456, { digits: 2 }, undefined, 'es')).toBe(`12,35\u00a0%`);
    });
    it('null devuelve N/D', () => {
        expect(formatPercent(null, {}, undefined, 'es')).toBe('N/D');
    });
    it('cero redondeado es neutral', () => {
        expect(formatPercent(-0.0004, {}, undefined, 'es')).toBe(`0,0\u00a0%`);
    });
});

describe('formatConfidence', () => {
    it('0.9 -> 90%', () => {
        expect(formatConfidence(0.9, 'N/D')).toBe('90%');
    });
    it('null devuelve fallback', () => {
        expect(formatConfidence(null, 'N/D')).toBe('N/D');
    });
});

describe('formatCountEs', () => {
    it('singular y plural', () => {
        expect(formatCountEs(1, 'posición', 'posiciones', 'es')).toBe('1 posición');
        expect(formatCountEs(5, 'posición', 'posiciones', 'es')).toBe('5 posiciones');
    });
    it('0 es plural', () => {
        expect(formatCountEs(0, 'posición', 'posiciones', 'es')).toBe('0 posiciones');
    });
});

describe('currencySymbolEs', () => {
    it('USD', () => {
        expect(currencySymbolEs('USD', 'es')).toBe('US$');
    });
    it('EUR', () => {
        expect(currencySymbolEs('EUR', 'es')).toBe('€');
    });
    it('peniques', () => {
        expect(currencySymbolEs('GBp', 'es')).toBe('p');
    });
    it('divisa desconocida devuelve el código', () => {
        expect(currencySymbolEs("¤", 'es')).toBe('¤');
    });
});

describe('formatGeneratedDate', () => {
    it('fecha válida', () => {
        expect(formatGeneratedDate('2026-11-13', { day: 'numeric', month: 'short', year: 'numeric' }, 'es')).toBe('13 nov 2026');
    });
    it('null y no parseable devuelven null', () => {
        expect(formatGeneratedDate(null, {}, 'es')).toBeNull();
        expect(formatGeneratedDate('no-fecha', {}, 'es')).toBeNull();
    });
});

describe('formatUserDateTime', () => {
    it('YYYY-MM-DD sin hora (evita React #418)', () => {
        const result = formatUserDateTime('2026-11-13', undefined, undefined, 'es');
        expect(result).toBe('13 nov 2026');
        expect(result).not.toMatch(/\d{1,2}:\d{2}/);
    });
    it('instante con hora', () => {
        const result = formatUserDateTime('2026-11-13T15:30:00Z', undefined, undefined, 'es');
        expect(result).toMatch(/\d{1,2}:\d{2}/);
    });
});

describe('todayLocal', () => {
    it('devuelve YYYY-MM-DD', () => {
        expect(todayLocal()).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    });
    it('acepta fecha inyectable', () => {
        expect(todayLocal(new Date('2026-06-15T12:00:00Z'))).toBe('2026-06-15');
    });
});

describe('formatAgeShort', () => {
    it('ahora', () => {
        expect(formatAgeShort(Date.now() / 1000, Date.now(), 'es')).toBe('ahora');
        expect(formatAgeShort(Date.now() / 1000, Date.now(), 'en')).toBe('now');
    });
    it('minutos', () => {
        expect(formatAgeShort((Date.now() - 5 * 60_000) / 1000, Date.now(), 'es')).toBe('5 min');
    });
    it('horas', () => {
        expect(formatAgeShort((Date.now() - 3 * 3_600_000) / 1000, Date.now(), 'es')).toBe('3 h');
    });
    it('días', () => {
        expect(formatAgeShort((Date.now() - 2 * 86_400_000) / 1000, Date.now(), 'es')).toBe('2 d');
    });
    it('más de 6 días devuelve null', () => {
        expect(formatAgeShort((Date.now() - 8 * 86_400_000) / 1000, Date.now(), 'es')).toBeNull();
    });
    it('null y futuro devuelven null', () => {
        expect(formatAgeShort(null, Date.now(), 'es')).toBeNull();
        expect(formatAgeShort((Date.now() + 60_000) / 1000, Date.now(), 'es')).toBe('ahora');
    });
});

describe('formatTimeAgo', () => {
    const ref = new Date('2026-11-13T12:00:00Z').getTime();
    it('ahora mismo', () => {
        expect(formatTimeAgo(ref / 1000, ref, 'es')).toBe('ahora mismo');
        expect(formatTimeAgo(ref / 1000, ref, 'en')).toBe('just now');
    });
    it('minutos', () => {
        expect(formatTimeAgo((ref - 5 * 60_000) / 1000, ref, 'es')).toBe('hace 5 minutos');
        expect(formatTimeAgo((ref - 1 * 60_000) / 1000, ref, 'es')).toBe('hace 1 minuto');
    });
    it('horas', () => {
        expect(formatTimeAgo((ref - 3 * 3_600_000) / 1000, ref, 'es')).toBe('hace 3 horas');
        expect(formatTimeAgo((ref - 1 * 3_600_000) / 1000, ref, 'es')).toBe('hace 1 hora');
    });
    it('días', () => {
        expect(formatTimeAgo((ref - 2 * 86_400_000) / 1000, ref, 'es')).toBe('hace 2 días');
        expect(formatTimeAgo((ref - 1 * 86_400_000) / 1000, ref, 'es')).toBe('hace 1 día');
    });
    it('inglés', () => {
        expect(formatTimeAgo((ref - 5 * 60_000) / 1000, ref, 'en')).toBe('5 minutes ago');
        expect(formatTimeAgo((ref - 3 * 3_600_000) / 1000, ref, 'en')).toBe('3 hours ago');
        expect(formatTimeAgo((ref - 2 * 86_400_000) / 1000, ref, 'en')).toBe('2 days ago');
    });
    it('null devuelve N/D', () => {
        expect(formatTimeAgo(null, ref, 'es')).toBe('N/D');
    });
});

describe('marginOfSafetyDisplay', () => {
    it('base positiva muestra el porcentaje', () => {
        expect(marginOfSafetyDisplay(0.25, 100, 'es')).toBe(`25,0\u00a0%`);
    });
    it('base no positiva devuelve N/D', () => {
        expect(marginOfSafetyDisplay(0.25, 0, 'es')).toBe('N/D');
        expect(marginOfSafetyDisplay(0.25, -10, 'es')).toBe('N/D');
    });
    it('margen null devuelve N/D', () => {
        expect(marginOfSafetyDisplay(null, 100, 'es')).toBe('N/D');
    });
});

describe('formatCompanyName', () => {
    it('ya mezcla mayúsculas y minúsculas: respeta', () => {
        expect(formatCompanyName('Apple Inc', 'es')).toBe('Apple Inc');
    });
    it('todo mayúsculas: pasa a Title Case', () => {
        expect(formatCompanyName('APPLE INC', 'es')).toBe('Apple Inc');
    });
    it('siglas de 3 letras se conservan', () => {
        expect(formatCompanyName('INTERNATIONAL BUSINESS MACHINES', 'es')).toBe('International Business Machines');
        expect(formatCompanyName('IBM', 'es')).toBe('IBM');
    });
    it('sufijos corporativos', () => {
        expect(formatCompanyName('COCA-COLA CO', 'es')).toBe('Coca-Cola Co');
    });
    it('LT recortado se expande', () => {
        expect(formatCompanyName('VODAFONE GROUP LT', 'es')).toBe('Vodafone Group Ltd');
    });
    it('null devuelve N/D', () => {
        expect(formatCompanyName(null, 'es')).toBe('N/D');
    });
});

describe('isValidCurrencyCode', () => {
    it('códigos ISO de 3 letras', () => {
        expect(isValidCurrencyCode('USD')).toBe(true);
        expect(isValidCurrencyCode('EUR')).toBe(true);
        expect(isValidCurrencyCode('GBP')).toBe(true);
    });
    it('peniques', () => {
        expect(isValidCurrencyCode('GBp')).toBe(true);
        expect(isValidCurrencyCode('GBX')).toBe(true);
    });
    it('inválidos', () => {
        expect(isValidCurrencyCode('')).toBe(false);
        expect(isValidCurrencyCode('US')).toBe(false);
        expect(isValidCurrencyCode('USDD')).toBe(false);
        expect(isValidCurrencyCode(null)).toBe(false);
        expect(isValidCurrencyCode(undefined)).toBe(false);
    });
});
