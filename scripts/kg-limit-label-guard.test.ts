/**
 * F258: /knowledge-graph tenía un campo numérico con «120» sin etiqueta ni
 * nombre accesible (spinbutton value=120 sin nombre). El backend usa ese
 * limit como número máximo de nodos del grafo: se etiqueta como tal,
 * visible y accesible.
 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const page = readFileSync('app/(root)/knowledge-graph/page.tsx', 'utf8');
const kgDict = JSON.parse(readFileSync('lib/i18n/messages/es/knowledgeGraph.json', 'utf8'));

test('el campo limit va dentro de una etiqueta visible que lo nombra', () => {
    // i18n: la etiqueta referencia la clave y el diccionario es conserva «Máximo de nodos» verbatim.
    assert.match(page, /<label className="[^"]*">\{t\('knowledgeGraph\.page\.maxNodes'\)\}<Input[^>]*name="limit"[^>]*\/><\/label>/);
    assert.equal(kgDict.page.maxNodes, 'Máximo de nodos', 'la etiqueta del campo limit se mantiene verbatim');
});

test('el campo sigue siendo numérico con sus límites (1-500)', () => {
    assert.match(page, /name="limit" type="number"/);
    assert.match(page, /min="1"/);
    assert.match(page, /max="500"/);
});
