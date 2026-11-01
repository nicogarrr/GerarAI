/**
 * Guard del screener ad-hoc (/screeners): un envío con la condición
 * incompleta (sin métrica o sin valor) NO puede recargar la página en
 * silencio. Bug QA live 21-oct-2026: elegir solo un valor y pulsar
 * Ejecutar navegaba a ?left=&right=5 y la página volvía sin resultados
 * y sin ningún aviso (el input required de la métrica es readOnly, así
 * que la validación nativa no lo cubre).
 *
 * Ejecución: node --experimental-strip-types --test scripts/screeners-adhoc-incomplete-guard.test.ts
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const PAGE = 'app/(root)/screeners/page.tsx';

void test('un envío ad-hoc incompleto muestra un aviso role=alert junto al formulario', () => {
    const page = readFileSync(PAGE, 'utf8') + JSON.stringify(JSON.parse(readFileSync('lib/i18n/messages/es/screener.json', 'utf8')).screens);
    assert.match(page, /const attemptedRun = query\.left !== undefined \|\| query\.right !== undefined \|\| query\.ranking !== undefined;/, 'detecta el intento de ejecución por los parámetros de la URL');
    assert.match(page, /const incompleteRun = attemptedRun && \(!query\.left \|\| !query\.right\);/, 'incompleto = intento sin métrica o sin valor');
    assert.match(page, /result = incompleteRun \? null : await runAdHocScreen/, 'no consulta al backend con la condición incompleta');
    assert.match(page, /El filtro no se ejecutó: falta la métrica o el valor de la condición\. Complétalos y pulsa Ejecutar\./, 'aviso visible en español');
    assert.match(page, /\{incompleteRun \? \(\s*<p role="alert"/, 'el aviso es un role=alert junto al formulario');
});

void test('la carga limpia de /screeners no puede mostrar el aviso', () => {
    const page = readFileSync(PAGE, 'utf8') + JSON.stringify(JSON.parse(readFileSync('lib/i18n/messages/es/screener.json', 'utf8')).screens);
    // Sin parámetros en la URL, attemptedRun es false: el aviso depende
    // de que el usuario haya enviado el formulario, nunca aparece en la
    // primera pintada.
    assert.match(page, /attemptedRun && /, 'el aviso exige intento de ejecución');
});
