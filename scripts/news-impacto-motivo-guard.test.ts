import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const flow = readFileSync('components/research/NewsEventsFlow.tsx', 'utf8');
const labels = readFileSync('lib/labels.ts', 'utf8');
const dict = JSON.parse(readFileSync('lib/i18n/messages/es/labels.json', 'utf8'));

test('la etiqueta de impacto muestra el motivo en una linea junto a buena/mala/neutra', () => {
  // El badge acepta el tipo de evento y lo pinta tras el impacto.
  assert.match(flow, /export function ImpactBadge\(\{\s*direction,\s*eventType,\s*t = createTranslator\('es'\),\s*locale = 'es',\s*\}/);
  assert.match(flow, /etiquetaTipoEvento\(eventType, locale\)/);
  assert.match(flow, /\{etiquetaDireccionImpacto\(direction, locale\)\}\s*\{motivo \? ` · \$\{motivo\}` : ''\}/);
});

test('el motivo sale del tipo de evento real, nunca inventado, y omite lo no informativo', () => {
  assert.match(flow, /eventType !== 'general_news' && eventType !== 'unknown'/);
  // El catalogo de tipos existe (en el diccionario, cruzado en labels.ts)
  // y es el que traduce el motivo.
  assert.match(labels, /EVENTO_CODES/);
  assert.match(labels, /byCode\(EVENTO_CODES, esLabels\.eventTypes\)/);
  assert.equal(dict.eventTypes.dilution, 'Dilución');
  assert.equal(dict.eventTypes.general_news, 'Noticia general');
});

test('las dos filas (tarjeta movil y tabla md) pasan el tipo de evento al badge', () => {
  const calls = flow.match(/<ImpactBadge direction=\{event\.impact_direction\} eventType=\{event\.event_type\} t=\{t\} locale=\{locale\} \/>/g) ?? [];
  assert.equal(calls.length, 2);
});
