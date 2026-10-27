import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const src = readFileSync(new URL('../components/portfolio/PortfolioValueBreakdown.tsx', import.meta.url), 'utf8');
test('Inicio hides the exchange-rate explanation without removing date or incomplete-FX warnings', () => {
    assert.doesNotMatch(src, /Tipos de cambio usados\./);
    assert.match(src, /summary\.valuationDatesDiffer/);
    assert.match(src, /el total combina fechas distintas/);
    assert.match(src, /Faltan tipos de cambio\. El desglose excluye esos saldos y posiciones\./);
    assert.match(src, /formatMoney\(totalValue, baseCurrency\)/);
});
