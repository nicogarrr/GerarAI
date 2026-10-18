import assert from 'node:assert/strict';
import test from 'node:test';
// @ts-expect-error TS5097: explicit extension for node strip-types.
import { humanizeTaxText } from '../lib/taxes/humanize-text.ts';
// @ts-expect-error TS5097: explicit extension for node strip-types.
import { changeSummaryText, changeTypeLabel } from '../lib/research/change-copy.ts';
// @ts-expect-error TS5097: explicit extension for node strip-types.
import { alertCardCopy } from '../lib/alerts/card-copy.ts';

test('claves internas del declarante no llegan a pantalla', () => {
  const text = humanizeTaxText("Declara tax_declarant.custody con la clave 'cash:USD' en la metadata del tenant");
  assert.doesNotMatch(text, /tax_declarant|tenant|custody/);
});

test('el cuerpo del cambio no repite el titular y las etiquetas van en español', () => {
  const out = changeSummaryText('Noticia material que requiere revisión de la tesis: Acme gana un contrato de 5 millones con la NASA. Acme gana un contrato de 5 millones con la NASA.');
  assert.equal(out.match(/Acme gana/g)?.length, 1);
  assert.equal(changeTypeLabel('news_material_update'), 'noticia material');
  assert.match(changeSummaryText('Evidence classified claim as contradicted: X sube'), /^La evidencia clasificó/);
});

test('alerta genérica usa su propio texto', () => {
  const card = alertCardCopy({ id: 1, title: 'Posiciones cortas en aumento: ZS', message: 'ZS: posiciones cortas FINRA 1 → 2 acciones a 2026-10-01.', severity: 'medium', status: 'open', alert_type: 'shorts_rising', channels: [], deliveries: {}, ticker: 'ZS', companyName: 'Zscaler', triggeredAt: null, sourceUrl: null, createdAt: '2026-10-18T10:00:00Z', eventDate: null, eventDateSource: null, eventForm: null });
  assert.match(card.summary, /FINRA/);
  assert.doesNotMatch(card.summary, /consulta la regla/);
});
