import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

/** La tarjeta «Última tesis» de la ficha no enseña veredicto ni resumen (con cifras) de un borrador. */
// @ts-expect-error TS5097: node strip-types requires the extension.
const { thesisIsPublic } = await import('../lib/research/thesis-publication.ts');

const page = readFileSync('app/(root)/research/[ticker]/page.tsx', 'utf8');

describe('ficha: borrador sin veredicto ni cifras en «Última tesis»', () => {
    it('solo published es pública; el helper es el que usa la ficha', () => {
        assert.equal(thesisIsPublic('published'), true);
        for (const status of ['approved', 'final', 'draft', 'review', 'changes_requested', 'insufficient_data', '', null, undefined]) {
            assert.equal(thesisIsPublic(status), false, String(status));
        }
        assert.match(page, /import \{ thesisIsPublic \} from '@\/lib\/research\/thesis-publication'/);
        assert.match(page, /thesisIsPublic\(snapshot\.latest_thesis\.status\)/);

    });
    it('rating y resumen condicionados a tesis pública; el borrador dice por qué', () => {
        assert.match(page, /thesisIsPublic\(snapshot\.latest_thesis\.status\) && visibleThesisRating/);
        assert.match(page, /<ThesisSummary thesis=\{snapshot\.latest_thesis\} model=\{snapshot\.model_summary\} locale=\{locale\} \/>/);
        const summary = readFileSync('components/research/ThesisSummary.tsx', 'utf8');
        assert.match(summary, /thesisIsPublic\(thesis\.status\)/);
        assert.match(summary, /model\?\.publishable === true/);
    });
});
