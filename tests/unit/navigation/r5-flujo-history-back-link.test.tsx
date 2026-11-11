import { readFileSync } from 'node:fs';
import path from 'node:path';

import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const back = vi.fn();
let pathname = '/watchlist';
let search = '';
vi.mock('next/navigation', () => ({
    usePathname: () => pathname,
    useSearchParams: () => new URLSearchParams(search),
}));

import { HistoryBackLink, InAppHistoryTracker } from '@/components/common/HistoryBackLink';
import { inAppHistoryStore } from '@/lib/nav/in-app-history';

function navigate(to: string, view: ReturnType<typeof render>) {
    const [p, q = ''] = to.split('?');
    pathname = p;
    search = q;
    view.rerender(<Shell />);
}

function Shell() {
    return (
        <>
            <InAppHistoryTracker />
            <HistoryBackLink href="/research/NVDA">← NVDA</HistoryBackLink>
            <HistoryBackLink href="/research" sameDestinationOnly={false} historyChildren="Volver">Research</HistoryBackLink>
        </>
    );
}

describe('HistoryBackLink en el flujo real', () => {
    beforeEach(() => {
        inAppHistoryStore.reset();
        back.mockReset();
        vi.spyOn(window.history, 'back').mockImplementation(back);
        pathname = '/watchlist';
        search = '';
    });
    afterEach(() => {
        inAppHistoryStore.reset();
        vi.restoreAllMocks();
    });

    it('abierta directamente: enlace normal al padre', () => {
        pathname = '/insider';
        search = 'ticker=NVDA';
        render(<Shell />);
        const link = screen.getByRole('link', { name: '← NVDA' });
        expect(link.getAttribute('href')).toBe('/research/NVDA');
        expect(link.getAttribute('data-back-mode')).toBe('link');
        expect(screen.getByRole('link', { name: 'Research' })).toBeTruthy();
        fireEvent.click(link);
        expect(back).not.toHaveBeenCalled();
    });

    it('desde la ficha (?view=valoracion): vuelve por historial, sin perder la pestaña', () => {
        pathname = '/research/NVDA';
        search = 'view=valoracion';
        const view = render(<Shell />);
        act(() => navigate('/insider?ticker=NVDA', view));
        const link = screen.getByRole('link', { name: '← NVDA' });
        expect(link.getAttribute('data-back-mode')).toBe('history');
        fireEvent.click(link);
        expect(back).toHaveBeenCalledTimes(1);
    });

    it('desde la watchlist: «← NVDA» va a NVDA y el genérico dice «Volver»', () => {
        const view = render(<Shell />);
        act(() => navigate('/research/NVDA', view));
        expect(screen.getByRole('link', { name: 'Volver' }).getAttribute('data-back-mode')).toBe('history');
        act(() => navigate('/insider?ticker=NVDA', view));
        // La anterior es la ficha: los dos vuelven por historial.
        expect(screen.getByRole('link', { name: '← NVDA' }).getAttribute('data-back-mode')).toBe('history');
    });

    it('Cmd/Ctrl+clic abre el padre como enlace normal', () => {
        pathname = '/research/NVDA';
        const view = render(<Shell />);
        act(() => navigate('/insider?ticker=NVDA', view));
        fireEvent.click(screen.getByRole('link', { name: '← NVDA' }), { metaKey: true });
        expect(back).not.toHaveBeenCalled();
    });
});

describe('los enlaces «volver» del flujo usan HistoryBackLink', () => {
    const root = process.cwd();
    const read = (p: string) => readFileSync(path.join(root, p), 'utf8');

    it('el layout autenticado monta el tracker', () => {
        expect(read('app/(root)/layout.tsx')).toMatch(/<InAppHistoryTracker \/>/);
    });

    it.each([
        'app/(root)/research/[ticker]/page.tsx',
        'app/(root)/research/news/page.tsx',
        'app/(root)/insider/page.tsx',
        'app/(root)/corporate-actions/page.tsx',
        'app/(root)/research/[ticker]/tesis/page.tsx',
        'app/(root)/screeners/[screenId]/page.tsx',
        'app/(root)/research/sources/page.tsx',
    ])('%s', (file) => {
        const src = read(file);
        expect(src).toMatch(/<HistoryBackLink\b/);
        // Ningún «← …» de vuelta queda como <Link> fijo.
        expect(src).not.toMatch(/<Link[^>]*>\s*<ArrowLeft/);
    });
});
