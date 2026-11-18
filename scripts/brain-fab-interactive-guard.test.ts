import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

test('mobile access is in its reserved navigation row, not over page controls', () => {
  const brain = readFileSync('components/brain/GlobalBrain.tsx', 'utf8') + '\n' + readFileSync('components/brain/GlobalBrainPanel.tsx', 'utf8');
  const nav = readFileSync('components/layout/BottomNav.tsx', 'utf8');
  // #1848: la burbuja es ahora un envoltorio (boton + pista "Pregunta al
  // Cerebro"), asi que el literal cambia de orden pero NO de significado:
  // sigue oculta en movil (hidden), fija y visible desde md (fixed + md:flex).
  // #5953: decorative wrapper lets clicks reach page controls underneath;
  // only the actual Brain button restores hit testing. Check tokens on the
  // same wrapper instead of requiring adjacent class names.
  const wrapper = brain.match(/<div className="([^"]*\bgroup\b[^"]*)"/)?.[1];
  assert.ok(wrapper, 'desktop Brain wrapper must exist');
  const classes = new Set(wrapper.split(/\s+/));
  for (const token of ['group', 'fixed', 'hidden', 'items-center', 'gap-2', 'md:flex', 'pointer-events-none']) {
    assert.ok(classes.has(token), `desktop Brain wrapper must retain ${token}`);
  }
  const trigger = brain.match(/<Button\b[^>]*onClick=\{\(\) => setIsOpen\(true\)\}[\s\S]*?className="([^"]+)"/);
  assert.ok(trigger, 'Brain opening button must exist');
  assert.ok(trigger[1].split(/\s+/).includes('pointer-events-auto'), 'Brain button must stay clickable');
  assert.ok(!brain.includes('group-hover:pointer-events-auto'), 'decorative hint must not capture hover clicks');
  assert.ok(!brain.includes('group-focus-within:pointer-events-auto'), 'decorative hint must not capture focus clicks');
  assert.ok(!brain.includes('fabHidden'));
  assert.ok(!brain.includes('translate-y-24'));
  // #1805: el Cerebro es una celda más de la rejilla (6 columnas), ya no una
  // franja apilada encima de la barra; sigue en la fila de navegación.
  assert.equal(JSON.parse(readFileSync('lib/i18n/messages/es/brain.json', 'utf8')).name, 'Cerebro');
  assert.ok(nav.includes('grid-cols-6'));
  assert.ok(nav.includes("{t('brain.name')}"));
  assert.ok(nav.indexOf('<ul') < nav.indexOf("{t('brain.name')}"));
  assert.ok(nav.includes("onClick={() => openBrain()}"));
  assert.ok(nav.includes("from '@/lib/brain/open-brain'"));
  assert.ok(!nav.includes('dispatchEvent'));
});
