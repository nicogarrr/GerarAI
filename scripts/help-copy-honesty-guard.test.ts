/**
 * Guard F138/F238/F244 (/help coherente con la app real): la guia no
 * puede nombrar pestañas/botones que no existen («Model», «Generate
 * model»), ni enviar la exportacion de la tesis a /export (que es la
 * exportacion anual del journal), ni describir un flujo de favoritos
 * con estrella que la app no tiene (es «Seguir»), ni dejar nombres de
 * modulos en ingles («Decision Journal», «what must be true»,
 * «Expectation vs Reality»).
 *
 * Ejecucion: node --experimental-strip-types --test scripts/help-copy-honesty-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

// Las afirmaciones visibles viven en el diccionario; los enlaces siguen en JSX.
const source = readFileSync('components/help/HelpTabs.tsx', 'utf8') + '\n' + readFileSync('lib/i18n/messages/es/help.json', 'utf8');

describe('help copy honesty guard (F138/F238/F244)', () => {
  it('nombra la pestaña y el boton reales del modelo', () => {
    assert.equal(source.includes('«Model»'), false, 'la pestaña real es «Modelo»');
    assert.equal(source.includes('Generate model'), false, 'el boton real es «Generar modelo»');
    assert.match(source, /«Modelo»/);
    assert.match(source, /«Generar modelo»/);
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
