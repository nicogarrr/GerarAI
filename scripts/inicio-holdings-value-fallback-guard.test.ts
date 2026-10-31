import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const source = readFileSync(new URL('../components/PersonalizedOverview.tsx', import.meta.url), 'utf8');

test('Inicio: sin base de coste la posicion muestra valor y peso, no solo N/D', () => {
    assert.match(source, /formatMoney\(h\.value, h\.baseCurrency\)/);
    assert.match(source, /equityValue/);
});

test('Inicio: la rentabilidad solo sale con base de coste y divisa convertida', () => {
    assert.match(source, /h\.cost > 0 && !h\.fxMissing/);
});

const breakdown = readFileSync(new URL('../components/portfolio/PortfolioValueBreakdown.tsx', import.meta.url), 'utf8');
test('Inicio: bruto, saldos positivos, deuda y neto tienen etiquetas distintas', () => {
    for (const label of ['Posiciones (bruto)', 'Caja (saldos positivos)', 'Deuda de margen', 'Patrimonio neto']) {
        assert.ok(breakdown.includes(label), label);
    }
    assert.ok(source.includes('home.portfolio.weightsNote'));
    const dictHome = JSON.parse(readFileSync('lib/i18n/messages/es/home.json', 'utf8'));
    assert.equal(dictHome.portfolio.weightsNote, 'Pesos sobre el valor bruto de las posiciones.');
    assert.ok(source.includes('(h.value / portfolioSummary.equityValue)'));
});
test('Inicio: backend previo no se presenta como deuda bruta y falta FX se declara', () => {
    assert.ok(breakdown.includes('cashAssets !== undefined && marginDebt !== undefined'));
    assert.ok(breakdown.includes('Caja / margen neto'));
    assert.ok(breakdown.includes("status === 'incomplete_fx'"));
    assert.ok(breakdown.includes('(parcial)'));
});
