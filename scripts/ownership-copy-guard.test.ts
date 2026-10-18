import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const page = readFileSync('app/(root)/ownership/page.tsx', 'utf8');

test('F327: la vista /ownership no pierde tildes en su copy', () => {
    assert.doesNotMatch(page, /nueva posicion/);
    assert.doesNotMatch(page, /se declaro\)/);
    assert.doesNotMatch(page, /su ultimo informe/);
    assert.doesNotMatch(page, /gestor aun no/);
    assert.match(page, /nueva posición/);
    assert.match(page, /se declaró\)/);
    assert.match(page, /su último informe/);
    assert.match(page, /Pulsa &quot;Sincronizar 13F&quot;/);
});

test('F14: cabeceras y avisos de /ownership con tildes (límites, todavía, estará, próximo)', () => {
    assert.doesNotMatch(page, /Limites de este dato/);
    assert.doesNotMatch(page, /todavia/);
    assert.doesNotMatch(page, /estara disponible/);
    assert.doesNotMatch(page, /proximo trimestre/);
    assert.match(page, /Límites de este dato/);
    assert.match(page, /Sin datos 13F todavía/);
    assert.match(page, /estará disponible tras el próximo trimestre/);
});

test('F14b: "últimos informes" con tilde', () => {
    assert.doesNotMatch(page, /dos ultimos informes/);
    assert.match(page, /dos últimos informes/);
});
