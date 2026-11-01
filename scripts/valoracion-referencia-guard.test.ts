import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

/**
 * Guard de la fuente de verdad de valoración (WorldStocks punto 3): el
 * «valor por acción» interno del modelo remite a la vista Valoración como
 * referencia de la ficha, con enlace a sus 3 escenarios; sin ticker la nota
 * sigue siendo válida y no enlaza a ningún sitio roto.
 */
const panel = readFileSync('components/research/FundamentalModelPanels.tsx', 'utf8');
const page = readFileSync('app/(root)/research/[ticker]/page.tsx', 'utf8');
// El texto vive en el diccionario (i18n): se comprueba la clave en el panel y la redacción en español.
const es = JSON.parse(readFileSync('lib/i18n/messages/es/research.json', 'utf8')).model as Record<string, string>;

describe('modelo: la valoración de referencia es la vista Valoración', () => {
    it('declara la vista Valoración como referencia de la ficha', () => {
        assert.match(panel, /research\.model\.noteIntro/);
        assert.match(panel, /research\.model\.noteOutro/);
        assert.match(es.noteIntro, /La valoración de referencia de la ficha es la de la vista Valoración/);
        assert.match(es.noteOutro, /manda ella/);
    });
    it('enlaza a sus 3 escenarios solo con ticker (nunca una URL rota)', () => {
        assert.match(panel, /\?view=valuation/);
        assert.match(panel, /research\.model\.noteLink/);
        assert.match(es.noteLink, /ver sus 3 escenarios/);
        assert.match(panel, /\{ticker \? \(/);
    });
    it('mantiene la honestidad sobre el cálculo interno (versión y fecha)', () => {
        assert.match(es.noteIntro, /cálculo interno del modelo/);
        assert.match(es.noteOutro, /compara versión y fecha antes de usarlo/);
    });
    it('la ficha le pasa el ticker y el traductor', () => {
        // t llega del getT() de la pagina: las etiquetas del panel salen del
        // diccionario (ratchet i18n), nunca de literales escritos a mano.
        assert.match(page, /<LongTermModelPanel model=\{model\?\.status === 'not_generated' \? null : model\} ticker=\{ticker\} t=\{t\} locale=\{locale\} \/>/);
    });
});
