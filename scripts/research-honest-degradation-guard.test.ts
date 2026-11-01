/**
 * Guard de honestidad de la ficha de research (#D2a, fixes del auditor en #752).
 *
 * Tres cosas que el paralelismo no puede hacer por comodidad:
 *  1. Pintar un backend caido (503/timeout) como "empresa sin datos".
 *  2. Lanzar el POST del chat al LLM cuando la vista activa no es el chat.
 *  3. Pintar "Seguir" cuando el estado de la watchlist es desconocido.
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
// @ts-expect-error TS5097: la extensión explícita la exige node --experimental-strip-types.
import { settleResearchBatch } from '../lib/research/parallel-fetch.ts';

const PAGE = readFileSync('app/(root)/research/[ticker]/page.tsx', 'utf8');
const FOLLOW = readFileSync('components/screener/FollowButton.tsx', 'utf8');

describe('un fallo de la vista activa no se pinta como vacio', () => {
  it('el lote conserva el error original de una lectura rechazada', async () => {
    const boom = new Error('503 backend caido');
    const [result] = await settleResearchBatch([{ key: 'thesis', promise: Promise.reject(boom) }], 50);
    assert.equal(result.ok, false);
    assert.ok(!result.ok && result.error === boom, 'el error original sobrevive para relanzarlo');
  });

  it('un timeout queda como fallo, no como valor vacio', async () => {
    const never = new Promise<never>(() => undefined);
    const [result] = await settleResearchBatch([{ key: 'thesis', promise: never }], 10);
    assert.equal(result.ok, false);
    assert.ok(!result.ok && result.reason === 'timeout');
  });

  it('viewData relanza en vez de caer a EMPTY_VIEW_DATA', () => {
    const body = PAGE.slice(PAGE.indexOf('const viewData = async'), PAGE.indexOf('let headerMarket'));
    assert.match(body, /throw failed\.error instanceof Error/);
    assert.match(body, /Reintenta/);
  });
});

describe('la ficha no llama al motor de chat desde el servidor', () => {
  it('la pregunta vive en el Cerebro, no en un POST al renderizar la ficha', () => {
    assert.doesNotMatch(PAGE, /askResearchCompanyChat|chatPromise/);
  });
});

describe('watchlist desconocida no pinta "Seguir"', () => {
  it('la ficha pasa estado desconocido al boton', () => {
    assert.match(PAGE, /const watchlistUnknown = watchlist === null/);
    assert.match(PAGE, /stateUnknown=\{watchlistUnknown\}/);
  });
  it('el boton se deshabilita y no ofrece Seguir si el estado es desconocido', () => {
    assert.match(FOLLOW, /disabled=\{busy \|\| stateUnknown\}/);
    assert.match(FOLLOW, /stateUnknown \? t\('screener\.follow\.unavailable'\)/);
    // El texto vive en el diccionario (solo esa clave).
    const esFollow = JSON.parse(readFileSync('lib/i18n/messages/es/screener.json', 'utf8')).follow;
    assert.equal(esFollow.unavailable, 'Seguir (no disponible)');
  });
});
