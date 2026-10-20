/**
 * Guard de honestidad del NAV de cartera: la ventana se elige por fechas y
 * solo después se omiten los puntos sin NAV (nunca un 0 inventado, nunca un
 * dato fuera de ventana colado por un hueco).
 * Ejecución: node --experimental-strip-types --test scripts/portfolio-nav-honesty-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

// @ts-expect-error TS5097: la extensión explícita la exige node --experimental-strip-types.
import { windowNav } from '../lib/portfolio-nav.ts';

const tabs = readFileSync('components/portfolio/PortfolioTabs.tsx', 'utf8');

describe('NAV de cartera: sin ceros inventados', () => {
    it('ningún punto del gráfico fabrica un 0 cuando falta el NAV', () => {
        assert.ok(!/nav\[index\]\s*\?\?\s*0/.test(tabs), 'nav[index] ?? 0 dibuja un 0 falso');
        assert.ok(!/nav\[index\]\s*\|\|\s*0/.test(tabs), 'nav[index] || 0 dibuja un 0 falso');
    });
});

describe('NAV de cartera: la ventana se elige por fechas, no por puntos con dato', () => {
    // Repro del auditor: hueco de NAV en cambio de año.
    const dates = ['2025-12-30', '2025-12-31', '2026-01-01', '2026-01-02'];
    const nav = [100, 101, null, 102];

    it('YTD con hueco no cuela el 31 de diciembre', () => {
        assert.deepEqual(windowNav(dates, nav, 'YTD'), [{ date: '2026-01-02', value: 102 }]);
    });

    it('1S con hueco omite el punto sin NAV dentro de la ventana', () => {
        assert.deepEqual(windowNav(dates, nav, '1S'), [
            { date: '2025-12-30', value: 100 },
            { date: '2025-12-31', value: 101 },
            { date: '2026-01-02', value: 102 },
        ]);
    });

    it('Todo devuelve todos los puntos con dato', () => {
        assert.equal(windowNav(dates, nav, 'Todo').length, 3);
    });
});
