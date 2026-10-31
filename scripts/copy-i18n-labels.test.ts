/**
 * Batch copy/i18n honestidad (F208/F174/F175): las cadenas internas o en
 * inglés no se pintan crudas - sectores de la cabecera de /risk, tipos de
 * instrumento del buscador, tiers y tipos de evento de /research/news.
 * Ejecución: node --experimental-strip-types --test scripts/copy-i18n-labels.test.ts
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

// @ts-expect-error TS5097: la extensión explícita la exige node --experimental-strip-types.
import { sectorIndustryLine, etiquetaValor, etiquetaFactor, etiquetaSector, etiquetaSeveridad, etiquetaTierFuente, etiquetaTipoEvento, etiquetaTipoInstrumento } from '../lib/labels.ts';

void test('sectores de la cabecera de exposición se traducen (F208)', () => {
    assert.equal(etiquetaSector('Communication Services'), 'Servicios de comunicación');
    assert.equal(etiquetaSector('Sector Inventado'), 'Sector Inventado');
    assert.equal(etiquetaFactor('pre_fcf'), 'Pre flujo de caja libre');
    assert.equal(etiquetaFactor('adr:8'), 'ADR (ratio 8)');
    assert.equal(etiquetaFactor('algo_nuevo'), 'Algo nuevo');
    assert.equal(etiquetaSector('Unknown'), 'Sin clasificar');
    assert.equal(etiquetaSeveridad('high'), 'Alta');
    assert.equal(etiquetaSeveridad('medium'), 'Media');
    assert.equal(etiquetaSeveridad('raro'), 'raro');
});

void test('tipos de instrumento del buscador en español (F174)', () => {
    assert.equal(etiquetaTipoInstrumento('Common Stock'), 'Acción ordinaria');
    assert.equal(etiquetaTipoInstrumento('Canadian DR'), 'Recibo de depósito canadiense');
    assert.equal(etiquetaTipoInstrumento('Otro tipo'), 'Otro tipo');
    // OpenFIGI securityType sin significado de clase de activo: literal, sin traducción inferida.
    assert.equal(etiquetaTipoInstrumento('PUBLIC'), 'PUBLIC');
});

void test('los ocho tiers del catálogo backend tienen etiqueta (F175)', () => {
    // Catálogo completo de source_hierarchy_service.SOURCE_TIERS; si el
    // backend añade una clave, su tripwire en pytest obliga a etiquetarla aquí.
    assert.equal(etiquetaTierFuente('tier_1_regulatory'), 'Regulatoria · T1');
    assert.equal(etiquetaTierFuente('tier_2_company'), 'Empresa · T2');
    assert.equal(etiquetaTierFuente('tier_3_transcript'), 'Transcripción · T3');
    assert.equal(etiquetaTierFuente('tier_4_reputable_media'), 'Medios · T4');
    assert.equal(etiquetaTierFuente('tier_5_data_provider'), 'Proveedor de datos · T5');
    assert.equal(etiquetaTierFuente('tier_6_bootstrap'), 'Datos iniciales · T6');
    assert.equal(etiquetaTierFuente('tier_7_user_input'), 'Aportado por el usuario · T7');
    assert.equal(etiquetaTierFuente('tier_unknown'), 'Fuente sin clasificar');
});

void test('tipos de evento y fallback de códigos futuros (F175)', () => {
    assert.equal(etiquetaTipoEvento('regulatory'), 'Regulatorio');
    assert.equal(etiquetaTipoEvento('earnings'), 'Resultados');
    assert.equal(etiquetaTipoEvento('dilution'), 'Dilución');
    assert.equal(etiquetaTipoEvento('contract'), 'Contrato');
    assert.equal(etiquetaTipoEvento('capital_allocation'), 'Asignación de capital');
    assert.equal(etiquetaTipoEvento('general_news'), 'Noticia general');
    // Código futuro desconocido: se muestra crudo (honesto), nunca inventado.
    assert.equal(etiquetaTierFuente('tier_8_futuro'), 'tier_8_futuro');
});

void test('los componentes usan las etiquetas, no la cadena cruda', () => {
    const risk = readFileSync('components/risk/RiskDashboardView.tsx', 'utf8');
    assert.match(risk, /exposureRecord\(t, f, value, etiquetaSector\)/);
    assert.match(risk, /exposureRecord\(t, f, value, etiquetaFactor\)/);
    assert.match(risk, /etiquetaSeveridad\(formatRecordValue\(alert\.severity\)\)/);
    assert.doesNotMatch(risk, /hace falta historia de precios/);
    const search = readFileSync('components/SearchCommand.tsx', 'utf8') + readFileSync('components/SearchCommandDialog.tsx', 'utf8');
    assert.match(search, /etiquetaTipoInstrumento\(stock\.type\)/);
    const news = (readFileSync('app/(root)/research/news/page.tsx', 'utf8') + readFileSync('components/research/NewsEventsFlow.tsx', 'utf8'));
    // La tabla ya no muestra la columna de tier (SERIE 1): si vuelve a
    // aparecer source_tier, debe pasar por la etiqueta, nunca crudo.
    if (news.includes('event.source_tier')) {
        assert.match(news, /etiquetaTierFuente\(event\.source_tier, locale\)/, 'source_tier solo se muestra via etiquetaTierFuente, nunca crudo');
    }
    assert.match(news, /etiquetaTipoEvento\(event\.event_type, locale\)/);
});

test('industrias conocidas se traducen en la línea de sector del índice', () => {
  assert.equal(sectorIndustryLine('Communication Services', 'Communications'), 'Servicios de comunicación · Comunicaciones');
  assert.equal(sectorIndustryLine('Industrials', 'Professional Services'), 'Industriales · Servicios profesionales');
  assert.equal(sectorIndustryLine('Industrials', 'Electrical Equipment'), 'Industriales · Equipamiento eléctrico');
});

test('etiquetaValor traduce códigos del backend y no deja guiones bajos', () => {
  assert.equal(etiquetaValor('unproven'), 'no probada');
  assert.equal(etiquetaValor('uncertain'), 'incierta');
  assert.equal(etiquetaValor('tier_1_regulatory'), 'Regulatoria · T1');
  assert.equal(etiquetaValor('tier_unknown'), 'Fuente sin clasificar');
  assert.equal(etiquetaValor('primary_official'), 'oficial primaria');
  assert.equal(etiquetaValor('wacc_policy'), 'política de WACC');
  assert.equal(etiquetaValor('algo_nuevo'), 'algo nuevo');
});


test('la lista de auditorías conserva la referencia a su versión de tesis', () => {
  const source = readFileSync('app/(root)/research/[ticker]/page.tsx', 'utf8');
  assert.ok(source.includes("`tesis v${audit.thesis_version}`"));
  assert.ok(!source.includes('tesis {audit.thesis_version_id'), 'id interno de tesis');
  assert.ok(source.includes('<SourceAuditDetail audit={audit} ticker={ticker} />'));
});
