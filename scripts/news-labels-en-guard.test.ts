import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
// @ts-expect-error TS5097: node --experimental-strip-types necesita la extensión.
import { etiquetaDireccionImpacto, etiquetaTemaMacro, etiquetaTierFuente, etiquetaTipoEvento } from '../lib/labels.ts';
// @ts-expect-error TS5097: node --experimental-strip-types necesita la extensión.
import { TICKER_BADGE_LABELS, TICKER_BADGE_LABELS_EN } from '../lib/ticker-badges.ts';

test('sin locale las etiquetas siguen siendo el literal ES histórico', () => {
  assert.equal(etiquetaDireccionImpacto('negative'), 'Negativo');
  assert.equal(etiquetaTipoEvento('dilution'), 'Dilución');
  assert.equal(etiquetaTipoEvento('general_news'), 'Noticia general');
  assert.equal(etiquetaTipoEvento('unknown'), 'Desconocido');
  assert.equal(etiquetaTierFuente('tier_1_regulatory'), 'Regulatoria · T1');
  assert.equal(etiquetaTemaMacro('interest_rates'), 'Tipos de interés');
  assert.equal(TICKER_BADGE_LABELS.portfolio, 'En cartera');
  assert.equal(TICKER_BADGE_LABELS.watchlist, 'En watchlist');
});

test('EN cubre exactamente las mismas claves y no deja español', () => {
  for (const [k, es] of Object.entries({ positive: 1, negative: 1, neutral: 1, mixed: 1 })) {
    assert.notEqual(etiquetaDireccionImpacto(k, 'en'), etiquetaDireccionImpacto(k), `${k} ${es}`);
  }
  for (const k of ['regulatory', 'earnings', 'dilution', 'contract', 'capital_allocation', 'general_news', 'legal_solicitation', 'opinion', 'unknown']) {
    assert.notEqual(etiquetaTipoEvento(k, 'en'), etiquetaTipoEvento(k), k);
  }
  for (const k of ['tier_1_regulatory', 'tier_2_company', 'tier_3_transcript', 'tier_4_reputable_media', 'tier_5_data_provider', 'tier_6_bootstrap', 'tier_7_user_input', 'tier_8_social', 'tier_unknown']) {
    assert.notEqual(etiquetaTierFuente(k, 'en'), etiquetaTierFuente(k), k);
  }
  for (const k of ['gold_central_banks', 'interest_rates', 'commodities', 'trucking_freight', 'ai_investment', 'hormuz_oil', 'energy', 'semiconductors', 'dollar_fx', 'inflation', 'china_supply_chains', 'us_trade_policy']) {
    assert.notEqual(etiquetaTemaMacro(k, 'en'), etiquetaTemaMacro(k), k);
  }
  assert.equal(etiquetaTipoEvento('clave_futura', 'en'), 'clave_futura');
  assert.equal(TICKER_BADGE_LABELS_EN.portfolio, 'In portfolio');
});

test('NewsEventsFlow pasa el locale a etiquetas, fechas relativas y badges; el aviso de error usa clave', () => {
  const flow = readFileSync('components/research/NewsEventsFlow.tsx', 'utf8');
  assert.match(flow, /const locale = await getLocale\(\);/);
  assert.equal((flow.match(/formatTimeAgo\(event\.date, Date\.now\(\), locale\)/g) ?? []).length, 2);
  assert.equal((flow.match(/<TickerContextBadges\n\s+locale=\{locale\}/g) ?? []).length, 2);
  const second = readFileSync('components/research/NewsSecondOrder.tsx', 'utf8');
  assert.match(second, /\{t\('research\.flow\.second\.error'\)\}/);
  const es = JSON.parse(readFileSync('lib/i18n/messages/es/research.json', 'utf8')).flow.second;
  assert.equal(es.error, 'No disponible ahora. Vuelve a abrir para reintentar.');
  assert.equal(es.none, 'Sin empresas del universo expuestas a esta noticia.');
  assert.equal(es.more, 'y {count} más');
});

test('todo macro_theme que emite el backend tiene etiqueta ES y EN (nunca el código crudo)', () => {
  const py = readFileSync('data-engine/app/services/macro_news.py', 'utf8');
  const block = py.slice(py.indexOf('MACRO_GDELT_QUERIES'));
  const keys = [...block.matchAll(/^\s{8}"([a-z_]+)",$/gm)].map((m) => m[1]);
  assert.ok(keys.length >= 10, 'se leyeron los temas del backend');
  for (const k of keys) {
    assert.notEqual(etiquetaTemaMacro(k), k, `ES ${k}`);
    assert.notEqual(etiquetaTemaMacro(k, 'en'), k, `EN ${k}`);
    assert.notEqual(etiquetaTemaMacro(k, 'en'), etiquetaTemaMacro(k), `EN != ES ${k}`);
  }
});
