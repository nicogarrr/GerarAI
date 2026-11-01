/**
 * Guard: el walk-forward pinta sus cortes en la zona del MERCADO.
 *
 * `asOf` llega como instante ISO de fin de mes (`2026-03-31T23:59:59.000Z`,
 * lib/actions/propicks-backtest.actions.ts). formatUserDate lo renderiza en
 * Europe/Madrid, donde ese instante ya es 01:59 del día 1: cada corte salía
 * UN DÍA tarde. formatMarketDate (America/New_York) lo mantiene en su día.
 *
 * Ejecución: node --experimental-strip-types --test scripts/propicks-walkforward-date-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

// @ts-expect-error TS5097: la extensión explícita la exige node --experimental-strip-types.
import { formatMarketDate, formatUserDate } from '../lib/format.ts';

const view = readFileSync('components/proPicks/WalkForwardResults.tsx', 'utf8');

describe('walk-forward: fechas de corte', () => {
    it('el desfase existe con la zona del usuario (demostración del bug)', () => {
        // Fin de marzo 23:59:59Z: en Madrid ya es 1 de abril; en NY es 31 de marzo.
        assert.match(formatUserDate('2026-03-31T23:59:59.000Z'), /1 abr\.? 2026/);
        assert.match(formatMarketDate('2026-03-31T23:59:59.000Z'), /31 mar\.? 2026/);
    });
    it('la vista usa formatMarketDate para asOf, nunca formatUserDate', () => {
        assert.ok(!/formatUserDate/.test(view), 'formatUserDate queda vetado en WalkForwardResults');
        assert.match(view, /from: formatMarketDate\(first\.asOf\), to: formatMarketDate\(last\.asOf\)/);
        const rowUses = view.match(/formatMarketDate\(row\.asOf\)/g) ?? [];
        assert.equal(rowUses.length, 2, 'tabla y tarjetas usan formatMarketDate(row.asOf)');
    });
});
