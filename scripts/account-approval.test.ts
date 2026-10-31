/**
 * Nucleo puro de la aprobacion de cuentas: tokens firmados de un solo uso,
 * caducidad, TTLs y regla de cuentas abuelas.
 * Ejecucion: node --experimental-strip-types --test scripts/account-approval.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import {
    approvalTokenTtlMs,
    adminListTokenTtlMs,
    createAdminListToken,
    createDecisionToken,
    isAccountActive,
    normalizeAccountStatus,
    signupAutoApprove,
    verifyAdminListToken,
    verifyDecisionToken,
    APPROVAL_TOKEN_TTL_DEFAULT_MS,
    ADMIN_LIST_TOKEN_TTL_DEFAULT_MS,
    // @ts-expect-error TS5097: la extension explicita la exige node --experimental-strip-types.
} from '../lib/auth/account-approval.ts';

const SECRET = 'test-secret-de-al-menos-32-caracteres';
const NOW = 1_800_000_000_000;

describe('estado de cuenta (abuelas aprobadas)', () => {
    it('campo ausente o desconocido = aprobada (cuentas anteriores a la funcion)', () => {
        assert.equal(isAccountActive(undefined), true);
        assert.equal(isAccountActive(null), true);
        assert.equal(isAccountActive('otra-cosa'), true);
        assert.equal(normalizeAccountStatus(undefined), null);
    });
    it('approved entra; pending y rejected no', () => {
        assert.equal(isAccountActive('approved'), true);
        assert.equal(isAccountActive('pending'), false);
        assert.equal(isAccountActive('rejected'), false);
    });
});

describe('token de decision (aprobar/rechazar)', () => {
    it('ida y vuelta: verifica lo que firma', () => {
        const token = createDecisionToken({ approvalId: '507f1f77bcf86cd799439011', action: 'approve', secret: SECRET, nowMs: NOW });
        assert.deepEqual(verifyDecisionToken(token, SECRET, NOW), {
            approvalId: '507f1f77bcf86cd799439011',
            action: 'approve',
            expires: Math.floor((NOW + APPROVAL_TOKEN_TTL_DEFAULT_MS) / 1000),
        });
    });
    it('la firma cubre la accion: approve no se convierte en reject', () => {
        const token = createDecisionToken({ approvalId: 'abc123', action: 'approve', secret: SECRET, nowMs: NOW });
        const tampered = token.replace('.approve.', '.reject.');
        assert.notEqual(tampered, token);
        assert.equal(verifyDecisionToken(tampered, SECRET, NOW), null);
    });
    it('la firma cubre la caducidad: alargarla invalida el token', () => {
        const token = createDecisionToken({ approvalId: 'abc123', action: 'approve', secret: SECRET, nowMs: NOW, ttlMs: 1000 });
        const parts = token.split('.');
        parts[2] = String(Number(parts[2]) + 999999);
        assert.equal(verifyDecisionToken(parts.join('.'), SECRET, NOW), null);
    });
    it('caducado, secreto distinto, malformado o vacio: null', () => {
        const token = createDecisionToken({ approvalId: 'abc123', action: 'reject', secret: SECRET, nowMs: NOW, ttlMs: 60_000 });
        assert.equal(verifyDecisionToken(token, SECRET, NOW + 120_000), null);
        assert.equal(verifyDecisionToken(token, 'otro-secreto', NOW), null);
        assert.equal(verifyDecisionToken('a.b.c', SECRET, NOW), null);
        assert.equal(verifyDecisionToken('', SECRET, NOW), null);
        assert.equal(verifyDecisionToken(null, SECRET, NOW), null);
        assert.equal(verifyDecisionToken(token, undefined, NOW), null);
    });
});

describe('token del listado admin', () => {
    it('ida y vuelta; caducidad y secreto se respetan', () => {
        const token = createAdminListToken({ secret: SECRET, nowMs: NOW });
        assert.equal(verifyAdminListToken(token, SECRET, NOW), true);
        assert.equal(verifyAdminListToken(token, SECRET, NOW + ADMIN_LIST_TOKEN_TTL_DEFAULT_MS + 1000), false);
        assert.equal(verifyAdminListToken(token, 'otro', NOW), false);
        assert.equal(verifyAdminListToken('x.y.z', SECRET, NOW), false);
        assert.equal(verifyAdminListToken(null, SECRET, NOW), false);
    });
    it('un token de decision NO abre el listado ni al reves', () => {
        const decision = createDecisionToken({ approvalId: 'abc123', action: 'approve', secret: SECRET, nowMs: NOW });
        const list = createAdminListToken({ secret: SECRET, nowMs: NOW });
        assert.equal(verifyAdminListToken(decision, SECRET, NOW), false);
        assert.equal(verifyDecisionToken(list, SECRET, NOW), null);
    });
});

describe('TTLs y flags de entorno', () => {
    it('TTLs por defecto y configurables por horas', () => {
        assert.equal(approvalTokenTtlMs({}), APPROVAL_TOKEN_TTL_DEFAULT_MS);
        assert.equal(adminListTokenTtlMs({}), ADMIN_LIST_TOKEN_TTL_DEFAULT_MS);
        assert.equal(approvalTokenTtlMs({ APPROVAL_TOKEN_TTL_HOURS: '48' }), 48 * 3_600_000);
        assert.equal(adminListTokenTtlMs({ ADMIN_LIST_TOKEN_TTL_HOURS: '24' }), 24 * 3_600_000);
    });
    it('TTL invalido o desorbitado cae al default', () => {
        assert.equal(approvalTokenTtlMs({ APPROVAL_TOKEN_TTL_HOURS: 'no-es-numero' }), APPROVAL_TOKEN_TTL_DEFAULT_MS);
        assert.equal(approvalTokenTtlMs({ APPROVAL_TOKEN_TTL_HOURS: '-5' }), APPROVAL_TOKEN_TTL_DEFAULT_MS);
        assert.equal(approvalTokenTtlMs({ APPROVAL_TOKEN_TTL_HOURS: '999999' }), APPROVAL_TOKEN_TTL_DEFAULT_MS);
    });
    it('SIGNUP_AUTO_APPROVE solo con valor explicito', () => {
        assert.equal(signupAutoApprove({}), false);
        assert.equal(signupAutoApprove({ SIGNUP_AUTO_APPROVE: 'true' }), true);
        assert.equal(signupAutoApprove({ SIGNUP_AUTO_APPROVE: '1' }), true);
        assert.equal(signupAutoApprove({ SIGNUP_AUTO_APPROVE: 'false' }), false);
    });
    it('SIGNUP_AUTO_APPROVE es IMPOSIBLE en produccion aunque la env este mal puesta', () => {
        assert.equal(signupAutoApprove({ NODE_ENV: 'production', SIGNUP_AUTO_APPROVE: 'true' }), false);
        assert.equal(signupAutoApprove({ NODE_ENV: 'production', SIGNUP_AUTO_APPROVE: '1' }), false);
        assert.equal(signupAutoApprove({ NODE_ENV: 'development', SIGNUP_AUTO_APPROVE: 'true' }), true);
    });
});
