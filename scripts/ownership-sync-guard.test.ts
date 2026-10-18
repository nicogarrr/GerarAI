import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

test('ownership: el estado «Sin datos 13F» tiene el botón que el texto anunciaba', () => {
  const page = readFileSync('app/(root)/ownership/page.tsx', 'utf8');
  assert.ok(page.includes('SyncPortfoliosButton'), 'la página reutiliza SyncPortfoliosButton (sin componente cliente nuevo)');
  assert.ok(!page.includes('Pulsa &quot;Sincronizar 13F&quot;'), 'no queda la instrucción sin botón');

  const button = readFileSync('app/(root)/inversores/_components/SyncPortfoliosButton.tsx', 'utf8');
  assert.ok(page.includes('label="Sincronizar 13F"'), 'la etiqueta coincide con lo que el estado anunciaba');
  assert.ok(button.includes("label = 'Sincronizar carteras ahora'"), 'etiqueta por defecto conservada');
  assert.ok(button.includes('bg-teal-600 text-white'), 'botón teal con texto blanco legible');
  assert.ok(button.includes('syncInvestorPortfoliosNow'), 'encola el actor existente, no reimplementa la descarga');
});
