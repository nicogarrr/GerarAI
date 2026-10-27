/**
 * Email de los formularios de acceso: acepta lo que acepta el servidor.
 * Ejecución: node --experimental-strip-types --test scripts/auth-email-validation.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
// @ts-expect-error TS5097: la extension explicita la exige node --experimental-strip-types.
import { EMAIL_PATTERN, emailFieldValidation, isValidEmail, normalizeEmailInput } from '../lib/validation/email.ts';

describe('isValidEmail', () => {
    it('acepta alias con + y apóstrofo, mayúsculas y subdominios', () => {
        for (const email of [
            'nico+gerarai@gmail.com',
            "o'neill@ejemplo.com",
            'Nico.Garcia@Example.COM',
            'qa_1-x@mail.ejemplo.co.uk',
        ]) {
            assert.equal(isValidEmail(email), true, email);
        }
    });

    it('recorta los espacios de los extremos antes de validar', () => {
        assert.equal(normalizeEmailInput('  nico@gmail.com \t'), 'nico@gmail.com');
        assert.equal(isValidEmail('nico@gmail.com '), true);
        assert.equal(isValidEmail(' nico+gerarai@gmail.com'), true);
    });

    it('sigue rechazando direcciones mal formadas', () => {
        for (const email of ['', 'sin-arroba', 'a@b', 'a@b.c', '.a@b.co', 'a..b@b.co', 'a b@b.co', 'a@-b.co', '<script>@x.co']) {
            assert.equal(isValidEmail(email), false, email);
        }
        assert.equal(isValidEmail(null), false);
        assert.equal(isValidEmail(42), false);
    });

    it('las opciones de register recortan y validan con el mismo patrón', () => {
        assert.equal(emailFieldValidation.setValueAs(' a@b.co '), 'a@b.co');
        assert.equal(emailFieldValidation.pattern.value, EMAIL_PATTERN);
    });
});

describe('formularios de acceso', () => {
    for (const file of ['components/forms/SignUpForm.tsx', 'components/forms/SignInForm.tsx']) {
        it(`${file} usa la validación compartida y no una regex propia`, () => {
            const source = readFileSync(file, 'utf8');
            assert.match(source, /emailFieldValidation/);
            assert.doesNotMatch(source, /\[\\w-\.\]\+@/);
        });
    }
});
