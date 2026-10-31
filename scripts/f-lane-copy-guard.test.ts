import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
// @ts-expect-error TS5097: explicit extension for node strip-types.
import { humanizeTaxText } from '../lib/taxes/humanize-text.ts';
// @ts-expect-error TS5097: explicit extension for node strip-types.
import { changeSummaryText, changeTypeLabel } from '../lib/research/change-copy.ts';
// @ts-expect-error TS5097: explicit extension for node strip-types.
import { alertCardCopy } from '../lib/alerts/card-copy.ts';

/** t() de test: resuelve alerts.card.* contra messages/es/alerts.json con
 *  interpolación {var}: el guard comprueba el copy real que se renderiza. */
const ES_ALERTS = JSON.parse(readFileSync('lib/i18n/messages/es/alerts.json', 'utf8'));
const t = ((key: string, vars: Record<string, string | number> = {}): string => {
  const value = key.split('.').slice(1).reduce<unknown>((node, part) => (node as Record<string, unknown>)[part], ES_ALERTS);
  assert.equal(typeof value, 'string', `falta ${key} en messages/es/alerts.json`);
  return (value as string).replace(/\{(\w+)\}/g, (_, name) => String(vars[name] ?? `{${name}}`));
}) as never;
const LOCALE = 'es' as never;


test('claves internas del declarante no llegan a pantalla', () => {
  const text = humanizeTaxText("Declara tax_declarant.custody con la clave 'cash:USD' en la metadata del tenant");
  assert.doesNotMatch(text, /tax_declarant|tenant|custody/);
});

test('plantilla del declarante sin sustituciones rotas ni ids de caja crudos', () => {
  const raw = "Faltan datos identificativos del declarante: no se inventan. Guárdalos en la metadata del tenant bajo la clave 'tax_declarant' (nif, apellidos_nombre).";
  const text = humanizeTaxText(raw);
  assert.doesNotMatch(text, /la tus|la los|tenant|tax_declarant/);
  assert.match(text, /Guárdalos en tus datos fiscales, en los datos del declarante/);
  assert.equal(humanizeTaxText('cash-EUR'), 'caja EUR');
  const dates = humanizeTaxText("Faltan first_acquisition_dates por ISIN y previous_year_isins");
  assert.doesNotMatch(dates, /_/);
  assert.match(dates, /fechas de primera adquisición/);
});

test('la jerga «snapshot» del motor fiscal llega como «captura»', () => {
    assert.equal(
        humanizeTaxText('Partidas con snapshot demasiado antiguo (V): cada valor afirma su 31/12 con SU snapshot; uno reciente no certifica a otro viejo. Resultado no concluyente.'),
        'Partidas con captura demasiado antigua (V): cada valor afirma su 31/12 con SU captura; una reciente no certifica a otra vieja. Resultado no concluyente.',
    );
    assert.equal(
        humanizeTaxText('Sin snapshots de valoración a cierre del ejercicio: no se puede afirmar nada sobre esta categoría.'),
        'Sin capturas de valoración a cierre del ejercicio: no se puede afirmar nada sobre esta categoría.',
    );
    assert.equal(
        humanizeTaxText('Sin tipo de cambio a fecha del snapshot: fuera del total EUR, valorar a mano.'),
        'Sin tipo de cambio a fecha de la captura: fuera del total EUR, valorar a mano.',
    );
});

test('el cuerpo del cambio no repite el titular y las etiquetas van en español', () => {
  const out = changeSummaryText('Noticia material que requiere revisión de la tesis: Acme gana un contrato de 5 millones con la NASA. Acme gana un contrato de 5 millones con la NASA.');
  assert.equal(out.match(/Acme gana/g)?.length, 1);
  assert.equal(changeTypeLabel('news_material_update'), 'noticia material');
  assert.match(changeSummaryText('Evidence classified claim as contradicted: X sube'), /^La evidencia clasificó/);
  assert.doesNotMatch(changeSummaryText('Material news requires thesis review. No structural thesis node matched with sufficient confidence.'), /No structural/);
});

test('alerta genérica usa su propio texto', () => {
  const card = alertCardCopy({ id: 1, title: 'Posiciones cortas en aumento: ZS', message: 'ZS: posiciones cortas FINRA 1 → 2 acciones a 2026-10-01.', severity: 'medium', status: 'open', alert_type: 'shorts_rising', channels: [], deliveries: {}, ticker: 'ZS', companyName: 'Zscaler', triggeredAt: null, sourceUrl: null, createdAt: '2026-10-18T10:00:00Z', eventDate: null, eventDateSource: null, eventForm: null }, t, LOCALE);
  assert.match(card.summary, /FINRA/);
  assert.doesNotMatch(card.summary, /consulta la regla/);
});
