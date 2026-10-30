/**
 * F181 + copy insider: vocabulario ES fijo. «compostadora» y «ingestar»
 * no son español; «Rhino» era un resto sin sentido en la explicacion de
 * senales insider (el backend dice CEO/CFO/«C-suite»).
 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import { loadMessages } from './i18n-messages.mjs';

const es = JSON.stringify(loadMessages('es').dict);
const knowledge = readFileSync('app/(root)/knowledge/page.tsx', 'utf8');
const insider = readFileSync('app/(root)/insider/page.tsx', 'utf8');

test('el vocabulario ES no recae en compostadora/ingestar/Rhino', () => {
    assert.doesNotMatch(es, /compostadora/i);
    assert.match(es, /compounders de calidad/);
    assert.doesNotMatch(knowledge, /ingestar/i);
    assert.doesNotMatch(insider, /Rhino/);
    // El backend clasifica c-suite como CEO o CFO (insider_service._is_c_suite
    // = _is_ceo OR _is_cfo): prometer «otro C-suite» insinuaria deteccion de
    // COO/CIO/CTO que no existe.
    assert.match(readFileSync('lib/insider/format.ts', 'utf8'), /CEO.*CFO/);
});
