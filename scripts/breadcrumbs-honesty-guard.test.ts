/**
 * Guarda de migas honestas (F141): un nivel intermedio que no es una ruta
 * real no puede renderizarse como enlace - el hash `#Seccion` no navega a
 * nada y el lector no puede saberlo hasta pulsar.
 * Ejecución: node --experimental-strip-types --test scripts/breadcrumbs-honesty-guard.test.ts
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
// La jerarquia vive en lib/nav/build-crumbs.ts (funcion pura); el componente
// solo presenta. Las guardas miran ambos.
const crumbs = readFileSync(join(here, '..', 'components/layout/Breadcrumbs.tsx'), 'utf8')
    + readFileSync(join(here, '..', 'lib/nav/build-crumbs.ts'), 'utf8');

void test('ninguna miga enlaza a un hash inerte', () => {
    assert.ok(!crumbs.includes('href: `#'), 'sin enlaces a hashes de seccion');
    assert.ok(!crumbs.includes("'#"), 'sin hrefs hash');
    assert.ok(crumbs.includes('href?: string'), 'href opcional: niveles sin ruta van como texto');
});

void test('las secciones del menu llevan tildes', () => {
    const constants = readFileSync(join(here, '..', 'lib/constants.ts'), 'utf8');
    assert.ok(!constants.includes("title: 'Senales'"), 'Señales con tilde');
    assert.ok(!constants.includes("title: 'Analisis'"), 'Análisis con tilde');
});
