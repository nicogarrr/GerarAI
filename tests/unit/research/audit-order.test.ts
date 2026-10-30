import { describe, expect, it } from 'vitest';

import { sortAuditsRecentFirst } from '@/lib/audit-status-copy';

describe('sortAuditsRecentFirst', () => {
    it('la auditoría más reciente va primero; sin fecha desempata por id', () => {
        const ordered = sortAuditsRecentFirst([
            { id: 3, created_at: '2026-10-20T10:00:00Z' },
            { id: 9, created_at: '2026-10-29T10:00:00Z' },
            { id: 5, created_at: null },
            { id: 7, created_at: null },
        ]);
        expect(ordered.map((a) => a.id)).toEqual([9, 3, 7, 5]);
    });

    it('no muta la entrada', () => {
        const input = [{ id: 1, created_at: '2026-10-20T10:00:00Z' }, { id: 2, created_at: '2026-10-29T10:00:00Z' }];
        sortAuditsRecentFirst(input);
        expect(input.map((a) => a.id)).toEqual([1, 2]);
    });
});
