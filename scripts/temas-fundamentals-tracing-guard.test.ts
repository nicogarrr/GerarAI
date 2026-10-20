import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';

test('snapshots explicitamente incluidos en tracing de /temas', () => {
  const config = readFileSync('next.config.ts', 'utf8');
  assert.match(config, /outputFileTracingIncludes:\s*\{\s*'\/temas':\s*\['\.\/data\/theme-fundamentals\/\*\.json'\]/);
  for (const name of ['nuclear', 'materiales', 'utilities']) {
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


test('Pink Sheet conserva fuente, proveedores, vintage y valores no reconstruidos', () => {
  for (const name of ['utilities', 'materiales']) {
    const data = JSON.parse(readFileSync(`data/theme-fundamentals/${name}.json`, 'utf8'));
    for (const s of data.series.filter((s: { monthly?: boolean }) => s.monthly)) {
      assert.equal(s.rows.length, 24);
      assert.equal(s.rows[0].label, '2026-09');
      assert.equal(s.vintage, '2026-10-02');
      assert.ok(s.attribution.startsWith('The World Bank: World Bank Commodity Price Data (The Pink Sheet): '));
      assert.ok(s.terms && s.providers && s.sourceDescription && s.sourceUnit);
      assert.ok(s.rows.every((r: { values: (number | null)[] }) => r.values.every(v => v === null || Number.isFinite(v))));
    }
  }
});
