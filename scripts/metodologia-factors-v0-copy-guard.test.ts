import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

// factors-v0: el párrafo de factores observacionales de /metodologia debe
// describir FIELMENTE lo que calcula el embudo (auditoría 16-nov-2026):
// quality = percentil del moat, momentum = percentil de momentum_12_1,
// value = EY/FCFY en no financieras y P/B+ROE en financieras — nunca
// «spread CFROI-WACC» (eso es la categoría value del SCORE, otra cosa).

const pagina = readFileSync('app/(public)/metodologia/page.tsx', 'utf8');
const es = JSON.parse(readFileSync('lib/i18n/messages/es/landing.json', 'utf8'));
const en = JSON.parse(readFileSync('lib/i18n/messages/en/landing.json', 'utf8'));
const esFactors = es.metodologia.funnel.factorsRest as string;
const enFactors = en.metodologia.funnel.factorsRest as string;

test('la página cablea el párrafo de factores observacionales', () => {
    assert.match(pagina, /t\('landing\.metodologia\.funnel\.factorsStrong'\)/);
    assert.match(pagina, /t\('landing\.metodologia\.funnel\.factorsRest'\)/);
});

test('ES: los tres factores se definen con sus métricas reales', () => {
    assert.match(esFactors, /momentum_12_1/);
    assert.match(esFactors, /quality_moat_score_v2/);
    assert.match(esFactors, /earnings yield \/ FCF yield/);
    assert.match(esFactors, /P\/B/);
    assert.match(esFactors, /ROE/);
    // Declarados observacionales: sin efecto en score/pesos/ranking y sin validar.
    assert.match(esFactors, /no entran en el score/i);
    assert.match(esFactors, /pendientes de validación PIT\/OOS/);
});

test('ES: factor_value NO se describe como spread CFROI-WACC', () => {
    // El spread CFROI-WACC es la categoría value del score; el factor
    // observacional value usa EY/FCFY (no financieras) y P/B+ROE (financieras).
    const frase = esFactors.split('.')[0];
    assert.doesNotMatch(frase, /spread CFROI-WACC/);
});

test('EN: paridad del párrafo de factores', () => {
    assert.ok(en.metodologia.funnel.factorsStrong);
    assert.match(enFactors, /momentum_12_1/);
    assert.match(enFactors, /earnings yield \/ FCF yield/);
    assert.match(enFactors, /do not enter the score/i);
    assert.match(enFactors, /pending PIT\/OOS validation/);
});
