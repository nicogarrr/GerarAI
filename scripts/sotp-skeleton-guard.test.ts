import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

// The streaming boundary must reserve space before SOTP data arrives.
const page = readFileSync('app/(root)/research/[ticker]/page.tsx', 'utf8');
const section = readFileSync('components/research/SotpBreakdownSkeleton.tsx', 'utf8');

test('el Suspense de SOTP reserva hueco con un skeleton (nunca null)', () => {
  assert.match(page, /<Suspense fallback=\{<SotpBreakdownSkeleton \/>\}><SotpBreakdownSection/);
});

test('el skeleton existe y espeja la estructura real (cabecera, nav, tabla)', () => {
  assert.match(section, /export function SotpBreakdownSkeleton\(\)/);
  const body = section.slice(section.indexOf('export function SotpBreakdownSkeleton'), section.lastIndexOf('}'));
  // Cabecera + nav de variantes + al menos 3 filas de partes: sin ellas el
  // hueco reservado vuelve a quedarse corto y el CLS reaparece.
  assert.ok((body.match(/animate-pulse|Skeleton/g) ?? []).length >= 6, 'skeleton demasiado corto para reservar la altura real');
});
