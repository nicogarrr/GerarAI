import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';

test('snapshots explicitamente incluidos en tracing de /temas', () => {
  const config = readFileSync('next.config.ts', 'utf8');
  assert.match(config, /outputFileTracingIncludes:\s*\{\s*'\/temas':\s*\['\.\/data\/theme-fundamentals\/\*\.json'\]/);
  for (const name of ['nuclear', 'materiales']) {
    const file = `data/theme-fundamentals/${name}.json`;
    assert.ok(existsSync(file));
    const data = JSON.parse(readFileSync(file, 'utf8'));
    assert.ok(data.checkedAt && data.series.length);
    assert.ok(data.series.every((s: { source: string; vintage: string; published: string }) => s.source && s.vintage && s.published));
  }
});

test('los agregados no normalizan ni dibujan barras de paises', () => {
  const component = readFileSync('app/(root)/temas/_components/ThemeFundamentals.tsx', 'utf8');
  assert.ok(component.includes("s.rows.filter((row) => !row.label.startsWith('Otros países') && !row.label.startsWith('Total mundial'))"));
  assert.ok(component.includes("!r.label.startsWith('Otros países') && !r.label.startsWith('Total mundial')"));
});
