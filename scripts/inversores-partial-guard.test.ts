/** Inversores: cobertura PARTIAL del 13F visible (nunca se muestran cifras dudosas sin aviso). */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
const ES_INVESTORS_JSON = readFileSync('lib/i18n/messages/es/investors.json', 'utf8');

const ficha = readFileSync('app/(root)/inversores/_components/Portfolio.tsx', 'utf8');
// Carteras se fusiona en /inversores (decisión de Nico, 2026-10-20): la tarjeta con cobertura vive en el hub.
const carteras = (readFileSync('app/(root)/inversores/page.tsx', 'utf8') + ES_INVESTORS_JSON);
const actions = readFileSync('lib/actions/investors.actions.ts', 'utf8');

test('el tipo de inversor lleva coverage', () => {
    assert.match(actions, /coverage\?: string \| null/);
});

test('la ficha avisa de datos parciales cuando coverage es partial', () => {
    assert.match(ficha, /portfolio\.coverage === "partial"/);
    assert.match(ficha, /Datos parciales/);
});

test('la lista de inversores marca "Datos parciales" en la tarjeta', () => {
    assert.match(carteras, /investor\.coverage === 'partial'/);
    assert.match(carteras, /Datos parciales/);
});

// Movidas a vistas de /ownership (Movimientos 13F) por decision de Nico, WhatsApp 2026-10-20 00:59.
const masCompradas = readFileSync('app/(root)/ownership/_components/MostBought.tsx', 'utf8');

test('mas-compradas avisa de cuantos gestores comparados van parciales', () => {
    assert.match(actions, /managers_partial\?: number/);
    assert.match(masCompradas, /data\.managers_partial \?/);
    assert.match(masCompradas, /con datos parciales/);
});
