/**
 * Guardia de la tanda `ti` de i18nPageMetadata: alerts, calendario (4) y
 * macro-calendario llevaban el patron getT + { title, description } con la
 * variable `ti`; ahora llaman al helper de lib/i18n/metadata.ts.
 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const pages: Array<[string, string, string]> = [
  ['app/(root)/alerts/page.tsx', 'alerts.meta.title', 'alerts.meta.description'],
  ['app/(root)/calendar/page.tsx', 'calendar.meta.catalystsTitle', 'calendar.meta.catalystsDescription'],
  ['app/(root)/calendar/ipos/page.tsx', 'calendar.meta.iposTitle', 'calendar.meta.iposDescription'],
  ['app/(root)/calendar/resultados/page.tsx', 'calendar.meta.earningsTitle', 'calendar.meta.earningsDescription'],
  ['app/(root)/calendar/suscripcion/page.tsx', 'calendar.meta.subscriptionTitle', 'calendar.meta.subscriptionDescription'],
  ['app/(root)/macro-calendar/page.tsx', 'calendar.meta.macroTitle', 'calendar.meta.macroDescription'],
];

for (const [file, titleKey, descriptionKey] of pages) {
  test(file + ' usa el helper con sus claves', () => {
    const src = readFileSync(file, 'utf8');
    const start = src.indexOf('generateMetadata');
    assert.ok(start >= 0, 'generateMetadata ausente');
    const block = src.slice(start, start + 220);
    assert.ok(
      block.includes('return i18nPageMetadata(\'' + titleKey + '\', \'' + descriptionKey + '\');'),
      'la pagina no llama al helper con sus claves',
    );
    assert.ok(!block.includes('{ title: ti('), 'queda el objeto inline');
    assert.ok(src.includes("from '@/lib/i18n/metadata';"), 'falta el import del helper');
  });
}
