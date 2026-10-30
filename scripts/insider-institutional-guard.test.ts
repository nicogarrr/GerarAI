/**
 * «Grandes compras» mezcla insiders personales con filtros institucionales
 * (Berkshire Hathaway Inc, fondos, accionistas 10 %): la sección aclara que
 * las institucionales llevan etiqueta y SignalLine la pinta vía
 * isInstitutionalInsiderName.
 * Ejecución: node --experimental-strip-types --test scripts/insider-institutional-guard.test.ts
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
// @ts-expect-error TS5097: la extension explicita la exige node --experimental-strip-types.
import { isInstitutionalInsiderName } from '../lib/insider/format.ts';

const here = dirname(fileURLToPath(import.meta.url));
const source = (rel: string) => readFileSync(join(here, '..', rel), 'utf8');

void test('la sección explica la mezcla y el componente etiqueta', () => {
    const feed = source('components/insider/InsiderFeed.tsx');
    // Las cadenas visibles viven en el diccionario i18n (carril C); el
    // componente las referencia por clave. El guard verifica ambos extremos.
    const esFeed = JSON.parse(source('lib/i18n/messages/es/insider.json')).feed;
    assert.ok(feed.includes('insider.feed.institutional'), 'referencia al badge Institucional');
    assert.equal(esFeed.institutional, 'Institucional');
    assert.ok(feed.includes('isInstitutionalInsiderName'), 'usa el detector');
    assert.ok(feed.includes('insider.feed.bigBuysNote'), 'referencia a la nota aclaratoria');
    assert.ok(esFeed.bigBuysNote.includes('no insiders personales'), 'nota aclaratoria');
});

void test('detecta entidades y no personas', () => {
    assert.equal(isInstitutionalInsiderName('Berkshire Hathaway Inc / Buffett Warren E'), true);
    assert.equal(isInstitutionalInsiderName('VANGUARD GROUP INC'), true);
    assert.equal(isInstitutionalInsiderName('Cook Timothy D'), false);
    assert.equal(isInstitutionalInsiderName(null), false);
});
