import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

test('Inicio formatea precios de acciones igual que la watchlist y la ficha (formatPrice)', () => {
    const src = readFileSync('components/PersonalizedOverview.tsx', 'utf8');
    assert.match(src, /formatPrice\(stock\.price, stock\.currency\)/);
    assert.match(src, /formatPrice\(op\.price, op\.currency\)/);
    assert.doesNotMatch(src, /formatMoney\(stock\.price/);
});

test('el bloqueo del 720 por datos del declarante enlaza a /settings', () => {
    const src = readFileSync('components/taxes/FilingSections.tsx', 'utf8');
    // El texto visible vive en el diccionario i18n (carril C); el componente
    // lo referencia por clave. El guard verifica ambos extremos.
    const esTaxes = JSON.parse(readFileSync('lib/i18n/messages/es/taxes.json', 'utf8'));
    assert.match(src, /href="\/settings"/);
    assert.match(src, /taxes\.modelo720\.completeData/);
    assert.equal(esTaxes.modelo720.completeData, 'Completar datos fiscales');
});
