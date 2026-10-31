import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

// El selector de ticker de la guía no puede volver a ser un input suelto en
// la cabecera del Cerebro: parece una herramienta de desarrollo. Se abre
// desde un botón "Guía" y se mantiene visible mientras haya ticker activo.
test('el ticker de la guía se pliega tras un botón y conserva su aria-label', () => {
  const brain = readFileSync('components/brain/GlobalBrain.tsx', 'utf8') + '\n' + readFileSync('components/brain/GlobalBrainPanel.tsx', 'utf8');
  assert.ok(brain.includes('showGuideInput || guideTicker'));
  assert.ok(brain.includes('aria-label={t(\'brain.panel.guideButtonAria\')}'));
  assert.ok(brain.includes('ariaLabel={t(\'brain.panel.tickerAria\')}'));
  assert.ok(brain.includes('setShowGuideInput(false)'));
  assert.ok(brain.includes("{t('brain.panel.guideButton')}"));
  const dict = JSON.parse(readFileSync('lib/i18n/messages/es/brain.json', 'utf8'));
  assert.equal(dict.panel.guideButtonAria, 'Abrir la guía de investigación por empresa');
  assert.equal(dict.panel.tickerAria, 'Ticker de la guía de investigación');
  assert.equal(dict.panel.guideButton, 'Guía');
});
