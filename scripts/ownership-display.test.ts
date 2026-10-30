import assert from 'node:assert/strict';
import test from 'node:test';
// @ts-expect-error TS5097: node requires an explicit extension.
import { ownershipManagerName } from '../lib/ownership-display.ts';
test('display names use reviewed CIKs and preserve unknown official names', () => {
 assert.equal(ownershipManagerName('0001061768', 'BAUPOST GROUP LLC/MA'), 'Baupost Group');
 assert.equal(ownershipManagerName('0001376879', 'AKO CAPITAL LLP'), 'AKO Capital');
 assert.equal(ownershipManagerName('unknown', 'ABC LLC'), 'ABC LLC');
});
// @ts-expect-error TS5097: ejecución directa con Node.
import { ownershipLimitations } from '../lib/research/ownership-display.ts';

test('traduce los cuatro límites incluso cuando vienen concatenados', () => {
  const text = ownershipLimitations('Quarterly cadence with up to a 45-day reporting lag. Long-only US-listed positions; no shorts, no non-13F securities. Holdings as filed: CUSIP + issuer name; tickers never inferred. Amendments are separate immutable filings.');
  assert.ok(text.includes('45 días'));
  assert.ok(text.includes('sin cortos'));
  assert.ok(text.includes('nunca se infieren tickers'));
  assert.ok(text.includes('Las enmiendas son declaraciones inmutables independientes'));
  assert.ok(!text.includes('Quarterly'));
  assert.ok(!text.includes('no sustituyen'));
  assert.equal(ownershipLimitations('Nueva advertencia del proveedor'), 'Nueva advertencia del proveedor');
});

// @ts-expect-error TS5097: ejecución directa con Node.
import { holdingsVerificationNote } from '../lib/ownership-display.ts';

test('Auditoría A: un 13F sin verificar nunca se presenta como verificado', () => {
  assert.match(holdingsVerificationNote('mismatch') ?? '', /no cuadran/);
  assert.match(holdingsVerificationNote('unverified') ?? '', /sin verificar/);
  assert.match(holdingsVerificationNote('partial') ?? '', /parciales/);
  assert.equal(holdingsVerificationNote('ok'), null);
});

import { readdirSync, readFileSync } from 'node:fs';
import path from 'node:path';

test('ficha-4: ningún panel pinta las limitaciones del 13F en crudo (inglés)', () => {
  // La ficha (Gestores que la declaran) hacía holders.limitations.join(' ') y
  // mostraba «Quarterly cadence with up to a 45-day reporting lag…» en inglés.
  const raw: string[] = [];
  for (const root of ['app', 'components']) {
    for (const name of readdirSync(root, { recursive: true, encoding: 'utf8' })) {
      if (!name.endsWith('.tsx')) continue;
      const file = path.join(root, name);
      if (/\.limitations\.(join|map)\(/.test(readFileSync(file, 'utf8'))) raw.push(file);
    }
  }
  assert.deepEqual(raw, []);
  const page = readFileSync('app/(root)/research/[ticker]/page.tsx', 'utf8');
  assert.match(page, /ownershipLimitations\(holders\.limitations\)/);
});
