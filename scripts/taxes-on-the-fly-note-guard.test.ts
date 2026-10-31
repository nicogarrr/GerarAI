/**
 * Guard F183: un informe fiscal calculado al vuelo (`persisted=false`,
 * `generated_at=null`) no puede dejar la fila «Generado» vacía sin
 * explicación: la UI declara «Informe calculado al vuelo, aún no guardado».
 * Ejecución: node --experimental-strip-types --test scripts/taxes-on-the-fly-note-guard.test.ts
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

// @ts-expect-error TS5097: la extensión explícita la exige node --experimental-strip-types.
import { onTheFlyReportNote, ON_THE_FLY_REPORT_NOTE } from '../lib/taxes/report-note.ts';

void test('la nota solo aparece con persisted=false y sin generated_at', () => {
    assert.equal(onTheFlyReportNote({ persisted: false, generated_at: null }), ON_THE_FLY_REPORT_NOTE);
    assert.equal(onTheFlyReportNote({ persisted: false }), ON_THE_FLY_REPORT_NOTE);
    // Persistido: jamás nota.
    assert.equal(onTheFlyReportNote({ persisted: true, generated_at: '2026-09-24T22:20:00Z' }), null);
    assert.equal(onTheFlyReportNote({ persisted: true }), null);
    // generated_at presente gana: el informe está guardado aunque el flag diga otra cosa.
    assert.equal(onTheFlyReportNote({ persisted: false, generated_at: '2026-09-24T22:20:00Z' }), null);
    // Sin declarar persistencia no se afirma nada.
    assert.equal(onTheFlyReportNote({}), null);
    assert.equal(onTheFlyReportNote(null), null);
});

void test('la vista pinta la nota en la fila «Generado»', () => {
    const view: string = readFileSync(new URL('../components/taxes/TaxesView.tsx', import.meta.url), 'utf8');
    // Las etiquetas visibles viven en el diccionario i18n (carril C); la
    // vista las referencia por clave. El guard verifica ambos extremos.
    const esTaxes = JSON.parse(readFileSync(new URL('../lib/i18n/messages/es/taxes.json', import.meta.url), 'utf8'));
    assert.match(view, /onTheFlyReportNote\(raw\)/);
    assert.match(view, /humanized\[i18n\.t\('taxes\.labels\.generatedAt'\)\] = onTheFly/);
    assert.equal(esTaxes.values.onTheFlyNote, ON_THE_FLY_REPORT_NOTE);
    assert.equal(esTaxes.labels.generatedAt, 'Generado');
});

console.log('taxes-on-the-fly-note-guard: ok');
