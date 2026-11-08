import { describe, expect, it } from 'vitest';

import { newsBadge } from '@/lib/newsBadge';

// F149: article.related es la compañía que menciona el proveedor, NO una
// tenencia. La insignia «holding» solo sale si el ticker está entre los
// símbolos reales del usuario.

describe('newsBadge', () => {
    it('sin related: insignia general', () => {
        expect(newsBadge({})).toEqual({ kind: 'general' });
        expect(newsBadge({ related: null })).toEqual({ kind: 'general' });
        expect(newsBadge({ related: '  ' })).toEqual({ kind: 'general' });
    });

    it('ticker mencionado que el usuario tiene en cartera: holding', () => {
        expect(newsBadge({ related: 'aapl' }, ['MSFT', 'AAPL'])).toEqual({ kind: 'holding', ticker: 'AAPL' });
    });

    it('ticker mencionado fuera de la cartera: mentioned, nunca holding', () => {
        expect(newsBadge({ related: 'TSLA' }, ['MSFT', 'AAPL'])).toEqual({ kind: 'mentioned', ticker: 'TSLA' });
        expect(newsBadge({ related: 'TSLA' })).toEqual({ kind: 'mentioned', ticker: 'TSLA' });
    });

    it('compara sin distinguir mayúsculas ni espacios', () => {
        expect(newsBadge({ related: ' tsla ' }, [' tsla'])).toEqual({ kind: 'holding', ticker: 'TSLA' });
    });
});
