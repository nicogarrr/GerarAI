/**
 * F380: el tooltip del gráfico usaba siempre USD aunque el listado fuese EUR/GBP.
 * Ejecución: node --experimental-strip-types --test scripts/market-chart-currency-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const source = (p: string): string => readFileSync(join(root, p), 'utf8');

describe('gráfico de mercado: divisa del listado', () => {
    it('no fija USD y recibe la divisa del snapshot', () => {
        const chart = source('components/research/CompanyMarketChart.tsx');
        assert.ok(!/formatMoney\(value, 'USD'\)/.test(chart));
        assert.match(chart, /currency\?: string \| null/);
    });
});
