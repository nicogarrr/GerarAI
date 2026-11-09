// hmacSignature/safeEqual compartidos (lib/auth/hmac.ts): account-approval y
// delete-reauth llevaban la misma cadena HMAC-SHA256 base64url y la misma
// comparacion en tiempo constante copiadas. Fija el contrato y que ninguno
// reintroduce su copia.
// Ejecucion: node --experimental-strip-types --test scripts/auth-hmac-shared.test.ts
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
// @ts-expect-error TS5097: node strip-types needs the source extension.
const { hmacSignature, safeEqual } = await import('../lib/auth/hmac.ts');

describe('hmacSignature', () => {
    it('es determinista y liga payload y secreto', () => {
        const a = hmacSignature('payload.opaco', 'secreto-1');
        assert.equal(a, hmacSignature('payload.opaco', 'secreto-1'));
        assert.notEqual(a, hmacSignature('payload.opaco', 'secreto-2'));
        assert.notEqual(a, hmacSignature('otro.payload', 'secreto-1'));
        assert.equal(a.includes('+'), false);
        assert.equal(a.includes('/'), false);
        assert.equal(a.includes('='), false);
    });
});

describe('safeEqual', () => {
    it('true solo con cadenas identicas; distinta longitud no lanza', () => {
        assert.equal(safeEqual('abc', 'abc'), true);
        assert.equal(safeEqual('abc', 'abd'), false);
        assert.equal(safeEqual('abc', 'abcd'), false);
        assert.equal(safeEqual('', ''), true);
    });
});

describe('sin copias locales', () => {
    it('account-approval y delete-reauth importan de ./hmac.ts', () => {
        for (const file of ['lib/auth/account-approval.ts', 'lib/auth/delete-reauth.ts']) {
            const src = readFileSync(file, 'utf-8');
            assert.equal(src.includes("from './hmac.ts'"), true, file);
            assert.equal(src.includes('node:crypto'), false, file);
        }
    });
});
