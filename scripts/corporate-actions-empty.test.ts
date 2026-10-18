import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
// @ts-expect-error Node strip-types requires explicit extension.
import { corporateActionsEmptyMessage } from '../lib/research/corporate-actions-empty.ts';

test('sin importaciones no dice que todo esté al día', () => {
    const text = corporateActionsEmptyMessage({ dividends_last_import: null, splits_last_import: null });
    assert.match(text, /todavía no se ha importado/);
    assert.doesNotMatch(text, /al día/i);
});

test('con importaciones da la fecha de la última', () => {
    const text = corporateActionsEmptyMessage({ dividends_last_import: '2026-10-10T06:20:00Z', splits_last_import: '2026-10-15T06:20:00Z' });
    assert.match(text, /Última importación de datos: 15\/10\/2026/);
});

test('sin estado de fuentes tampoco afirma nada', () => {
    assert.match(corporateActionsEmptyMessage(null), /sin estado de las fuentes/i);
});

test('la vista ya no trae el «Todo al día» fijo', () => {
    assert.doesNotMatch(readFileSync('components/corporate-actions/CorporateActionsView.tsx', 'utf8'), /Todo al día/);
});
