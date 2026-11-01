/**
 * Sin etiquetas de fuente en la UI (orden de Nico, 31-oct, aclarada por el piloto):
 * los avisos de calidad (no oficial / desactualizado / sin verificar / cotejar)
 * se conservan SIN nombrar la fuente. La procedencia vive en la pestana Fuentes,
 * ayuda/metodologia, chat, tesis y el registro interno (SOURCE, claves de datos).
 *
 * Este guard prueba AUSENCIA de proveedor en las etiquetas visibles que quedaban
 * tras #3707 y #3751: tooltips de watchlist, radar, facts panels, objetivos de
 * analistas, screener, paper trading, deep value y las etiquetas de cotizacion.
 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const read = (path) => readFileSync(path, 'utf8');

test('watchlist: tooltip de consenso sin "fuente de mercado"', () => {
    const page = read('app/(root)/watchlist/page.tsx');
    const es = read('lib/i18n/messages/es/watchlist.json');
    assert.doesNotMatch(page + es, /Fuente de mercado no oficial/);
    assert.ok(page.includes("t('watchlist.page.analystTitle')"));
    assert.match(JSON.parse(es).page.analystTitle, /Fuente no oficial\./, 'se conserva el aviso de calidad sin nombrar fuente');
});

test('radar global: candidatos sin etiqueta de fuente', () => {
    const view = read('components/proPicks/RadarGlobalView.tsx') + JSON.stringify(JSON.parse(read('lib/i18n/messages/es/propicks.json')).radar);
    assert.doesNotMatch(view, /fuente de mercado/i);
    assert.match(view, /Candidatos sin verificar; conviene cotejo oficial/);
    assert.match(view, /Consulta en vivo al pulsar el botón/);
});

test('objetivos de analistas: aviso de divisa sin fuente', () => {
    const view = read('components/research/AnalystTargetsView.tsx');
    assert.doesNotMatch(view, /fuente de mercado/i);
    assert.match(view, /Divisa no declarada: importes sin unidad verificada/);
});

test('facts panels: cifras no oficiales sin etiqueta de fuente', () => {
    const view = read('components/research/FactsPanels.tsx');
    assert.doesNotMatch(view, /fuente no oficial|fuente de mercado/i);
    assert.match(view, /Incluye cifras no oficiales, sin auditar ni contrastar/);
});

test('screener: lectura offline sin nombre de proveedor', () => {
    // El aviso vive en el diccionario: solo se añaden sus dos claves (es y en).
    const dicts = ['es', 'en'].map((lang) => JSON.parse(read(`lib/i18n/messages/${lang}/screener.json`)));
    const page = read('app/(root)/screener/page.tsx') + JSON.stringify(dicts.map((d) => [d.engineDownText, d.metaDescription]));
    assert.doesNotMatch(page, /precios Finnhub|lectura offline con Finnhub|Finnhub prices|with Finnhub/);
    assert.match(page, /La tabla muestra precios como lectura offline/);
});

test('paper trading: nota de dividendos sin Yahoo/FMP', () => {
    const view = read('components/proPicks/PaperTradingView.tsx');
    // La nota vive en el diccionario (Ajustes → Idioma); el literal español no cambia.
    const note = JSON.parse(read('lib/i18n/messages/es/propicks.json')).paper.basisText;
    assert.doesNotMatch(view, /Yahoo\/FMP|fuente Yahoo/i);
    assert.doesNotMatch(note, /Yahoo\/FMP|fuente Yahoo/i);
    assert.match(view, /t\('propicks\.paper\.basisText'\)/);
    assert.match(note, /fuente no oficial; eventos inciertos excluidos/);
});

test('deep value: desacuerdo de fuentes sin nombrar la fuente', () => {
    const view = read('components/proPicks/DeepValueView.tsx') + JSON.stringify(JSON.parse(read('lib/i18n/messages/es/propicks.json')).deepValue);
    assert.doesNotMatch(view, /Finnhub indica/);
    assert.match(view, /Fuentes en desacuerdo: otra fuente indica/);
});

test('portfolio i18n: razones de exclusion sin nombre de proveedor', () => {
    for (const lang of ['es', 'en']) {
        const messages = read(`lib/i18n/messages/${lang}/portfolio.json`);
        assert.doesNotMatch(messages, /\(Yahoo\)|Yahoo no indic|Yahoo devolvi|Yahoo did not|Yahoo returned/);
    }
});

test('paper trading i18n: nota de valoracion sin nombre de proveedor', () => {
    const es = read('lib/i18n/messages/es/paperTrading.json');
    const en = read('lib/i18n/messages/en/paperTrading.json');
    assert.doesNotMatch(es, /Solo se valora con Finnhub/);
    assert.doesNotMatch(en, /Valuation only uses Finnhub/);
    assert.match(es, /cotizaci[oó]n en vivo/);
    assert.match(en, /live quote/);
});

test('etiquetas de cotizacion: sin prefijo de proveedor', () => {
    const valuation = read('lib/market/demo-valuation.ts');
    assert.doesNotMatch(valuation, /\$\{source\} · /, 'quoteLabel ya no prefija el nombre de la fuente');
    assert.doesNotMatch(valuation, /listado de Finnhub indica|listado de Finnhub:/, 'los motivos de N/D no nombran la fuente');
});
