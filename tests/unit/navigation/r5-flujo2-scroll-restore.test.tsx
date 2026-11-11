import { act, render } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

let pathname = '/research/NVDA';
let search = 'view=valoracion';
vi.mock('next/navigation', () => ({
    usePathname: () => pathname,
    useSearchParams: () => new URLSearchParams(search),
}));

import { ScrollPreserver } from '@/components/layout/ScrollPreserver';
import { RESTORE_TIMEOUT_MS, SCROLL_MEMORY_KEY, readScrollMemory, rememberScroll, restoreStep } from '@/lib/nav/scroll-memory';

/**
 * Auditoría de flujo r5 (11-nov): tras bajar por la ficha, volver por
 * historial («← Volver a NVDA» o el atrás del navegador desde el Informe)
 * dejaba la ficha arriba o en un sitio que no era el del usuario.
 * jsdom no hace layout: se simulan scrollY, la altura del documento y los
 * fotogramas a mano.
 */
let scrollY = 0;
let docHeight = 4000;
const viewport = 844;
let rafQueue: FrameRequestCallback[] = [];

function flushFrames(n = 1) {
    for (let i = 0; i < n; i++) {
        const queue = rafQueue;
        rafQueue = [];
        act(() => {
            for (const cb of queue) cb(performance.now());
        });
    }
}

function userScrollsTo(y: number) {
    act(() => {
        window.dispatchEvent(new WheelEvent('wheel'));
        scrollY = y;
        window.dispatchEvent(new Event('scroll'));
    });
    flushFrames();
}

function go(url: string, view: ReturnType<typeof render>) {
    const [p, q = ''] = url.split('?');
    pathname = p;
    search = q;
    view.rerender(<ScrollPreserver />);
}

beforeEach(() => {
    sessionStorage.clear();
    pathname = '/research/NVDA';
    search = 'view=valoracion';
    scrollY = 0;
    docHeight = 4000;
    rafQueue = [];
    Object.defineProperty(window, 'scrollY', { configurable: true, get: () => scrollY });
    Object.defineProperty(window, 'innerHeight', { configurable: true, value: viewport });
    Object.defineProperty(document.documentElement, 'scrollHeight', { configurable: true, get: () => docHeight });
    vi.spyOn(window, 'scrollTo').mockImplementation(((_x: number, y: number) => {
        scrollY = Math.min(y, Math.max(0, docHeight - viewport));
    }) as typeof window.scrollTo);
    vi.spyOn(window, 'requestAnimationFrame').mockImplementation((cb) => {
        rafQueue.push(cb);
        return rafQueue.length;
    });
    vi.spyOn(window, 'cancelAnimationFrame').mockImplementation(() => {});
});

afterEach(() => {
    vi.restoreAllMocks();
});

function clickLink(href: string) {
    const a = document.createElement('a');
    a.setAttribute('href', href);
    document.body.appendChild(a);
    act(() => {
        a.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true }));
    });
    a.remove();
}

describe('ScrollPreserver: volver por historial', () => {
    it('«Volver» desde una subpágina deja la ficha donde estaba, aunque la ficha llegue tarde', () => {
        const view = render(<ScrollPreserver />);
        userScrollsTo(900);
        // Menú «Más acciones» → Insiders.
        clickLink('/insider?ticker=NVDA');
        // La página nueva es corta: el navegador recorta scrollY a 0 antes
        // de que la URL cambie (eso guardaba el navegador).
        docHeight = 900;
        act(() => {
            scrollY = 0;
            window.dispatchEvent(new Event('scroll'));
        });
        flushFrames();
        go('/insider?ticker=NVDA', view);
        flushFrames(2);
        // «← Volver a NVDA» = history.back(): popstate y la ficha vuelve
        // por streaming (aún corta).
        act(() => {
            window.dispatchEvent(new PopStateEvent('popstate'));
        });
        go('/research/NVDA?view=valoracion', view);
        flushFrames(3);
        expect(scrollY).toBe(56); // tope del documento corto: 900 − 844
        // Llega el resto de la ficha.
        docHeight = 5000;
        flushFrames(8);
        expect(scrollY).toBe(900);
    });

    it('el atrás del navegador vuelve a la posición del usuario, no a la que dejó recortada la página siguiente', () => {
        const view = render(<ScrollPreserver />);
        userScrollsTo(1200);
        clickLink('/research/NVDA/informe');
        act(() => {
            scrollY = 1525; // la página nueva (Informe) mueve el scroll antes de cambiar la URL
            window.dispatchEvent(new Event('scroll'));
        });
        flushFrames();
        go('/research/NVDA/informe', view);
        flushFrames(2);
        userScrollsTo(300);
        act(() => {
            window.dispatchEvent(new PopStateEvent('popstate'));
        });
        go('/research/NVDA?view=valoracion', view);
        flushFrames(10);
        expect(scrollY).toBe(1200);
        // Y el Informe recuerda su propia posición si se vuelve adelante.
        expect(readScrollMemory(sessionStorage)['/research/NVDA/informe']).toBe(300);
    });

    it('si el usuario hace scroll mientras se restaura, manda él', () => {
        const view = render(<ScrollPreserver />);
        userScrollsTo(900);
        clickLink('/insider?ticker=NVDA');
        go('/insider?ticker=NVDA', view);
        flushFrames(2);
        docHeight = 900;
        act(() => {
            window.dispatchEvent(new PopStateEvent('popstate'));
        });
        go('/research/NVDA?view=valoracion', view);
        flushFrames(2);
        act(() => {
            window.dispatchEvent(new Event('touchstart'));
            scrollY = 10;
        });
        docHeight = 5000;
        flushFrames(8);
        expect(scrollY).toBe(10);
    });

    it('navegar hacia delante a otra ruta no restaura nada', () => {
        sessionStorage.setItem(SCROLL_MEMORY_KEY, JSON.stringify({ '/watchlist': 700 }));
        const view = render(<ScrollPreserver />);
        userScrollsTo(400);
        clickLink('/watchlist');
        go('/watchlist', view);
        flushFrames(5);
        expect(window.scrollTo).not.toHaveBeenCalled();
    });

    it('pestañas de la misma ficha: se conserva la posición (comportamiento previo)', () => {
        const view = render(<ScrollPreserver />);
        userScrollsTo(450);
        clickLink('/research/NVDA?view=tesis');
        act(() => {
            scrollY = 0; // loading.tsx colapsa el documento
        });
        go('/research/NVDA?view=tesis', view);
        flushFrames(2);
        expect(scrollY).toBe(450);
    });
});

describe('scroll-memory', () => {
    it('restoreStep espera a que el documento mida lo bastante y a que la posición aguante', () => {
        expect(restoreStep({ target: 900, y: 0, maxY: 300, stableFrames: 0, elapsedMs: 10 })).toEqual({ kind: 'scroll', to: 300, stableFrames: 0 });
        expect(restoreStep({ target: 900, y: 900, maxY: 2000, stableFrames: 4, elapsedMs: 50 })).toEqual({ kind: 'done' });
        expect(restoreStep({ target: 900, y: 300, maxY: 300, stableFrames: 0, elapsedMs: RESTORE_TIMEOUT_MS })).toEqual({ kind: 'give-up' });
    });

    it('rememberScroll guarda la más reciente y limita las entradas', () => {
        let m = {};
        for (let i = 0; i < 60; i++) m = rememberScroll(m, `/p${i}`, i);
        expect(Object.keys(m)).toHaveLength(50);
        expect(m).not.toHaveProperty('/p0');
        expect(readScrollMemory({ getItem: () => '{"a":"x","b":12}', setItem: () => {} })).toEqual({ b: 12 });
    });
});
