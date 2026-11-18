/**
 * Guard F138/F238/F244 (/help coherente con la app real): la guia no
 * puede nombrar pestañas/botones que no existen («Model», «Generate
 * model»), ni enviar la exportacion de la tesis a /export (que es la
 * exportacion anual del journal), ni describir un flujo de favoritos
 * con estrella que la app no tiene (es «Seguir»), ni dejar nombres de
 * modulos en ingles («Decision Journal», «what must be true»,
 * «Expectation vs Reality»).
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
const source = readFileSync('components/help/HelpTabs.tsx', 'utf8') + '\n' + readFileSync('lib/i18n/messages/es/help.json', 'utf8');
const enSource = readFileSync('lib/i18n/messages/en/help.json', 'utf8');

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

  it('no envia la exportacion de la tesis a /export', () => {
    assert.match(source, /«Exportar memo» y «Exportar EPUB»/, 'la tesis se exporta desde su vista');
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
});
