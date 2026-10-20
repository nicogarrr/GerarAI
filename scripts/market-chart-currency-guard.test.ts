/**
 * F380: el gráfico de la ficha no puede fijar USD con listados en otra divisa.
 * (Antes cubría CompanyMarketChart, eliminado por código muerto; ahora el vivo.)
 * Ejecución: node --experimental-strip-types --test scripts/market-chart-currency-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const source = (p: string): string => readFileSync(join(root, p), 'utf8');

describe('gráfico técnico: divisa del listado', () => {
    it('no fija USD y muestra el número sin símbolo si la divisa falta o es inválida', () => {
        const chart = source('components/research/CompanyTechnicalChart.tsx');
        assert.ok(!/formatMoney\(value, 'USD'\)/.test(chart));
        assert.ok(!/'USD'/.test(chart), 'ningún USD literal en el chart vivo');
        assert.match(chart, /isValidCurrencyCode\(currency\) \? formatMoney\(value, currency\) : formatNumber\(value\)/);
    });
});
