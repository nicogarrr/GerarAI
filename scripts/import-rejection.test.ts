import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
// @ts-expect-error Node strip-types requires the explicit TS extension.
import { importRejection } from '../lib/portfolio/import-rejection.ts';

class Http extends Error {
  statusCode: number;
  constructor(message: string, statusCode: number) { super(message); this.statusCode = statusCode; }
}

test('un 400 del backend se devuelve con su motivo en vez de lanzarse', () => {
  const result = importRejection(new Http('El CSV no tiene la columna action.', 400));
  assert.equal(result?.status, 'rejected');
  assert.equal(result?.message, 'El CSV no tiene la columna action.');
});

test('los 5xx y los errores sin motivo siguen lanzándose', () => {
  assert.equal(importRejection(new Http('boom', 500)), null);
  assert.equal(importRejection(new Http('400 Bad Request', 400)), null);
  assert.equal(importRejection(new Error('sin status')), null);
  assert.equal(importRejection('texto'), null);
});

test('las tres acciones de importación y el botón usan el rechazo', () => {
  const actions = readFileSync('lib/actions/portfolio.actions.ts', 'utf8');
  assert.equal(actions.match(/importRejection\(/g)?.length, 3);
  const button = readFileSync('components/portfolio/ImportIBKRButton.tsx', 'utf8');
  assert.match(button, /result\.message/);
});
