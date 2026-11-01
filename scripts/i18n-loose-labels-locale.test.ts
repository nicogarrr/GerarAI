import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
// @ts-expect-error explicit extension for node
import { createTranslator } from '../lib/i18n/translate.ts';
// @ts-expect-error explicit extension for node
import { xirrUnavailableReason } from '../lib/research/xirr-status.ts';
// @ts-expect-error explicit extension for node
import { etiquetaCanal, etiquetaEstadoEntrega } from '../lib/alerts/delivery-labels.ts';
// @ts-expect-error explicit extension for node
import { listingStatus } from '../lib/research/listing-status.ts';

const en = createTranslator('en');
const now = new Date('2026-11-01T12:00:00Z');

test('XIRR «N/D» reason follows the chosen language', () => {
  assert.equal(xirrUnavailableReason('no_xirr_root', en), 'it does not converge with the recorded cash flows');
  assert.equal(xirrUnavailableReason('whatever', en), 'not enough cash flows in the transaction record');
  assert.equal(xirrUnavailableReason('no_xirr_root'), 'no converge con los flujos registrados');
  assert.equal(xirrUnavailableReason(null), 'sin flujos suficientes en el registro de transacciones');
  assert.equal(xirrUnavailableReason('toString', en), 'not enough cash flows in the transaction record');
});

test('alert channel and delivery labels follow the chosen language', () => {
  assert.equal(etiquetaCanal('in_app', en), 'in the app');
  assert.equal(etiquetaCanal('email', en), 'email');
  assert.equal(etiquetaEstadoEntrega('delivered', en), 'delivered');
  assert.equal(etiquetaEstadoEntrega('sin registro', en), 'no delivery record');
  assert.equal(etiquetaCanal('in_app'), 'en la app');
  assert.equal(etiquetaEstadoEntrega('failed'), 'fallida');
  assert.equal(etiquetaCanal('sms', en), 'sms');
  assert.equal(etiquetaCanal('constructor', en), 'constructor');
});

test('stale listing banner follows the chosen language; Spanish keeps dd/mm/yyyy', () => {
  assert.deepEqual(listingStatus('UNKNOWN', null, now, false, en), { stale: true, message: 'Ticker with no current quote (no known close)' });
  const stale = listingStatus('NASDAQ', '2026-09-27', now, false, en, (iso: string) => `<${iso}>`);
  assert.deepEqual(stale, { stale: true, message: 'Ticker with no current quote (last close <2026-09-27>)' });
  assert.deepEqual(listingStatus('NASDAQ', '2026-09-27', now), { stale: true, message: 'Ticker sin cotización vigente (último cierre 27/09/2026)' });
});

test('callers pass the translator', () => {
  const alerts = readFileSync('components/alerts/AlertsManager.tsx', 'utf8');
  assert.ok(!alerts.includes('.map(etiquetaCanal)'));
  assert.ok(alerts.includes('etiquetaEstadoEntrega(status, ti)'));
  assert.ok(readFileSync('app/(root)/portfolio/intelligence/page.tsx', 'utf8').includes('xirrUnavailableReason(data.performance.trace?.status, ti)'));
  assert.ok(readFileSync('components/research/ListingStaleBanner.tsx', 'utf8').includes('hasCurrentQuote(live, now), ti, formatDate)'));
});
