import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
// @ts-expect-error TS5097: la extensión explícita la exige node --experimental-strip-types.
import { groupReviews } from '../lib/research/review-groups.ts';

describe('revisiones agrupadas', () => {
    it('91 revisiones iguales salen como un renglón con contador y la fecha más reciente', () => {
        const rows = Array.from({ length: 91 }, (_, i) => ({ id: i + 1, title: 'Revisión necesaria: actualización material de noticias', created_at: `2026-10-${String(1 + (i % 19)).padStart(2, '0')}T10:00:00Z` }));
        const groups = groupReviews([...rows, { id: 500, title: 'Otra revisión', created_at: '2026-10-20T00:00:00Z' }]);
        assert.equal(groups.length, 2);
        assert.equal(groups[0].title, 'Otra revisión');
        assert.equal(groups[1].count, 91);
        assert.equal(groups[1].latest, '2026-10-19T10:00:00Z');
    });
    it('ignora mayúsculas y espacios repetidos', () => {
        assert.equal(groupReviews([{ id: 1, title: 'A  b' }, { id: 2, title: 'a b ' }]).length, 1);
    });
});
