/**
 * Guard de keys de React: proveedores duplicados en /temas y las dos
 * secciones hijas del mismo ejercicio fiscal en Impuestos no pueden compartir
 * key (React reutilizaba nodos y podía perder/fusionar contenido).
 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import {
  flowSupplierKey,
  // @ts-expect-error Node strip-types exige la extensión explícita.
} from '../lib/market/flows.ts';
import {
  filingSectionKey,
  // @ts-expect-error Node strip-types exige la extensión explícita.
} from '../lib/taxes/section-keys.ts';

test('proveedor duplicado conserva una key única por posición', () => {
  const rtx = { ticker: 'RTX', name: 'RTX Corporation' };
  assert.notEqual(flowSupplierKey(rtx, 0), flowSupplierKey(rtx, 1));
  assert.equal(flowSupplierKey(rtx, 0), 'RTX::RTX Corporation::0');
  assert.equal(flowSupplierKey({ ticker: null, name: 'Proveedor sin ticker' }, 2), 'sin-ticker::Proveedor sin ticker::2');
});

test('ThemeFlow usa ticker + nombre + índice, no solo el ticker', () => {
  const source = readFileSync('app/(root)/temas/_components/ThemeFlow.tsx', 'utf8');
  assert.match(source, /flow\.suppliers\.map\(\(supplier, index\) =>/);
  assert.match(source, /key=\{flowSupplierKey\(supplier, index\)\}/);
  assert.doesNotMatch(source, /key=\{supplier\.ticker \?\? supplier\.name\}/);
});

test('las secciones fiscales hijas no comparten la key del año', () => {
  assert.equal(filingSectionKey('tme-preview', 2026), 'tme-preview-2026');
  assert.equal(filingSectionKey('sale-casillas', 2026), 'sale-casillas-2026');
  assert.notEqual(filingSectionKey('tme-preview', 2026), filingSectionKey('sale-casillas', 2026));

  const source = readFileSync('components/taxes/FilingSections.tsx', 'utf8');
  assert.match(source, /<TmePreviewForm key=\{filingSectionKey\('tme-preview', year\)\}/);
  assert.match(source, /<SaleCasillas key=\{filingSectionKey\('sale-casillas', year\)\}/);
  assert.doesNotMatch(source, /<TmePreviewForm key=\{year\}/);
  assert.doesNotMatch(source, /<SaleCasillas key=\{year\}/);
});
