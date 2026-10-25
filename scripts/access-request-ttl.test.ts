/**
 * El TTL de access_requests es opt-in: Mongoose autoIndex lo aplicaria a los
 * documentos ya existentes. Ejecucion:
 *   node --experimental-strip-types --test scripts/access-request-ttl.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
// @ts-expect-error TS5097: la extension explicita la exige node --experimental-strip-types.
import { accessRequestTtlSeconds } from '../lib/access-request-retention.ts';

describe('access_requests TTL', () => {
  it('apagado por defecto, aunque haya ventana configurada', () => {
    assert.equal(accessRequestTtlSeconds({}), null);
    assert.equal(accessRequestTtlSeconds({ ACCESS_REQUEST_RETENTION_DAYS: '30' }), null);
    assert.equal(accessRequestTtlSeconds({ ACCESS_REQUEST_TTL_ENABLED: 'false' }), null);
  });

  it('solo con ACCESS_REQUEST_TTL_ENABLED=true devuelve la ventana pedida', () => {
    assert.equal(accessRequestTtlSeconds({ ACCESS_REQUEST_TTL_ENABLED: 'true', ACCESS_REQUEST_RETENTION_DAYS: '30' }), 30 * 86_400);
  });

  it('ventana invalida cae a 365 dias solo si esta activado', () => {
    for (const bad of ['abc', '0', '-5']) {
      assert.equal(accessRequestTtlSeconds({ ACCESS_REQUEST_TTL_ENABLED: 'true', ACCESS_REQUEST_RETENTION_DAYS: bad }), 365 * 86_400);
    }
  });
});
