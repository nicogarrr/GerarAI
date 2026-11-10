import { act, fireEvent, render, screen } from '@testing-library/react';
import { renderToString } from 'react-dom/server';
import { afterAll, afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import MobileNav from '@/components/MobileNav';
import BottomNav from '@/components/layout/BottomNav';
import { LibraryChat } from '@/app/(root)/inversores/_components/LibraryChat';
import { EARLY_OPEN_CAPTURE_JS, EARLY_OPEN_NAV_KEY, consumeEarlyNavOpen } from '@/lib/early-open';
import { OPEN_BRAIN_PENDING_KEY, markBrainReady } from '@/lib/brain/open-brain';

vi.mock('next/navigation', () => ({ usePathname: () => '/inicio', useRouter: () => ({ push: vi.fn(), prefetch: vi.fn(), refresh: vi.fn() }) }));
vi.mock('@/lib/actions/finnhub.actions', () => ({ searchStocksWithStatus: vi.fn(async () => []), getPopularStocks: vi.fn(async () => []) }));
vi.mock('@/lib/popular-stocks-loader', () => ({ loadPopularStocks: vi.fn(async () => []) }));

// Execute the exact inline source once, as the initial HTML does. All tests
// click real SSR/component output, not synthetic hand-written buttons.
window.eval(EARLY_OPEN_CAPTURE_JS);
afterEach(() => { document.querySelectorAll('[data-ssr-test]').forEach((el) => el.remove()); });
beforeEach(() => {
    sessionStorage.clear();
    markBrainReady(false);
    vi.stubGlobal('matchMedia', vi.fn((media: string) => ({ matches: false, media, addEventListener: vi.fn(), removeEventListener: vi.fn() })));
});
afterAll(async () => { await import('@/components/SearchCommandDialog'); });

function ssr(tree: React.ReactNode) {
    const host = document.createElement('div');
    host.setAttribute('data-ssr-test', '');
    host.innerHTML = renderToString(tree);
    document.body.append(host);
    return host;
}

describe('initial HTML clicks before React hydration', () => {
    it('retains a real SSR hamburger click and opens the real drawer on mount', async () => {
        const html = ssr(<MobileNav />);
        fireEvent.click(html.querySelector('svg')!);
        expect(sessionStorage.getItem(EARLY_OPEN_NAV_KEY)).toBe('1');
        html.remove();
        render(<MobileNav />);
        expect(await screen.findByRole('dialog', { name: 'Menú de navegación' })).toBeVisible();
        expect(sessionStorage.getItem(EARLY_OPEN_NAV_KEY)).toBeNull();
        fireEvent.keyDown(document, { key: 'Escape' });
        expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
        expect(consumeEarlyNavOpen()).toBe(false);
    });
    it('retains a real SSR brain click when GlobalBrain is not listening yet', () => {
        const html = ssr(<BottomNav />);
        fireEvent.click(html.querySelector('button img')!);
        expect(sessionStorage.getItem(OPEN_BRAIN_PENDING_KEY)).toBe('null');
        html.remove();
    });
    it('dispatches once when GlobalBrain is ready but BottomNav is not hydrated', () => {
        markBrainReady(true);
        const listener = vi.fn();
        window.addEventListener('gerarai:open-brain', listener);
        const html = ssr(<BottomNav />);
        fireEvent.click(html.querySelector('button')!);
        expect(listener).toHaveBeenCalledOnce();
        expect(sessionStorage.getItem(OPEN_BRAIN_PENDING_KEY)).toBeNull();
        html.remove();
        window.removeEventListener('gerarai:open-brain', listener);
    });
    it('leaves hydrated clicks to React without retaining a second opening', async () => {
        render(<MobileNav />);
        await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Abrir menú de navegación' })); });
        expect(await screen.findByRole('dialog', { name: 'Menú de navegación' })).toBeVisible();
        expect(sessionStorage.getItem(EARLY_OPEN_NAV_KEY)).toBeNull();
    });
    it('hydrated BottomNav still retains the intent if GlobalBrain mounts later', () => {
        render(<BottomNav />);
        fireEvent.click(screen.getByRole('button', { name: 'Abrir el cerebro' }));
        expect(sessionStorage.getItem(OPEN_BRAIN_PENDING_KEY)).toBe('null');
    });
    it('hydrated BottomNav dispatches only once when the listener is ready', () => {
        markBrainReady(true);
        const listener = vi.fn();
        window.addEventListener('gerarai:open-brain', listener);
        render(<BottomNav />);
        fireEvent.click(screen.getByRole('button', { name: 'Abrir el cerebro' }));
        expect(listener).toHaveBeenCalledOnce();
        expect(sessionStorage.getItem(OPEN_BRAIN_PENDING_KEY)).toBeNull();
        window.removeEventListener('gerarai:open-brain', listener);
    });
    it('preloads the real drawer on pointer intent and focus', () => {
        render(<MobileNav />);
        const trigger = screen.getByRole('button', { name: 'Abrir menú de navegación' });
        fireEvent.pointerDown(trigger);
        fireEvent.focus(trigger);
        expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });
    it('has no pending navigation on the server', () => {
        vi.stubGlobal('window', undefined);
        expect(consumeEarlyNavOpen()).toBe(false);
        vi.unstubAllGlobals();
    });
    it('a hydrated LibraryChat click goes to React alone: nothing retained, no replay', () => {
        // Mata el mutante data-hydrated="0": con la captura global activa, un
        // marcador falso dejaría la intención en sessionStorage y GlobalBrain
        // abriría el panel una segunda vez al montar.
        markBrainReady(true);
        const listener = vi.fn();
        window.addEventListener('gerarai:open-brain', listener);
        render(<LibraryChat scope="library" authors={['Buffett']} />);
        const button = screen.getByRole('button', { name: 'Preguntar a la biblioteca' });
        fireEvent.click(button);
        expect(listener).toHaveBeenCalledOnce();
        expect(sessionStorage.getItem(OPEN_BRAIN_PENDING_KEY)).toBeNull();
        // El detalle con el contexto biblioteca llega intacto al evento.
        expect((listener.mock.calls[0][0] as CustomEvent).detail).toEqual({ knowledge: { scope: 'library', authors: ['Buffett'] } });
        window.removeEventListener('gerarai:open-brain', listener);
    });
    it('storage denial does not crash either capture or consumer', () => {
        vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('denied'); });
        vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('denied'); });
        const html = ssr(<><MobileNav /><BottomNav /></>);
        for (const button of html.querySelectorAll('button')) expect(() => fireEvent.click(button)).not.toThrow();
        for (const button of html.querySelectorAll('button')) expect(button).not.toHaveAttribute('aria-expanded', 'true');
        expect(consumeEarlyNavOpen()).toBe(false);
        html.remove();
    });
});
