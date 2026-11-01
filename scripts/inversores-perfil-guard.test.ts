/** Inversores sin 13F: la ficha publica muestra cada cifra con fuente, fecha y tipo; "Sin datos" solo por bloque. */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
const ES_INVESTORS_JSON = readFileSync('lib/i18n/messages/es/investors.json', 'utf8');

const section = readFileSync('app/(root)/inversores/_components/PublicProfile.tsx', 'utf8');
const ficha = readFileSync('app/(root)/inversores/[slug]/page.tsx', 'utf8');
const actions = readFileSync('lib/actions/investors.actions.ts', 'utf8');

test('el tipo de hecho exige fuente, fecha y tipo', () => {
    assert.match(actions, /as_of: string;\s+source_url: string;\s+kind: 'oficial' \| 'inferido' \| 'prensa';/);
});

test('cada cifra se muestra con tipo y fecha (el enlace de fuente se retiro en #3527)', () => {
    assert.match(section, /fact\.kind === 'oficial'/);
    assert.match(section, /fact\.as_of/);
});

test('la cartera sin datos explica el motivo', () => {
    assert.match(section, /profile\.holdings_note/);
});

test('la ficha usa el perfil publico y conserva "Sin datos" cuando no hay', () => {
    assert.match(ficha, /investor\.public_profile \?/);
    assert.match(ficha, /<PublicProfileSection profile=\{investor\.public_profile\} \/>/);
    assert.match(ficha, /<Portfolio/);
    assert.match(readFileSync('app/(root)/inversores/_components/Portfolio.tsx', 'utf8'), /SIN_DATOS/);
});

test('la rejilla distingue ficha publica de sin datos', () => {
    const list = (readFileSync('app/(root)/inversores/page.tsx', 'utf8') + ES_INVESTORS_JSON);
    assert.match(list, /investor\.has_public_profile/);
    assert.match(list, /Participaciones públicas · ver ficha/);
});
