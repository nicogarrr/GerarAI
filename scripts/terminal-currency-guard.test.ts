import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
// @ts-expect-error node strip-types needs extension.
import { formatProvenanceValue } from '../lib/research/provenance-format.ts';
test('terminal uses declared currency with English scale and no duplicate raw suffix',()=>{
 assert.equal(formatProvenanceValue(70918000,'USD'),'70,92 M\u00a0US$');
 assert.equal(formatProvenanceValue(19360000000,'USD'),'19,36 mil M\u00a0US$');
 assert.doesNotMatch(formatProvenanceValue(19360000000,'EUR'), /US\$/);
 // El terminal es una sección de la pestaña Finanzas desde el 29-oct-2026.
 const page=readFileSync('components/research/sections/FinancialTerminalSection.tsx','utf8');
 assert.match(page,/formatProvenanceValue\(raw, unit, locale\)/);
 assert.doesNotMatch(page,/>\{point.unit\}<\/span>/);
 // El literal vive en el diccionario (Ajustes → Idioma); en español no cambia.
 assert.match(page,/t\('research\.terminalSection\.noUnit'\)/);
 const es=JSON.parse(readFileSync('lib/i18n/messages/es/research.json','utf8'));
 assert.equal(es.terminalSection.noUnit,'N/D (unidad no disponible)');
});
