/** Inversores PR 2: "Más compradas" sin tickers inventados, con fuente y estado sin datos. */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

// Movidas a vistas de /ownership (Movimientos 13F) por decision de Nico, WhatsApp 2026-10-20 00:59.
// El texto vive en es/ownership.json: solo se añade la sección de Más compradas.
const page = readFileSync('app/(root)/ownership/_components/MostBought.tsx', 'utf8')
    + JSON.stringify(JSON.parse(readFileSync('lib/i18n/messages/es/ownership.json', 'utf8')).mostBought);
const grid = readFileSync('app/(root)/inversores/_components/HubNav.tsx', 'utf8');

test('Más compradas dice "Sin datos todavía" cuando no hay dos trimestres', () => {
    assert.match(page, /Sin datos todavía/);
});

test('cita la fuente SEC 13F, el retardo de 45 días y que no hay ticker', () => {
    assert.match(page, /SEC, Form 13F \(EDGAR\)/);
    assert.match(page, /45 días/);
    assert.match(page, /no trae ticker/);
});

test('no muestra tickers ni multiplica por mil a ciegas', () => {
    assert.ok(!/\.ticker|\.symbol/.test(page));
    assert.ok(!/\* 1000/.test(page));
});

test('la barra del hub enlaza a Movimientos 13F (/ownership)', () => {
    assert.match(grid, /\/ownership/);
});
