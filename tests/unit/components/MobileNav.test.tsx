import { GlobalBrain } from '@/components/brain/GlobalBrain';
import { markBrainReady, OPEN_BRAIN_PENDING_KEY } from '@/lib/brain/open-brain';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterAll, afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

// El shell real consume el handoff; el panel de chat tiene su suite propia.
vi.mock('@/components/brain/GlobalBrainPanel', () => ({
    GlobalBrainPanel: ({ openDetail }: { openDetail: { seq: number } | null }) =>
        <div role="dialog" aria-label="Cerebro de prueba" data-open-seq={openDetail?.seq} />,
}));

afterEach(() => {
    markBrainReady(false);
    window.sessionStorage.removeItem(OPEN_BRAIN_PENDING_KEY);
});

vi.mock('next/navigation', () => ({
    usePathname: () => '/inicio',
    useRouter: () => ({ push: vi.fn(), prefetch: vi.fn(), refresh: vi.fn() }),
}));
vi.mock('@/lib/actions/finnhub.actions', () => ({
    searchStocksWithStatus: vi.fn(async () => []),
    getPopularStocks: vi.fn(async () => []),
}));
vi.mock('@/lib/popular-stocks-loader', () => ({ loadPopularStocks: vi.fn(async () => []) }));

import MobileNav from '@/components/MobileNav';

// El drawer contiene el gatillo real del buscador (SearchCommand): su
// onFocus precarga el chunk de SearchCommandDialog (TickerSearchInput ->
// finnhub.actions) con un import() fire-and-forget, y los tests enfocan los
// botones del drawer. Si ese chunk sigue cargando cuando el archivo termina,
// Vitest reporta EnvironmentTeardownError como error no manejado y la run
// falla con todos los tests en verde (visto en CI, #3992/#3995). Drenar el
// chunk antes del teardown lo evita.
afterAll(async () => {
    await import('@/components/SearchCommandDialog');
});

beforeEach(() => {
    markBrainReady(false);
    window.sessionStorage.removeItem(OPEN_BRAIN_PENDING_KEY);
    vi.stubGlobal('matchMedia', vi.fn().mockImplementation((query: string) => ({
        matches: false, media: query, addEventListener: vi.fn(), removeEventListener: vi.fn(),
    })));
});

async function openDrawer() {
    fireEvent.click(screen.getByRole('button', { name: 'Abrir menú de navegación' }));
    // El drawer llega en chunk diferido (next/dynamic): se espera a que monte.
    await screen.findByRole('dialog', { name: 'Menú de navegación' });
}

function dialogEl(): HTMLDialogElement {
    return screen.getByRole('dialog', { name: 'Menú de navegación' }) as HTMLDialogElement;
}

describe('MobileNav (dialog nativo)', () => {
    it('el hamburger abre un <dialog> nativo modal con el MISMO árbol que el sidebar', async () => {
        render(<MobileNav />);
        await openDrawer();
        const dialog = dialogEl();
        // Nativo: sin role="dialog" ni aria-modal escritos a mano (los aporta
        // el elemento) y abierto como modal (showModal), no con el atributo open.
        expect(dialog.tagName).toBe('DIALOG');
        expect(dialog).not.toHaveAttribute('role');
        expect(dialog).not.toHaveAttribute('aria-modal');
        expect(dialog).toHaveAttribute('aria-labelledby', 'mobile-nav-title');
        expect(dialog.open).toBe(true);
        expect(dialog).toHaveAttribute('closedby', 'any');
        expect(screen.getByRole('link', { name: 'Cartera' })).toBeInTheDocument();
        expect(screen.getByRole('link', { name: 'Biblioteca' })).toBeInTheDocument();
    });

    it('no bloquea el scroll del body (ni al abrir ni al cerrar)', async () => {
        render(<MobileNav />);
        await openDrawer();
        // Guia dialog: sin modificar el scrollbar raíz; la contención de scroll
        // por CSS es progresiva y no está verificada en Safari.
        expect(document.body.style.overflow).toBe('');
        fireEvent(dialogEl(), new Event('cancel'));
        act(() => { dialogEl().close(); });
        expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
        expect(document.body.style.overflow).toBe('');
    });

    it('Escape (cancel nativo) cierra a traves del evento close', async () => {
        render(<MobileNav />);
        await openDrawer();
        // En el navegador Escape dispara cancel y, si no se previene, close.
        // jsdom no implementa ese paso UA: se reproduce la secuencia.
        fireEvent(dialogEl(), new Event('cancel', { cancelable: true }));
        act(() => { dialogEl().close(); });
        expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });

    it('el botón de cerrar recibe el foco al abrir', async () => {
        render(<MobileNav />);
        await openDrawer();
        expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Cerrar menú de navegación' }));
    });

    it('cierre por fondo (fallback de closedby="any" donde no existe, p.ej. Safari)', async () => {
        render(<MobileNav />);
        await openDrawer();
        const dialog = dialogEl();
        // jsdom no tiene layout: se fija un rectangulo para el calculo de
        // dentro/fuera (la guia pide medir posicion del puntero, no el target).
        vi.spyOn(dialog, 'getBoundingClientRect').mockReturnValue({
            left: 0, right: 300, top: 0, bottom: 800, width: 300, height: 800, x: 0, y: 0, toJSON: () => ({}),
        } as DOMRect);
        fireEvent(dialog, new MouseEvent('pointerdown', { bubbles: true, clientX: 350, clientY: 400 }));
        fireEvent(dialog, new MouseEvent('pointerup', { bubbles: true, clientX: 350, clientY: 400 }));
        expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });

    it('un clic DENTRO del panel no cierra (target del padding no cierra)', async () => {
        render(<MobileNav />);
        await openDrawer();
        const dialog = dialogEl();
        vi.spyOn(dialog, 'getBoundingClientRect').mockReturnValue({
            left: 0, right: 300, top: 0, bottom: 800, width: 300, height: 800, x: 0, y: 0, toJSON: () => ({}),
        } as DOMRect);
        fireEvent(dialog, new MouseEvent('pointerdown', { bubbles: true, clientX: 150, clientY: 400 }));
        fireEvent(dialog, new MouseEvent('pointerup', { bubbles: true, clientX: 150, clientY: 400 }));
        expect(screen.getByRole('dialog', { name: 'Menú de navegación' })).toBeInTheDocument();
        // Y un arrastre que empieza fuera pero suelta dentro tampoco.
        fireEvent(dialog, new MouseEvent('pointerdown', { bubbles: true, clientX: 350, clientY: 400 }));
        fireEvent(dialog, new MouseEvent('pointerup', { bubbles: true, clientX: 150, clientY: 400 }));
        expect(screen.getByRole('dialog', { name: 'Menú de navegación' })).toBeInTheDocument();
    });
});

describe('MobileNav (handoffs y breakpoints)', () => {
    function stubMatchMedia(matches = false) {
        const listeners: Record<string, EventListener[]> = {};
        vi.stubGlobal('matchMedia', vi.fn().mockImplementation((query: string) => ({
            matches, media: query,
            addEventListener: (ev: string, cb: EventListener) => { (listeners[ev] ??= []).push(cb); },
            removeEventListener: vi.fn(),
        })));
        return listeners;
    }

    it.each([true, false])('el botón Cerebro cierra el drawer y entrega la apertura (ready=%s)', async (ready) => {
        markBrainReady(ready);
        const onBrain = vi.fn();
        window.addEventListener('gerarai:open-brain', onBrain);
        const entry = render(<MobileNav />);
        await openDrawer();
        fireEvent.click(screen.getByRole('button', { name: /Cerebro/ }));
        expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
        expect(onBrain).toHaveBeenCalledTimes(ready ? 1 : 0);
        expect(window.sessionStorage.getItem(OPEN_BRAIN_PENDING_KEY)).toBe(ready ? null : 'null');
        if (!ready) {
            entry.unmount();
            const brain = render(<GlobalBrain userId="u1" />);
            expect(await screen.findByRole('dialog', { name: 'Cerebro de prueba' })).toHaveAttribute('data-open-seq', '1');
            expect(window.sessionStorage.getItem(OPEN_BRAIN_PENDING_KEY)).toBeNull();
            expect(onBrain).not.toHaveBeenCalled();
            brain.unmount();
            render(<GlobalBrain userId="u1" />);
            expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
        }
        window.removeEventListener('gerarai:open-brain', onBrain);
    });

    it('pulsar un enlace del árbol cierra el drawer', async () => {
        render(<MobileNav />);
        await openDrawer();
        fireEvent.click(screen.getByRole('link', { name: 'Cartera' }));
        expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });

    it('cruzar a md+ con el drawer abierto lo cierra (modal nativo invisible no puede quedar activo)', async () => {
        const listeners = stubMatchMedia(false);
        render(<MobileNav />);
        await openDrawer();
        expect(dialogEl().open).toBe(true);
        vi.mocked(window.matchMedia).mock.results[0].value.matches = true;
        act(() => { for (const cb of listeners['change'] ?? []) cb(new Event('change')); });
        expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });
});
