/**
 * Guard F138/F238/F244 (/help coherente con la app real): la guia no
 * puede nombrar pestañas/botones que no existen («Model», «Generate
 * model»), ni enviar la exportacion de la tesis a /export (que es la
 * exportacion anual del journal), ni describir un flujo de favoritos
 * con estrella que la app no tiene (es «Seguir»), ni dejar nombres de
 * modulos en ingles («Decision Journal», «what must be true»,
 * «Expectation vs Reality»), ni nombrar controles de exportacion que
 * la tesis no ofrece («Exportar memo», «Exportar EPUB»): el menu real
 * es «Leer / Descargar» y la vista de lectura añade «Imprimir».
 *
 * La ficha tiene seis pestañas (Resumen/Tesis/Finanzas/Valoración/
 * Seguimiento/Fuentes): la tesis se genera en «Tesis» y el modelo
 * fundamental vive en la sección «Modelo fundamental a largo plazo»
 * de «Valoración». No hay pestaña «Modelo» ni boton «Generar modelo».
 *
 * Ejecucion: node --experimental-strip-types --test scripts/help-copy-honesty-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

// Las afirmaciones visibles viven en el diccionario; los enlaces siguen en JSX.
const helpTabs = readFileSync('components/help/HelpTabs.tsx', 'utf8');
const esHelpRaw = readFileSync('lib/i18n/messages/es/help.json', 'utf8');
const source = helpTabs + '\n' + esHelpRaw;
const enSource = readFileSync('lib/i18n/messages/en/help.json', 'utf8');
const esHelp = JSON.parse(esHelpRaw);
const enHelp = JSON.parse(enSource);
const esNav = JSON.parse(readFileSync('lib/i18n/messages/es/nav.json', 'utf8'));
const enNav = JSON.parse(readFileSync('lib/i18n/messages/en/nav.json', 'utf8'));
const screenerPage = readFileSync('app/(root)/screener/page.tsx', 'utf8');

describe('help copy honesty guard (F138/F238/F244)', () => {
  it('nombra la pestaña y el boton reales de la tesis y la valoracion', () => {
    for (const gone of ['«Model»', '«Modelo»', 'Generate model', '«Generar modelo»']) {
      assert.equal(source.includes(gone), false, `referencia retirada: ${gone}`);
    }
    assert.match(source, /«Tesis»/);
    assert.match(source, /«Generar tesis»/);
    assert.match(source, /«Valoración»/);
    assert.match(source, /«Modelo fundamental a largo plazo»/);
  });

  it('la guia inglesa usa los nombres reales', () => {
    for (const gone of ['«Model»', 'Generate model', 'The «Model» tab']) {
      assert.equal(enSource.includes(gone), false, `referencia retirada: ${gone}`);
    }
    assert.match(enSource, /«Thesis»/);
    assert.match(enSource, /«Generate thesis»/);
    assert.match(enSource, /«Valuation»/);
    assert.match(enSource, /«Long-term fundamental model»/);
  });

  it('nombra los controles reales de la tesis y no inventa exportaciones', () => {
    for (const invented of ['Exportar memo', 'Exportar EPUB', 'Export memo', 'Export EPUB', 'EPUB']) {
      assert.equal(source.includes(invented), false, `control inexistente en es: ${invented}`);
      assert.equal(enSource.includes(invented), false, `control inexistente en en: ${invented}`);
    }
    for (const real of ['Leer / Descargar', 'Leer la tesis', 'Descargar PDF', 'Descargar Markdown', 'Imprimir']) {
      assert.ok(source.includes(real), `control real ausente en es: ${real}`);
      assert.ok(enSource.includes(real), `control real ausente en en: ${real}`);
    }
    assert.match(source, /\/export\}?<\/Link>\{?' '?\}\s*es la exportación anual del journal|exportación anual del journal/, '/export se describe como lo que es');
  });

  it('usa los nombres reales de los modulos, en español', () => {
    for (const en of ['Decision Journal', 'what must be true', 'Expectation vs Reality']) {
      assert.equal(source.includes(en), false, `nombre en ingles: ${en}`);
    }
    assert.match(source, /Diario de decisiones/);
    assert.match(source, /Expectativa vs realidad/);
  });

  it('el FAQ de seguimiento describe el flujo «Seguir», sin estrella', () => {
    assert.equal(source.includes('icono de estrella'), false, 'no hay estrella en la app');
    assert.match(source, /«Seguir»/);
  });

  it('«Explorar acciones» enlaza /screener, cuyo H1 es el título del módulo', () => {
    assert.match(helpTabs, /href: '\/screener', title: t\('help\.modules\.item4\.title'\)/, 'item4 apunta a /screener');
    assert.equal(helpTabs.includes("href: '/screeners', title: t('help.modules.item4.title')"), false, 'item4 no apunta a /screeners');
    assert.match(screenerPage, /t\('nav\.screener'\)/, 'el H1 de /screener usa nav.screener');
    assert.equal(esHelp.modules.item4.title, esNav.screener, 'el título es coincide con el H1 de destino');
    assert.equal(enHelp.modules.item4.title, enNav.screener, 'el título en coincide con el H1 de destino');
  });
});
