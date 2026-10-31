import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

// Perf (31-oct-2026, medido en prod a 390px): /calendar tardaba 6,6 s de LCP
// porque la página entera esperaba a getCatalystCalendar antes de pintar.
const src = readFileSync('app/(root)/calendar/page.tsx', 'utf8');

test('una sola petición compartida por cabecera y lista (promesa sin await en la página)', () => {
  assert.match(src, /const calendarPromise = getCatalystCalendar\(\);/);
  const page = src.slice(src.indexOf('export default async function CalendarPage'));
  assert.ok(!page.includes('await getCatalystCalendar('), 'la página no espera el fetch');
  assert.match(src, /calendar = await calendarPromise;/);
});

test('cabecera y lista van en Suspense con skeleton', () => {
  assert.ok(src.indexOf('<PageHeader') < src.indexOf('<Suspense fallback'), 'PageHeader antes del primer Suspense de datos');
  assert.match(src, /<Suspense fallback=\{<CalendarListSkeleton \/>\}>/);
  assert.match(src, /<Suspense fallback=\{<Skeleton className="h-4 w-72 max-w-full" \/>\}>/);
});
