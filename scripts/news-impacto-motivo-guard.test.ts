import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const flow = readFileSync('components/research/NewsEventsFlow.tsx', 'utf8');
const labels = readFileSync('lib/labels.ts', 'utf8');

test('la etiqueta de impacto muestra el motivo en una linea junto a buena/mala/neutra', () => {
  // El badge acepta el tipo de evento y lo pinta tras el impacto.
  assert.match(flow, /export function ImpactBadge\(\{\s*direction,\s*eventType,\s*t = createTranslator\('es'\),\s*\}/);
  assert.match(flow, /etiquetaTipoEvento\(eventType\)/);
  assert.match(flow, /\{etiquetaDireccionImpacto\(direction\)\}\s*\{motivo \? ` · \$\{motivo\}` : ''\}/);
});

test('el motivo sale del tipo de evento real, nunca inventado, y omite lo no informativo', () => {
  assert.match(flow, /eventType !== 'general_news' && eventType !== 'unknown'/);
  // El catalogo de tipos existe y es el que traduce el motivo.
  assert.match(labels, /dilution: 'Dilución'/);
  assert.match(labels, /general_news: 'Noticia general'/);
});

test('las dos filas (tarjeta movil y tabla md) pasan el tipo de evento al badge', () => {
  const calls = flow.match(/<ImpactBadge direction=\{event\.impact_direction\} eventType=\{event\.event_type\} t=\{t\} \/>/g) ?? [];
  assert.equal(calls.length, 2);
});
