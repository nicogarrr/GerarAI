import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { preserveScrollPosition, scrollToIdWhenReady } from '@/lib/utils/scroll-anchor';

// rAF manual: determinista, sin depender de timers.
let rafQueue: FrameRequestCallback[];
let rafId: number;
function stubRaf() {
    rafQueue = [];
    rafId = 0;
    const pending = new Map<number, FrameRequestCallback>();
    vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback) => {
        const id = ++rafId;
        pending.set(id, cb);
        rafQueue.push(cb);
        return id;
    });
    // Fiel al navegador: cancelar elimina el callback pendiente.
    vi.stubGlobal('cancelAnimationFrame', (id: number) => {
        const cb = pending.get(id);
        pending.delete(id);
        if (cb) {
            const i = rafQueue.indexOf(cb);
            if (i !== -1) rafQueue.splice(i, 1);
        }
    });
}
function runRafSteps(n: number) {
    for (let i = 0; i < n; i++) {
        const cb = rafQueue.shift();
        if (!cb) return;
        cb(performance.now());
    }
}

let scrollY = 0;
const scrollTo = vi.fn();

beforeEach(() => {
    scrollY = 0;
    scrollTo.mockClear();
    stubRaf();
    vi.stubGlobal('scrollTo', scrollTo);
    Object.defineProperty(window, 'scrollY', { get: () => scrollY, configurable: true });
});

afterEach(() => {
    vi.unstubAllGlobals();
});

describe('preserveScrollPosition', () => {
    it('llama al trigger de inmediato', () => {
        const trigger = vi.fn();
        preserveScrollPosition(trigger);
        expect(trigger).toHaveBeenCalledTimes(1);
    });

    it('si la página salta durante la retención, devuelve el scroll a su sitio', () => {
        scrollY = 100;
        preserveScrollPosition(() => {});
        scrollY = 150; // el re-render movió la página
        runRafSteps(1);
        expect(scrollTo).toHaveBeenCalledWith(0, 100);
    });

    it('no toca el scroll si no se movió', () => {
        scrollY = 100;
        preserveScrollPosition(() => {});
        runRafSteps(3);
        expect(scrollTo).not.toHaveBeenCalled();
    });

    it('cualquier gesto del usuario cancela la retención al momento', () => {
        scrollY = 100;
        preserveScrollPosition(() => {});
        window.dispatchEvent(new Event('wheel'));
        scrollY = 500;
        runRafSteps(3);
        expect(scrollTo).not.toHaveBeenCalled();
    });

    it('pasado el tiempo máximo deja de retener', () => {
        scrollY = 100;
        preserveScrollPosition(() => {}, 0); // retención ya expirada
        scrollY = 300;
        runRafSteps(3);
        expect(scrollTo).not.toHaveBeenCalled();
    });
});

describe('scrollToIdWhenReady', () => {
    it('hace scroll al elemento cuando aparece', () => {
        const spy = vi.spyOn(Element.prototype, 'scrollIntoView');
        const el = document.createElement('div');
        el.id = 'panel-x';
        document.body.appendChild(el);
        scrollToIdWhenReady('panel-x');
        runRafSteps(1);
        expect(spy).toHaveBeenCalledWith({ block: 'start' });
        el.remove();
    });

    it('espera a que el nodo llegue tras el refresco (no falla si aún no existe)', () => {
        const spy = vi.spyOn(Element.prototype, 'scrollIntoView');
        scrollToIdWhenReady('panel-tardio');
        runRafSteps(1); // aún no existe: reintenta sin error
        const el = document.createElement('div');
        el.id = 'panel-tardio';
        document.body.appendChild(el);
        runRafSteps(1);
        expect(spy).toHaveBeenCalledTimes(1);
        el.remove();
    });

    it('si el elemento no aparece en el tiempo máximo, no hace nada', () => {
        const spy = vi.spyOn(Element.prototype, 'scrollIntoView');
        scrollToIdWhenReady('inexistente', 0);
        runRafSteps(5);
        expect(spy).not.toHaveBeenCalled();
    });
});
