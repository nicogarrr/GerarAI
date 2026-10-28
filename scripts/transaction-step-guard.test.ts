/**
 * F389: step="0.01" bloquea editar operaciones importadas con cantidades o
 * precios fraccionarios (0.1234) aunque solo se cambie la nota.
 * Ejecución: node --experimental-strip-types --test scripts/transaction-step-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const source = (p: string): string => readFileSync(join(root, p), 'utf8');

describe('formularios de operaciones aceptan decimales', () => {
    for (const file of [
        'components/portfolio/EditTransactionDialog.tsx',
        'components/portfolio/AddTransactionButton.tsx',
    ]) {
        it(`${file} no restringe cantidad/precio a 2 decimales`, () => {
            const text = source(file);
            assert.ok(!text.includes('step="0.01"'));
            for (const field of ['quantity', 'price']) {
                const input = text.match(new RegExp(`<Input[^>]*id="${field}"[^>]*>`, 's'))?.[0];
                assert.ok(input, `${field} input exists`);
                assert.match(input, /type="text"/, `${field} must avoid browser number rounding`);
                assert.match(input, /inputMode="decimal"/, `${field} keeps decimal keyboard`);
                assert.ok(!input.includes('step='), `${field} has no precision restriction`);
            }
            assert.match(text, /parseLocalizedNumber/);
        });
    }
});
