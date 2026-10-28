import { describe, expect, it } from 'vitest';
import { collapseVersionHistory, versionHistoryBadges } from '@/lib/research/version-history';

const e = (version: number, summary: string | null, status = 'ok', rating = 'hold') => ({ version, status, rating, diff: { change_summary: summary } });

describe('collapseVersionHistory', () => {
    it('agrupa consecutivas idénticas y conserva el orden', () => {
        const groups = collapseVersionHistory([e(4, 'Sin cambios'), e(3, 'Sin cambios'), e(2, 'Sin cambios'), e(1, 'Inicial')]);
        expect(groups.map((g) => g.map((x) => x.version))).toEqual([[4, 3, 2], [1]]);
    });
    it('un cambio de estado o de rating rompe el grupo', () => {
        expect(collapseVersionHistory([e(3, 'S'), e(2, 'S', 'stale'), e(1, 'S', 'ok', 'buy')]).map((g) => g.length)).toEqual([1, 1, 1]);
    });
    it('resumen vacío o ausente nunca se agrupa', () => {
        expect(collapseVersionHistory([e(2, ''), e(1, '  ')]).map((g) => g.length)).toEqual([1, 1]);
        expect(collapseVersionHistory([{ version: 2, status: 'a', rating: 'b' }, { version: 1, status: 'a', rating: 'b', diff: null }]).length).toBe(2);
    });
    it('no agrupa no consecutivas aunque coincidan', () => {
        expect(collapseVersionHistory([e(3, 'A'), e(2, 'B'), e(1, 'A')]).length).toBe(3);
    });
    it('vacío -> vacío', () => {
        expect(collapseVersionHistory([])).toEqual([]);
    });
});

describe('versionHistoryBadges', () => {
    const t = (v: string) => v.toUpperCase();
    it('estado siempre; rating solo si es distinto al estado; aviso si cambió', () => {
        expect(versionHistoryBadges({ status: 'ok', rating: 'hold' }, t)).toEqual([{ key: 'status', text: 'OK' }, { key: 'rating', text: 'rating: HOLD' }]);
        expect(versionHistoryBadges({ status: 'x', rating: 'x' }, t)).toEqual([{ key: 'status', text: 'X' }]);
        expect(versionHistoryBadges({ status: 'a', rating: '', diff: { rating_changed: true } }, t).map((b) => b.key)).toEqual(['status', 'rating-change']);
    });
});
