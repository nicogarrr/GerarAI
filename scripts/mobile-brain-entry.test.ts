import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

test('menú móvil ofrece Cerebro aunque el FAB esté oculto por solape', () => {
  const nav = readFileSync('components/MobileNav.tsx', 'utf8') + '\n' + readFileSync('components/MobileNavDrawer.tsx', 'utf8');
  const brain = readFileSync('components/brain/GlobalBrain.tsx', 'utf8') + '\n' + readFileSync('components/brain/GlobalBrainPanel.tsx', 'utf8');
  assert.ok(nav.includes('>Cerebro'));
  assert.ok(nav.includes("onClose(); window.dispatchEvent(new Event('gerarai:open-brain'))"));
  assert.ok(brain.includes("window.addEventListener('gerarai:open-brain', openFromNavigation)"));
  assert.ok(brain.includes("window.removeEventListener('gerarai:open-brain', openFromNavigation)"));
});


test('cartera reserva espacio inferior y etiqueta el periodo de análisis', () => {
  const layout = readFileSync('app/(root)/portfolio/layout.tsx', 'utf8');
  const page = readFileSync('app/(root)/portfolio/intelligence/page.tsx', 'utf8');
  assert.ok(layout.includes('pb-[calc(5rem+env(safe-area-inset-bottom))] md:pb-0'));
  // i18n: la etiqueta vive en messages/<locale>/portfolio.json.
  assert.ok(page.includes('portfolio.intelligence.yearsLabel'));
  const portfolioEs = JSON.parse(readFileSync('lib/i18n/messages/es/portfolio.json', 'utf8'));
  assert.equal(portfolioEs.intelligence.yearsLabel, 'Periodo de análisis (años)');
  assert.ok(page.includes('htmlFor="intelligence-years"'));
});
