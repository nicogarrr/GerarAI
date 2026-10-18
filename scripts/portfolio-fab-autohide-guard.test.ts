import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

test('scroll and underlying page content cannot hide the mobile Cerebro entry', () => {
  const brain = readFileSync('components/brain/GlobalBrain.tsx', 'utf8');
  const nav = readFileSync('components/layout/BottomNav.tsx', 'utf8');
  const layout = readFileSync('app/(root)/layout.tsx', 'utf8');
  assert.ok(!brain.includes('fabScrollHidden'));
  assert.ok(!brain.includes('fabLegendBlocked'));
  assert.ok(!nav.includes('opacity-0'));
  assert.ok(nav.includes('min-h-11'));
  assert.ok(layout.includes('pb-[calc(7.5rem+env(safe-area-inset-bottom))]'));
});
