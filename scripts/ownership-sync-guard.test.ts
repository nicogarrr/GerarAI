import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
const ES_INVESTORS_JSON = readFileSync('lib/i18n/messages/es/investors.json', 'utf8');

test('ownership: el estado «Sin datos 13F» tiene el botón que el texto anunciaba', () => {
  const page = readFileSync('app/(root)/ownership/page.tsx', 'utf8');
  assert.ok(page.includes('SyncPortfoliosButton'), 'la página reutiliza SyncPortfoliosButton (sin componente cliente nuevo)');
  assert.ok(!page.includes('Pulsa &quot;Sincronizar 13F&quot;'), 'no queda la instrucción sin botón');

  const button = (readFileSync('app/(root)/inversores/_components/SyncPortfoliosButton.tsx', 'utf8') + ES_INVESTORS_JSON);
  assert.ok(page.includes('label="Sincronizar 13F"'), 'la etiqueta coincide con lo que el estado anunciaba');
  assert.ok(button.includes("label ?? t('investors.sync.label')"), 'etiqueta por defecto conservada');
  assert.ok(button.includes('"label": "Sincronizar carteras ahora"'), 'etiqueta por defecto conservada (diccionario)');
  assert.ok(!button.includes('bg-teal-600'), 'sin override de primario: usa el Button por defecto');
  assert.ok(button.includes('syncInvestorPortfoliosNow'), 'encola el actor existente, no reimplementa la descarga');
});

test('13F: el primer uso sin datos encola la sincronizacion sola, como mucho una vez cada 6 h', () => {
  const button = (readFileSync('app/(root)/inversores/_components/SyncPortfoliosButton.tsx', 'utf8') + ES_INVESTORS_JSON);
  assert.ok(button.includes('useEffect'), 'se dispara al montar el estado vacío');
  assert.ok(button.includes('sync-13f-last-auto'), 'marca del último intento automático');
  assert.ok(button.includes('6 * 60 * 60 * 1000'), 'intervalo mínimo de 6 h entre intentos automáticos');
  assert.ok(button.includes('syncInvestorPortfoliosNow'), 'reutiliza el actor existente');
});
