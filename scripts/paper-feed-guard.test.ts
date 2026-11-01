import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

test('cartera simulada vacía ofrece generar propuestas (acción real, cuota declarada)', () => {
  const view = readFileSync('components/proPicks/PaperTradingView.tsx', 'utf8');
  assert.ok(view.includes('PaperFeedButton'), 'el estado vacío usa PaperFeedButton');
  // Textos en el diccionario (Ajustes → Idioma); el literal español no cambia.
  const esPaper = JSON.parse(readFileSync('lib/i18n/messages/es/propicks.json', 'utf8')).paper;
  assert.ok(view.includes("t('propicks.paper.generate')") && esPaper.generate === 'Generar propuestas simuladas');
  assert.ok(view.includes("t('propicks.paper.queued')") && esPaper.queued.startsWith('Generación en curso'), 'confirma que el lote quedó encolado');
  assert.ok(view.includes("t('propicks.paper.empty')") && esPaper.empty.startsWith('Sin propuestas del modelo registradas.'), 'la razón honesta se conserva');

  const actions = readFileSync('lib/actions/paper-trading.actions.ts', 'utf8');
  assert.ok(actions.includes("'/api/paper-trading/feed', { method: 'POST' }"), 'la acción encola el lote existente, no inventa propuestas');

  const route = readFileSync('data-engine/app/api/routes/paper_trading.py', 'utf8');
  assert.ok(route.includes('"/feed", status_code=202'), 'la ruta 202 existe en el backend');
});
