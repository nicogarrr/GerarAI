/**
 * Solicitud de acceso: validacion, huella de IP, destino y credencial SMTP.
 * Ejecucion: node --experimental-strip-types --test scripts/access-request.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
// @ts-expect-error TS5097: la extension explicita la exige node --experimental-strip-types.
import { ACCESS_REQUEST_LIMITS, buildNotification, notifyTarget, parseAccessRequest, smtpConfig } from '../lib/access-request.ts';
// @ts-expect-error TS5097: la extension explicita la exige node --experimental-strip-types.
import { clientIp, hashIp } from '../lib/access-request-ip.ts';

describe('parseAccessRequest', () => {
  it('normaliza nombre y email', () => {
    const r = parseAccessRequest({ name: '  Ana   Pérez ', email: ' ANA@Ejemplo.COM ', note: ' hola ' });
    assert.deepEqual(r, { ok: true, value: { name: 'Ana Pérez', email: 'ana@ejemplo.com', note: 'hola' } });
  });

  it('rechaza nombre corto, email invalido y nota larga, con el campo', () => {
    const bad = (o: object) => parseAccessRequest(o) as { ok: false; reason: string; field?: string };
    assert.equal(bad({ name: 'A', email: 'a@b.co' }).field, 'name');
    assert.equal(bad({ name: 'Ana', email: 'sin-arroba' }).field, 'email');
    assert.equal(bad({ name: 'Ana', email: 'a@b' }).field, 'email');
    assert.equal(bad({ name: 'Ana', email: 'a@b.co', note: 'x'.repeat(ACCESS_REQUEST_LIMITS.noteMax + 1) }).field, 'note');
  });

  it('el campo trampa relleno es spam, y valores no string no rompen', () => {
    assert.deepEqual(parseAccessRequest({ name: 'Ana', email: 'a@b.co', honeypot: 'http://spam' }), { ok: false, reason: 'spam' });
    assert.equal(parseAccessRequest({ name: 5, email: null }).ok, false);
    assert.equal(parseAccessRequest(null).ok, false);
  });
});

describe('hashIp / clientIp', () => {
  it('misma IP y sal dan la misma huella; la IP no aparece en claro', () => {
    const h = hashIp('203.0.113.9', 's');
    assert.equal(h, hashIp(' 203.0.113.9 ', 's'));
    assert.notEqual(h, hashIp('203.0.113.9', 'otra'));
    assert.ok(!h.includes('203'));
    assert.equal(h.length, 32);
  });

  it('prefiere x-real-ip, luego la ultima IP de x-forwarded-for, o unknown', () => {
    assert.equal(clientIp('1.1.1.1, 2.2.2.2'), '2.2.2.2');
    assert.equal(clientIp('9.9.9.9, 2.2.2.2', '4.4.4.4'), '4.4.4.4');
    assert.equal(clientIp('', '3.3.3.3'), '3.3.3.3');
    assert.equal(clientIp(null, null), 'unknown');
  });
});

describe('destino y credencial', () => {
  it('notifyTarget solo acepta un email valido', () => {
    assert.equal(notifyTarget({ ACCESS_REQUEST_NOTIFY_EMAIL: ' yo@ejemplo.com ' }), 'yo@ejemplo.com');
    assert.equal(notifyTarget({ ACCESS_REQUEST_NOTIFY_EMAIL: 'no-email' }), null);
    assert.equal(notifyTarget({}), null);
  });

  it('smtpConfig exige usuario y contrasena, quita espacios y usa Gmail por defecto', () => {
    assert.equal(smtpConfig({ SMTP_USER: 'u@gmail.com' }), null);
    assert.equal(smtpConfig({ SMTP_PASS: 'x' }), null);
    assert.deepEqual(smtpConfig({ SMTP_USER: 'u@gmail.com', SMTP_PASS: 'abcd efgh ijkl mnop' }), {
      host: 'smtp.gmail.com', port: 465, user: 'u@gmail.com', pass: 'abcdefghijklmnop', from: 'u@gmail.com',
    });
    assert.equal(smtpConfig({ SMTP_USER: 'u', SMTP_PASS: 'p', SMTP_PORT: 'abc' })?.port, 465);
    assert.equal(smtpConfig({ SMTP_USER: 'u', SMTP_PASS: 'p', MAIL_FROM: 'GerarAI <a@b.co>' })?.from, 'GerarAI <a@b.co>');
  });
});

describe('buildNotification', () => {
  it('no deja saltos de linea del visitante en el asunto y declara que el registro sigue cerrado', () => {
    const n = buildNotification({ name: 'Ana\r\nBcc: x@y.z', email: 'a@b.co', note: '' }, 3);
    assert.ok(!/[\r\n]/.test(n.subject));
    assert.ok(n.text.includes('(sin nota)') && n.text.includes('total: 3') && n.text.includes('sigue cerrado'));
  });
});
