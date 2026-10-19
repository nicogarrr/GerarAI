import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
// @ts-expect-error TS5097: la extensión explícita la exige node --experimental-strip-types.
import { analystRatingEs } from '../lib/research/analyst-rating-es.ts';

describe('recomendaciones de analistas en español', () => {
    it('traduce las habituales', () => {
        assert.equal(analystRatingEs('Overweight'), 'Sobreponderar');
        assert.equal(analystRatingEs('  equal-weight '), 'Ponderación neutral');
        assert.equal(analystRatingEs('Buy'), 'Compra');
        assert.equal(analystRatingEs('Underweight'), 'Infraponderar');
    });
    it('lo desconocido queda tal cual y lo vacío es null', () => {
        assert.equal(analystRatingEs('Speculative Buy'), 'Speculative Buy');
        assert.equal(analystRatingEs(null), null);
        assert.equal(analystRatingEs(''), null);
    });
});
