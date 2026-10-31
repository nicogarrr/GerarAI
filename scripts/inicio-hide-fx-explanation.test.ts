import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const src = readFileSync(new URL('../components/portfolio/PortfolioValueBreakdown.tsx', import.meta.url), 'utf8');
test('Inicio hides the exchange-rate explanation and mixed-date note without changing valuation or incomplete-FX warning', () => {
    assert.doesNotMatch(src, /Tipos de cambio usados\./);
    assert.doesNotMatch(src, /summary\.valuationDatesDiffer/);
    assert.doesNotMatch(src, /el total combina fechas distintas/);
    // i18n: el aviso vive en messages/<locale>/portfolio.json.
    assert.match(src, /portfolio\.breakdown\.incompleteFx/);
    const breakdownEs = JSON.parse(readFileSync(new URL('../lib/i18n/messages/es/portfolio.json', import.meta.url), 'utf8'));
    assert.equal(breakdownEs.breakdown.incompleteFx, 'Faltan tipos de cambio. El desglose excluye esos saldos y posiciones.');
    assert.match(src, /formatMoney\(totalValue, baseCurrency\)/);
});
