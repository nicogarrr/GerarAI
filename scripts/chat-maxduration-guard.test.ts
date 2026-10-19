/**
 * El chat Cerebro (server action chatWithPortfolio) corre dentro de la pagina
 * donde esta el usuario y hereda su limite de Vercel (10 s por defecto en
 * Hobby). El backend tarda hasta 20 s en el peor caso medido (25-36 s antes),
 * asi que el layout (root), que monta GlobalBrain, debe declarar maxDuration
 * por encima del timeout del cliente del chat para degradar con mensaje y no
 * con "No se pudo completar la respuesta".
 *
 * Ejecucion: node --experimental-strip-types --test scripts/chat-maxduration-guard.test.ts
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const LAYOUT = readFileSync('app/(root)/layout.tsx', 'utf8');
const CLIENT = readFileSync('lib/research/client.ts', 'utf8');
const CHAT_MS = Number(/CHAT_MS:\s*([\d_]+)/.exec(CLIENT)?.[1]?.replace(/_/g, ''));

test('CHAT_MS se lee de lib/research/client.ts', () => {
  assert.ok(Number.isFinite(CHAT_MS) && CHAT_MS > 0);
});

test('el layout (root) declara maxDuration por encima del timeout del chat y dentro del tope Hobby', () => {
  const declared = Number(/export const maxDuration = (\d+);/.exec(LAYOUT)?.[1]);
  assert.ok(declared, 'falta export const maxDuration en app/(root)/layout.tsx');
  assert.ok(declared * 1000 >= CHAT_MS, `maxDuration (${declared}s) debe cubrir el timeout del chat (${CHAT_MS}ms)`);
  assert.ok(declared <= 60, 'el plan Hobby no admite mas de 60 s');
});
