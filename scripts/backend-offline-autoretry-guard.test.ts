/**
 * El estado «motor desconectado» solo tenía un Reintentar manual: durante un
 * restart del backend (ventana de 10-20 s) la pantalla no se recuperaba sola.
 * Ahora BackendOffline monta BackendOfflineAutoRetry, que repite el render en
 * servidor con esperas crecientes (5/10/20/40 s) y se desmonta al recuperarse.
 *
 * Ejecucion: node --experimental-strip-types --test scripts/backend-offline-autoretry-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const offline = readFileSync('components/system/BackendOffline.tsx', 'utf8');
const retry = readFileSync('components/system/BackendOfflineAutoRetry.tsx', 'utf8');

describe('backend offline auto-retry guard', () => {
  it('BackendOffline monta el reintento automático', () => {
    assert.match(offline, /import \{ BackendOfflineAutoRetry \} from '@\/components\/system\/BackendOfflineAutoRetry';/);
    assert.match(offline, /<BackendOfflineAutoRetry \/>/);
  });

  it('el reintento es automático, acotado y con espera creciente', () => {
    assert.match(retry, /'use client';/);
    assert.match(retry, /RETRY_DELAYS_MS = \[5000, 10000, 20000, 40000\]/);
    assert.match(retry, /router\.refresh\(\)/);
    assert.match(retry, /attempt >= RETRY_DELAYS_MS\.length/);
  });
});
