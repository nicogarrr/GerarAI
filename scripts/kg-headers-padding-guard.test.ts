import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const page = readFileSync('app/(root)/knowledge-graph/page.tsx', 'utf8');
const kgDict = JSON.parse(readFileSync('lib/i18n/messages/es/knowledgeGraph.json', 'utf8'));

test('F312: Confianza conserva su padding en la tabla de relaciones', () => {
    // Confianza va alineada a la derecha con padding horizontal (F312). La
    // columna Procedencia se elimino de la tabla en #3527 (la procedencia
    // sigue disponible en la API).
    // i18n: la cabecera referencia la clave y el diccionario es conserva «Confianza» verbatim.
    assert.match(page, /px-3 py-2 text-right" scope="col">\{t\('knowledgeGraph\.page\.colConfidence'\)\}/);
    assert.equal(kgDict.page.colConfidence, 'Confianza', 'el rotulo de la columna se mantiene verbatim');
    assert.match(page, /px-3 py-3 text-right text-gray-400">\{formatConfidence\(edge\.confidence\)/);
});
