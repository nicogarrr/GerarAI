import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

/** La tarjeta «Última tesis» de la ficha no enseña veredicto ni resumen (con cifras) de un borrador. */
const page = readFileSync('app/(root)/research/[ticker]/page.tsx', 'utf8');

describe('ficha: borrador sin veredicto ni cifras en «Última tesis»', () => {
    it('solo published/approved son públicas (insufficient_data es provisional y tampoco muestra veredicto)', () => {
        assert.match(page, /status === 'published' \|\| status === 'approved';/);
    });
    it('rating y resumen condicionados a tesis pública; el borrador dice por qué', () => {
        assert.match(page, /thesisIsPublic\(snapshot\.latest_thesis\.status\) && visibleThesisRating/);
        assert.match(page, /<ThesisSummary thesis=\{snapshot\.latest_thesis\} model=\{snapshot\.model_summary\} locale=\{locale\} \/>/);
        const summary = readFileSync('components/research/ThesisSummary.tsx', 'utf8');
        assert.match(summary, /thesis.status === 'published' \|\| thesis.status === 'approved'/);
        assert.match(summary, /model\?\.publishable === true/);
    });
});
