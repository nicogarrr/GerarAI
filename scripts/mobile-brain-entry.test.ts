import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

test('menú móvil ofrece Cerebro aunque el FAB esté oculto por solape', () => {
  const nav = readFileSync('components/MobileNav.tsx', 'utf8');
  const brain = readFileSync('components/brain/GlobalBrain.tsx', 'utf8');
  assert.ok(nav.includes('>Cerebro'));
  assert.ok(nav.includes("setOpen(false); window.dispatchEvent(new Event('gerarai:open-brain'))"));
  assert.ok(brain.includes("window.addEventListener('gerarai:open-brain', openFromNavigation)"));
  assert.ok(brain.includes("window.removeEventListener('gerarai:open-brain', openFromNavigation)"));
});
