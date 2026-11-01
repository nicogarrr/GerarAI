import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
// Los textos de Pro Picks viven en el diccionario es (i18n): se comprueban junto al código.
const ES_PROPICKS_JSON = readFileSync('lib/i18n/messages/es/propicks.json', 'utf8');

test('ProPicks mobile tablist wraps instead of clipping tabs mid-word', () => {
    // Tester 4 (2026-10-19): el scroll horizontal sin affordance cortaba
    // «Estrategia y rebalanc…». Nuevo contrato: las pestañas envuelven a dos
    // filas; ya no hay region con scroll, asi que tabIndex no aplica.
    const source = (readFileSync('components/proPicks/ProPicksTabs.tsx', 'utf8') + ES_PROPICKS_JSON);
    const list = source.match(/<TabsList[\s\S]*?<\/TabsList>/)?.[0];
    assert.ok(list);
    for (const token of ['w-full', 'min-w-0', 'max-w-full', 'justify-start', 'flex-wrap']) assert.ok(list.includes(token), token);
    assert.ok(!list.includes('w-max'));
    assert.ok(!list.includes('min-w-full'));
    assert.ok(!list.includes('overflow-x-auto'), 'sin scroll horizontal oculto');
    assert.ok(!list.includes('snap-x'), 'sin snap scroll');
    assert.ok(list.includes("t('propicks.tabs.paper')"));
    assert.ok(ES_PROPICKS_JSON.includes('"paper": "Resultados simulados de la IA"'));
});
