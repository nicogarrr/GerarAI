/** Los campos email de InputField ofrecen el teclado móvil con @
 * (inputMode="email") SIN activar la validación nativa del navegador:
 * los mensajes de validación siguen siendo los de react-hook-form en ES.
 * Ejecución: node --experimental-strip-types --test scripts/email-inputmode-guard.test.ts
 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const src = readFileSync('components/forms/InputField.tsx', 'utf8');

test('InputField deriva inputMode="email" para campos email', () => {
    assert.match(src, /inputMode\s*=\s*\(type === 'email' \|\| name\.toLowerCase\(\) === 'email'\)/, 'derivación por type o name');
    assert.match(src, /inputMode=\{inputMode\}/, 'se pasa al input');
});

test('sin type="email" implícito: la validación nativa no sustituye a RHF', () => {
    // El tipo por defecto sigue siendo "text": inputMode cambia el teclado,
    // no la validación (pattern ES de react-hook-form).
    assert.match(src, /type\s*=\s*"text"/, 'default text intacto');
    assert.ok(!src.includes('type={type === \'email\''), 'no se eleva el tipo');
});
