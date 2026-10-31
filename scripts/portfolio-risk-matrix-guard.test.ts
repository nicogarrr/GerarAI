import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const page = readFileSync('app/(root)/portfolio/intelligence/page.tsx', 'utf8');
const es = JSON.parse(readFileSync('lib/i18n/messages/es/portfolio.json', 'utf8'));
const en = JSON.parse(readFileSync('lib/i18n/messages/en/portfolio.json', 'utf8'));

test('RISKMATRIX-1: la tabla de contribución muestra el peso renormalizado', () => {
    // Review del piloto: el cálculo usa weight_included (pesos renormalizados
    // sobre las incluidas) y mostrar solo el peso de cartera confundía.
    assert.match(page, /rmColWeightIncluded/);
    assert.match(page, /pct\(row\.weight_included \?\? null\)/);
});

test('RISKMATRIX-2: con exclusiones, aviso visible de cobertura renormalizada', () => {
    // El aviso existe SOLO cuando hay excluidas y dice "sobre las incluidas".
    assert.match(page, /rmExcluded\.length > 0 \?\s*\(\s*<p[^>]*>\{ti\('portfolio\.intelligence\.rmCoverageNote', \{ n: rmIncluded\.length \}\)\}<\/p>/s);
    assert.match(es.intelligence.rmCoverageNote, /incluidas/);
    assert.match(es.intelligence.rmCoverageNote, /renormalizan/);
    assert.match(en.intelligence.rmCoverageNote, /included/);
    assert.match(en.intelligence.rmCoverageNote, /renormalized/);
});

test('RISKMATRIX-3: cada posición excluida lleva motivo traducido y conteo', () => {
    assert.match(page, /rmExcludedLine', \{ ticker: row\.ticker, reason: rmReasonLabel\(ti, row\.excluded_reason \?\? ''\), n: row\.sessions \}\)/);
    for (const key of ['rmReasonInsufficient', 'rmReasonFx', 'rmReasonNoValuation', 'rmReasonCalendar']) {
        assert.ok(es.intelligence[key], `es ${key}`);
        assert.ok(en.intelligence[key], `en ${key}`);
    }
});
