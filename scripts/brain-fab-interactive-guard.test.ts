import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

test('mobile access is in its reserved navigation row, not over page controls', () => {
  const brain = readFileSync('components/brain/GlobalBrain.tsx', 'utf8');
  const nav = readFileSync('components/layout/BottomNav.tsx', 'utf8');
  assert.ok(brain.includes('className="hidden md:flex fixed'));
  assert.ok(!brain.includes('fabHidden'));
  assert.ok(!brain.includes('translate-y-24'));
  assert.ok(nav.includes('grid-cols-5'));
  assert.ok(nav.indexOf('>Cerebro') < nav.indexOf('<ul'));
  assert.ok(nav.includes("new Event('gerarai:open-brain')"));
});
