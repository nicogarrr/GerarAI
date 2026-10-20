/**
 * Guard de honestidad del NAV de cartera: un punto sin dato se omite, nunca
 * se dibuja como 0 (un hueco en la serie no es una caída a cero).
 * Ejecución: node --experimental-strip-types --test scripts/portfolio-nav-honesty-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const tabs = readFileSync('components/portfolio/PortfolioTabs.tsx', 'utf8');

describe('NAV de cartera: sin ceros inventados', () => {
    it('ningún punto del gráfico fabrica un 0 cuando falta el NAV', () => {
        assert.ok(!/nav\[index\]\s*\?\?\s*0/.test(tabs), 'nav[index] ?? 0 dibuja un 0 falso');
        assert.ok(!/nav\[index\]\s*\|\|\s*0/.test(tabs), 'nav[index] || 0 dibuja un 0 falso');
    });

    it('los puntos sin NAV se omiten explícitamente', () => {
        assert.match(tabs, /value == null\) return \[\]/);
    });
});
