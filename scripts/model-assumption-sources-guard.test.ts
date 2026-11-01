import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const panels = readFileSync('components/research/FundamentalModelPanels.tsx', 'utf8');

test('Los supuestos del modelo enlazan a la fuente, no muestran ids internos', () => {
    assert.doesNotMatch(panels, /source_fact_ids\.join/);
    assert.match(panels, /<AssumptionSources fuentes=\{growthAssumption\?\.fuentes\}/);
    assert.match(panels, /<AssumptionSources fuentes=\{marginAssumption\?\.fuentes\}/);
});

test('Solo se enlaza https y sin fuente se dice "sin fuente"', () => {
    assert.ok(panels.includes("https:"), "solo https");
    assert.match(panels, /\.test\(fuente\.url\)/);
    assert.match(panels, /rel="noopener noreferrer"/);
    assert.match(panels, /<>\{ti\('research\.modelSources\.none'\)\}<\/>/);
    assert.equal(JSON.parse(readFileSync('lib/i18n/messages/es/research.json', 'utf8')).modelSources.none, 'sin fuente');
});
