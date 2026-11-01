import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

// El copy vive en es/ownership.json: solo se añade la sección de la página.
const page = readFileSync('app/(root)/ownership/page.tsx', 'utf8')
    + JSON.stringify(JSON.parse(readFileSync('lib/i18n/messages/es/ownership.json', 'utf8')).page);

test('F327: la vista /ownership no pierde tildes en su copy', () => {
    assert.doesNotMatch(page, /nueva posicion/);
    assert.doesNotMatch(page, /se declaro\)/);
    assert.doesNotMatch(page, /su ultimo informe/);
    assert.doesNotMatch(page, /gestor aun no/);
    assert.match(page, /nueva posición/);
    assert.match(page, /se declaró\)/);
    // #1440: el estado vacío trae el botón real, no copy que lo anunciaba.
    assert.match(page, /el último informe declarado ante la SEC/);
    assert.match(page, /label=\{t\('ownership\.page\.sync'\)\}/);
    assert.match(page, /"sync":"Sincronizar 13F"/);
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
