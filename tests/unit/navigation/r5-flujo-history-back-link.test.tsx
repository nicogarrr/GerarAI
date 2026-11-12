import { readFileSync } from 'node:fs';
import path from 'node:path';

import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const back = vi.fn();
const go = vi.fn();
let pathname = '/watchlist';
let search = '';
let navigation: EventTarget & { currentEntry: { key: string; index: number; url: string } };
function emitNavigation(to: string) {
    const index = navigation.currentEntry.index + 1;
    navigation.currentEntry = { key: String(index), index, url: `http://localhost${to}` };
    navigation.dispatchEvent(Object.assign(new Event('currententrychange'), { navigationType: 'push' }));
}
vi.mock('next/navigation', () => ({
    usePathname: () => pathname,
    useSearchParams: () => new URLSearchParams(search),
}));

import { HistoryBackLink, InAppHistoryTracker } from '@/components/common/HistoryBackLink';
import { inAppHistoryStore } from '@/lib/nav/in-app-history';

function navigate(to: string, view: ReturnType<typeof render>) {
    window.history.pushState(null, '', to);
    emitNavigation(to);
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
        go.mockReset();
        window.history.replaceState(null, "", "/");
        vi.spyOn(window.history, "go").mockImplementation(go);
        vi.spyOn(window.history, 'back').mockImplementation(back);
        pathname = '/watchlist';
        search = '';
        navigation = Object.assign(new EventTarget(), { currentEntry: { key: 'origin', index: 0, url: 'http://localhost/watchlist' } });
        vi.stubGlobal('navigation', navigation);
    });
    afterEach(() => {
        inAppHistoryStore.reset();
        vi.restoreAllMocks();
        vi.unstubAllGlobals();
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
        navigation.currentEntry.url = 'http://localhost/research/NVDA?view=valoracion';
        search = 'view=valoracion';
        window.history.replaceState(null, '', `${pathname}${search ? `?${search}` : ''}`);
        const view = render(<Shell />);
        act(() => navigate('/insider?ticker=NVDA', view));
        const link = screen.getByRole('link', { name: '← NVDA' });
        expect(link.getAttribute('data-back-mode')).toBe('history');
        fireEvent.click(link);
        expect(back).toHaveBeenCalledTimes(1);
    });

    it('desde la watchlist: «← NVDA» va a NVDA y el genérico dice «Volver»', () => {
        window.history.replaceState(null, '', `${pathname}${search ? `?${search}` : ''}`);
        const view = render(<Shell />);
        act(() => navigate('/research/NVDA', view));
        expect(screen.getByRole('link', { name: 'Volver' }).getAttribute('data-back-mode')).toBe('history');
        act(() => navigate('/insider?ticker=NVDA', view));
        // La anterior es la ficha: los dos vuelven por historial.
        expect(screen.getByRole('link', { name: '← NVDA' }).getAttribute('data-back-mode')).toBe('history');
    });

    it('watchlist to Research then native hash skips same-page history entries', async () => {
        window.history.replaceState(null, '', `${pathname}${search ? `?${search}` : ''}`);
        const view = render(<Shell />);
        act(() => navigate('/research/MSFT', view));
        act(() => {
            window.history.pushState(null, '', '/research/MSFT#historial-analistas');
            emitNavigation('/research/MSFT#historial-analistas');
        });
        await act(async () => {});
        fireEvent.click(screen.getByRole('link', { name: 'Volver' }));
        expect(go).toHaveBeenCalledWith(-2);
        expect(back).not.toHaveBeenCalled();
    });

    it('Cmd/Ctrl+clic abre el padre como enlace normal', () => {
        pathname = '/research/NVDA';
        navigation.currentEntry.url = 'http://localhost/research/NVDA?view=valoracion';
        window.history.replaceState(null, '', `${pathname}${search ? `?${search}` : ''}`);
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
