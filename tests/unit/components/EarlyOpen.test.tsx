import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { renderToString } from 'react-dom/server';
import { afterAll, afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import MobileNav from '@/components/MobileNav';
import BottomNav from '@/components/layout/BottomNav';
import { LibraryChat } from '@/app/(root)/inversores/_components/LibraryChat';
import { ThemeBrainButton } from '@/app/(root)/temas/_components/ThemeBrainButton';
import BrainAskForm from '@/components/research/BrainAskForm';
import { ChangesFeed } from '@/components/research/ChangesFeed';
import { ChatIntentLinks } from '@/components/research/ChatIntentLinks';
import { GuideBrainButton } from '@/components/research/GuideBrainButton';
import { GuideContextPanel } from '@/components/research/GuideContextPanel';
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

const themeQuestion = '¿Cómo gana dinero la fusión de energía?';
const intents = [
    ['Entender', '¿Qué hace BRK.B, cómo gana dinero y qué hechos y cálculos hay registrados sobre la empresa?'],
    ['Revisar supuestos', '¿Qué supuestos e hipótesis sostienen la tesis de BRK.B y qué evidencia tiene cada uno?'],
    ['Cuestionar', '¿Qué contradicciones, datos insuficientes y evidencia en contra hay registrados sobre BRK.B?'],
];
const change = (id: number) => ({
    id, company_id: 1, from_version_id: null, to_version_id: null, change_type: 'news_material_update', impact_direction: 'positive',
    materiality_score: 60, summary: `Suceso ${id}`, affected_claim_ids: [], affected_metrics: [], requires_review: false,
    created_at: `2026-10-${String(id % 28 + 1).padStart(2, '0')}T10:00:00Z`, updated_at: '',
});
const openReview = { id: 7, title: 'Revisar guía', summary: '', status: 'open', thesis_change_id: 1, news_event_id: null, created_at: '2026-10-02T00:00:00Z' };

describe('brain entries in the initial HTML', () => {
    it('retains an SSR ThemeBrainButton click with its analysis question', () => {
        const html = ssr(<ThemeBrainButton question={themeQuestion} />);
        const button = within(html).getByRole('button', { name: 'Analizar el tema' });
        expect(button).toHaveAttribute('data-early-open', 'brain');
        expect(button).toHaveAttribute('data-early-open-detail', JSON.stringify({ question: themeQuestion }));
        fireEvent.click(button);
        expect(sessionStorage.getItem(OPEN_BRAIN_PENDING_KEY)).toBe(JSON.stringify({ question: themeQuestion }));
        html.remove();
    });
    it('retains an SSR GuideBrainButton click with the ticker', () => {
        const html = ssr(<GuideBrainButton ticker="ASTS" />);
        const button = within(html).getByRole('button', { name: 'Guía de investigación' });
        expect(button).toHaveAttribute('data-early-open', 'brain');
        fireEvent.click(button);
        expect(sessionStorage.getItem(OPEN_BRAIN_PENDING_KEY)).toBe(JSON.stringify({ ticker: 'ASTS' }));
        html.remove();
    });
    it.each(intents)('retains an SSR %s intent click with its exact question', (label, question) => {
        const html = ssr(<ChatIntentLinks ticker="BRK.B" />);
        const button = within(html).getByRole('button', { name: label });
        expect(button).toHaveAttribute('data-early-open', 'brain');
        fireEvent.click(button);
        expect(JSON.parse(sessionStorage.getItem(OPEN_BRAIN_PENDING_KEY)!)).toEqual({ ticker: 'BRK.B', question });
        html.remove();
    });
    it('retains an SSR ask-form submit without a native form reload', () => {
        const html = ssr(<BrainAskForm ticker="ASTS" />);
        const submit = within(html).getByRole('button', { name: 'Preguntar' });
        expect(submit).toHaveAttribute('data-early-open', 'brain');
        // preventDefault frena el submit nativo aún sin onSubmit hidratado.
        expect(fireEvent.click(submit)).toBe(false);
        // La pregunta tecleada no existe en el servidor: se retiene solo el ticker.
        expect(sessionStorage.getItem(OPEN_BRAIN_PENDING_KEY)).toBe(JSON.stringify({ ticker: 'ASTS' }));
        html.remove();
    });
    it('retains an SSR guide review click with its review anchor', () => {
        const context = { ticker: 'ASTS', review_id: null, open_reviews: [{ id: 7, status: 'open', summary: 'Revisar guía' }], latest_news: [], missing_data: [] };
        const html = ssr(<GuideContextPanel ticker="ASTS" context={context} />);
        const button = within(html).getByRole('button', { name: 'Preguntar al Cerebro' });
        expect(button).toHaveAttribute('data-early-open', 'brain');
        fireEvent.click(button);
        expect(sessionStorage.getItem(OPEN_BRAIN_PENDING_KEY)).toBe(JSON.stringify({ ticker: 'ASTS', review_id: 7 }));
        html.remove();
    });
    it('retains an SSR ChangesFeed open-review click with its review anchor', () => {
        const html = ssr(<ChangesFeed alerts={[]} changes={[change(1), change(2)]} reviews={[openReview]} ticker="ASTS" />);
        const button = within(html).getByRole('button', { name: 'Abrir en el Cerebro' });
        expect(button).toHaveAttribute('data-early-open', 'brain');
        fireEvent.click(button);
        expect(sessionStorage.getItem(OPEN_BRAIN_PENDING_KEY)).toBe(JSON.stringify({ ticker: 'ASTS', review_id: 7 }));
        html.remove();
    });
    it('stores a bare null when the retained detail is not a JSON object', () => {
        const html = ssr(<GuideBrainButton ticker="ASTS" />);
        const button = within(html).getByRole('button', { name: 'Guía de investigación' });
        button.setAttribute('data-early-open-detail', '{not json');
        fireEvent.click(button);
        expect(sessionStorage.getItem(OPEN_BRAIN_PENDING_KEY)).toBe('null');
        sessionStorage.removeItem(OPEN_BRAIN_PENDING_KEY);
        button.setAttribute('data-early-open-detail', '[1,2]');
        fireEvent.click(button);
        expect(sessionStorage.getItem(OPEN_BRAIN_PENDING_KEY)).toBe('null');
        html.remove();
    });
    it('dispatches the parsed detail at once when GlobalBrain is already listening', () => {
        markBrainReady(true);
        const listener = vi.fn();
        window.addEventListener('gerarai:open-brain', listener);
        const html = ssr(<ThemeBrainButton question={themeQuestion} />);
        fireEvent.click(within(html).getByRole('button', { name: 'Analizar el tema' }));
        expect(listener).toHaveBeenCalledOnce();
        expect((listener.mock.calls[0][0] as CustomEvent).detail).toEqual({ question: themeQuestion });
        expect(sessionStorage.getItem(OPEN_BRAIN_PENDING_KEY)).toBeNull();
        html.remove();
        window.removeEventListener('gerarai:open-brain', listener);
    });
    it('a hydrated GuideBrainButton click goes to React alone: nothing retained, no replay', () => {
        // Mata el mutante data-hydrated="0": con la captura global activa, un
        // marcador falso interceptaría el clic antes de que llegue a React.
        markBrainReady(true);
        const listener = vi.fn();
        window.addEventListener('gerarai:open-brain', listener);
        render(<GuideBrainButton ticker="ASTS" />);
        const button = screen.getByRole('button', { name: 'Guía de investigación' });
        expect(button).toHaveAttribute('data-hydrated', '1');
        fireEvent.click(button);
        expect(listener).toHaveBeenCalledOnce();
        expect((listener.mock.calls[0][0] as CustomEvent).detail).toEqual({ ticker: 'ASTS' });
        expect(sessionStorage.getItem(OPEN_BRAIN_PENDING_KEY)).toBeNull();
        window.removeEventListener('gerarai:open-brain', listener);
    });
    it('a hydrated ThemeBrainButton click goes to React alone: nothing retained, no replay', () => {
        markBrainReady(true);
        const listener = vi.fn();
        window.addEventListener('gerarai:open-brain', listener);
        render(<ThemeBrainButton question={themeQuestion} />);
        const button = screen.getByRole('button', { name: 'Analizar el tema' });
        expect(button).toHaveAttribute('data-hydrated', '1');
        fireEvent.click(button);
        expect(listener).toHaveBeenCalledOnce();
        expect((listener.mock.calls[0][0] as CustomEvent).detail).toEqual({ question: themeQuestion });
        expect(sessionStorage.getItem(OPEN_BRAIN_PENDING_KEY)).toBeNull();
        window.removeEventListener('gerarai:open-brain', listener);
    });
    it('a hydrated BrainAskForm sends the typed question and retains nothing', () => {
        markBrainReady(true);
        const listener = vi.fn();
        window.addEventListener('gerarai:open-brain', listener);
        const { container } = render(<BrainAskForm ticker="ASTS" />);
        fireEvent.change(screen.getByRole('textbox', { name: 'Pregunta sobre ASTS' }), { target: { value: '¿Qué riesgos tiene ASTS?' } });
        fireEvent.submit(container.querySelector('form')!);
        expect(listener).toHaveBeenCalledOnce();
        expect((listener.mock.calls[0][0] as CustomEvent).detail).toEqual({ ticker: 'ASTS', question: '¿Qué riesgos tiene ASTS?' });
        expect(sessionStorage.getItem(OPEN_BRAIN_PENDING_KEY)).toBeNull();
        window.removeEventListener('gerarai:open-brain', listener);
    });
});
