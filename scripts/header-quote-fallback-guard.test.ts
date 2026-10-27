import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

/**
 * Cabecera de precio: si la cotización tarda (>4 s) o no llega, cae al último
 * cierre de las velas del gráfico, rotulado con su fecha; y el logo nunca
 * deja un hueco (iniciales mientras carga y recuperación de errores previos
 * a la hidratación).
 */
const header = readFileSync('components/research/CompanyHeaderQuote.tsx', 'utf8');
const logo = readFileSync('components/calendar/CompanyLogo.tsx', 'utf8');

describe('cabecera de precio con fallback al cierre del gráfico', () => {
    it('espera 4 s y usa solo datos de las velas (sin inventar métricas)', () => {
        assert.match(header, /setTimeout\(\(\) => setSlow\(true\), 4000\)/);
        assert.match(header, /snapshot\.history\.at\(-1\)/);
        assert.match(header, /Último cierre del gráfico/);
        assert.match(header, /Cotización en vivo no disponible ahora/);
        assert.match(header, /last\?\.open \?\? null/);
    });
    it('subunidades (GBX): fallback solo con la divisa del listado ya en subunidad, y rotula la vela parcial', () => {
        assert.match(header, /chartFallbackCurrency\(/);
        assert.match(header, /GBX/);
        assert.match(header, /isValidCurrencyCode\(fallbackCurrency\)/);
        assert.match(header, /Última vela del gráfico \(puede ser parcial\)/);
        assert.match(header, /lastIsClose/);
    });
    it('la rama de cotización real sigue exigiendo metadata y fecha de cierre anterior', () => {
        assert.match(header, /hasDatedMetrics \? quote!.open : null/);
        assert.match(header, /\['Cierre anterior', quote\?\.previous_close_timestamp \|\| quote\?\.previous_close_date \? quote.previous_close : null\]/);
    });
    it('la cotización real sustituye al fallback cuando llega', () => {
        assert.match(header, /const useFallback = !showPrice && /);
    });
});

describe('logo de la cabecera', () => {
    it('muestra iniciales mientras carga y recupera errores previos a hidratar', () => {
        assert.match(logo, /el\.complete/);
        assert.match(logo, /naturalWidth === 0/); // misma comprobación, rama de fallo
        assert.match(logo, /loading \?/); // iniciales mientras carga (estado derivado)
        assert.ok(!logo.includes('loading="lazy"'), 'lazy dejaba la imagen sin pedir en un hueco vacío');
    });
});
