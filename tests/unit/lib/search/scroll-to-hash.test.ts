// @vitest-environment node
import { describe, expect, it, vi } from 'vitest';
import { hashFromHref, scrollToHashAnchor } from '@/lib/search/scroll-to-hash';

describe('hashFromHref', () => {
    it('extrae y decodifica el ancla', () => {
        expect(hashFromHref('/research/MSFT?v=1#grafico')).toBe('grafico');
        expect(hashFromHref('/ruta#gr%C3%A1fico')).toBe('gráfico');
    });
    it('sin ancla o ancla vacía: null', () => {
        expect(hashFromHref('/ruta')).toBeNull();
        expect(hashFromHref('/ruta#')).toBeNull();
    });
});

describe('scrollToHashAnchor', () => {
    function harness(initialHash: string) {
        let hash = initialHash;
        const timers: Array<() => void> = [];
        const el = { scrollIntoView: vi.fn() };
        const deps = {
            getCurrentHash: () => hash,
            setHash: (h: string) => { hash = h; },
            getElementById: vi.fn(() => el as unknown as HTMLElement),
            setTimeoutFn: (cb: () => void) => { timers.push(cb); },
            run: (n: number) => { for (let i = 0; i < n; i++) timers.shift()?.(); },
            el,
            timers,
        };
        return deps;
    }

    it('hash ya comprometido y elemento presente: scroll inmediato + segunda pasada contra layout shift', () => {
        const d = harness('#grafico');
        scrollToHashAnchor('grafico', d);
        d.run(1); // primera pasada
        expect(d.el.scrollIntoView).toHaveBeenCalledWith({ block: 'start' });
        d.run(1); // segunda pasada (Suspense pudo empujar el ancla)
        expect(d.el.scrollIntoView).toHaveBeenCalledTimes(2);
    });

    it('la segunda pasada no se hace si el usuario ya navegó a otro hash', () => {
        const d = harness('#grafico');
        scrollToHashAnchor('grafico', d);
        d.run(1);
        d.setHash('#otra');
        d.run(1);
        expect(d.el.scrollIntoView).toHaveBeenCalledTimes(1);
    });

    it('espera a que router.push comprometa la URL (hash pendiente) y entonces hace scroll', () => {
        const d = harness('#anterior');
        scrollToHashAnchor('grafico', d);
        d.run(1); // aún pendiente
        expect(d.el.scrollIntoView).not.toHaveBeenCalled();
        d.setHash('#grafico');
        d.run(1);
        expect(d.el.scrollIntoView).toHaveBeenCalledTimes(1);
    });

    it('un tercer hash aborta: nunca secuestra el scroll del usuario', () => {
        const d = harness('#anterior');
        scrollToHashAnchor('grafico', d);
        d.setHash('#otra-cosa');
        d.run(3);
        expect(d.el.scrollIntoView).not.toHaveBeenCalled();
        expect(d.timers).toHaveLength(0);
    });

    it('si el elemento no aparece, reintenta dentro de la ventana y para en silencio', () => {
        const d = harness('#grafico');
        d.getElementById.mockReturnValue(null as never);
        scrollToHashAnchor('grafico', d);
        d.run(30); // MAX_ATTEMPTS es 15: más que de sobra
        expect(d.el.scrollIntoView).not.toHaveBeenCalled();
        expect(d.timers).toHaveLength(0);
    });

    it('compara hashes normalizados aunque la URL venga codificada', () => {
        const d = harness('#gr%C3%A1fico');
        scrollToHashAnchor('gráfico', d);
        d.run(1);
        expect(d.el.scrollIntoView).toHaveBeenCalled();
    });
});

describe('scrollToHashAnchor con ventana configurable', () => {
    function harness(initialHash: string) {
        const hash = initialHash;
        const timers: Array<{ cb: () => void; ms: number }> = [];
        const el = { scrollIntoView: vi.fn() };
        return {
            getCurrentHash: () => hash,
            getElementById: vi.fn(() => el as unknown as HTMLElement),
            setTimeoutFn: (cb: () => void, ms: number) => { timers.push({ cb, ms }); },
            run: (n: number) => { for (let i = 0; i < n; i++) timers.shift()?.cb(); },
            el,
            timers,
        };
    }

    it('respeta intervalMs y maxAttempts de quien llama', () => {
        const d = harness('#diario-decisiones');
        d.getElementById.mockReturnValue(null as never);
        scrollToHashAnchor('diario-decisiones', { ...d, intervalMs: 150, maxAttempts: 80 });
        // Primer intento en el tick 0 y reintentos al ritmo pedido.
        expect(d.timers[0]?.ms).toBe(0);
        d.run(1);
        expect(d.timers[0]?.ms).toBe(150);
        d.run(80);
        // 80 reintentos agotados: para en silencio, sin más temporizadores.
        expect(d.timers).toHaveLength(0);
        expect(d.el.scrollIntoView).not.toHaveBeenCalled();
    });

    it('sin opciones mantiene la ventana corta original (100 ms × 15)', () => {
        const d = harness('#grafico');
        d.getElementById.mockReturnValue(null as never);
        scrollToHashAnchor('grafico', d);
        d.run(1);
        expect(d.timers[0]?.ms).toBe(100);
        d.run(14);
        expect(d.timers).toHaveLength(0);
    });
});
