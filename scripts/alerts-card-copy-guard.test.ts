import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
// @ts-expect-error TS5097: explicit extension for node strip-types.
import { alertCardCopy, alertSummaryIsSourceHeadline } from '../lib/alerts/card-copy.ts';

const base = {
  id: 1, title: 'Review required: news material update',
  message: 'Material news requires thesis review. No structural thesis node matched with sufficient confidence.',
  severity: 'high', status: 'open', alert_type: 'news_material_update', channels: [], deliveries: {},
  ticker: 'V', companyName: 'Visa', triggeredAt: null, sourceUrl: 'https://www.sec.gov/x',
  createdAt: '2026-09-28T10:00:00Z', eventDate: '2025-10-28T12:00:00Z',
  eventDateSource: 'source', eventForm: '8-K',
};

test('filing card uses only source-backed fields; keeps original machine trace behind detail', () => {
  const card = alertCardCopy(base);
  assert.match(card.heading, /Visa · 8-K · 28 oct 2025/);
  assert.match(card.summary, /Documento 8-K asociado a Visa/);
  assert.doesNotMatch(card.summary, /No structural thesis|21846000000/);
  assert.match(card.technical, /No structural thesis node/);
});

test('unknown form/date are not guessed from machine prose or alert created_at', () => {
  const card = alertCardCopy({ ...base, eventDate: null, eventForm: null });
  assert.equal(card.heading, 'Visa · Noticia material');
  assert.doesNotMatch(card.summary, /8-K|2025/);
});

test('alerts without a company never print a placeholder company', () => {
  const digest = alertCardCopy({ ...base, alert_type: 'daily_digest', title: 'Resumen diario de tu cartera al 2026-10-17', ticker: null, companyName: null, eventDate: null, eventForm: null });
  assert.equal(digest.heading, 'Resumen diario de tu cartera al 2026-10-17');
  assert.doesNotMatch(`${digest.heading} ${digest.summary}`, /Empresa sin identificar/);
  assert.match(digest.summary, /Resumen diario de tu cartera/);
});

test('macro event reminders show their own title and a source-aware summary', () => {
  const card = alertCardCopy({ ...base, alert_type: 'macro_event', title: 'IPC de EE. UU. (inflación): mañana', ticker: null, companyName: null, eventDate: null, eventForm: null });
  assert.equal(card.heading, 'IPC de EE. UU. (inflación): mañana');
  assert.match(card.summary, /calendario macro oficial/);
  assert.doesNotMatch(card.summary, /sin empresa asociada/);
});

test('source and detail controls exist on both surfaces', () => {
  for (const path of ['components/PersonalizedOverview.tsx', 'components/alerts/AlertsManager.tsx']) {
    const view = readFileSync(path, 'utf8');
    assert.match(view, /alertCardCopy\(item\)/);
    // i18n: AlertsManager usa la clave del diccionario; PersonalizedOverview aún tiene el literal.
    assert.match(view, /Ver aviso original|alerts\.triggered\.viewOriginal/);
    assert.match(view, /item.sourceUrl/);
  }
});

test('tracked news card shows the source headline from the alert title', () => {
  const card = alertCardCopy({ ...base, alert_type: 'tracked_news', title: 'Noticia sobre ASML: ASML supera las previsiones de pedidos del trimestre', eventForm: null });
  assert.equal(card.summary, 'ASML supera las previsiones de pedidos del trimestre');
});

test('tracked news card without headline keeps the generic summary (no invented content)', () => {
  const card = alertCardCopy({ ...base, alert_type: 'tracked_news', title: 'Noticia sobre ASML', eventForm: null });
  assert.equal(card.summary, 'Noticia sobre Visa.');
});

test('news_material_update y regla news muestran el titular de la noticia de origen, no relleno', () => {
  for (const alert_type of ['news_material_update', 'news']) {
    const a = { ...base, alert_type, eventForm: null, eventHeadline: 'RKLB sufre su peor semana' };
    const card = alertCardCopy(a);
    assert.equal(card.summary, 'RKLB sufre su peor semana');
    assert.equal(alertSummaryIsSourceHeadline(a), true);
    assert.doesNotMatch(card.summary, /marcada para revisión|impacto aún/);
  }
});

test('noticia sin titular verificable: texto honesto, sin la frase de relleno', () => {
  const a = { ...base, alert_type: 'news_material_update', eventForm: null, eventHeadline: null };
  const card = alertCardCopy(a);
  assert.match(card.summary, /no trae titular verificable/);
  assert.equal(alertSummaryIsSourceHeadline(a), false);
});
