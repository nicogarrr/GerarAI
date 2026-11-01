import assert from 'node:assert/strict';
import { test } from 'node:test';
// @ts-expect-error TS5097: node strip-types requires the extension.
import { readTransactions } from '../e2e/user-flows/transactions.ts';

test('ledger helper follows every page instead of treating an envelope as empty', async () => {
  const calls: string[] = [];
  const rows = await readTransactions(async (_method, path) => {
    calls.push(path);
    return { status: 200, json: { items: [{ id: calls.length }], total: 2 } };
  });
  assert.deepEqual(rows.map(row => row.id), [1, 2]);
  assert.deepEqual(calls, ['/api/portfolio/transactions?page=1&page_size=200', '/api/portfolio/transactions?page=2&page_size=200']);
});

test('empty page is valid only when total is zero', async () => {
  assert.deepEqual(await readTransactions(async () => ({ status: 200, json: { items: [], total: 0 } })), []);
  await assert.rejects(readTransactions(async () => ({ status: 200, json: { items: [], total: 1 } })), /Incomplete/);
});

test('auth failures and obsolete array contracts fail closed, not as an empty portfolio', async () => {
  await assert.rejects(readTransactions(async () => ({ status: 403, json: { detail: 'denied' } })), /403/);
  await assert.rejects(readTransactions(async () => ({ status: 200, json: [] })), /Invalid/);
});
