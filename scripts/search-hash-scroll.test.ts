import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
// @ts-expect-error TS5097: la extensión explícita la exige node --experimental-strip-types.
import { hashFromHref, scrollToHashAnchor } from '../lib/search/scroll-to-hash.ts';

function fakeScheduler() {
    const queue: { callback: () => void; ms: number }[] = [];
    return {
        queue,
        setTimeoutFn: (callback: () => void, ms: number) => { queue.push({ callback, ms }); },
        flush: (times = 50) => { for (let i = 0; i < times && queue.length; i++) queue.shift()!.callback(); },
    };
}

describe('hashFromHref', () => {
    it('extrae el ancla de rutas con y sin query', () => {
        assert.equal(hashFromHref('/research/MSFT#grafico'), 'grafico');
        assert.equal(hashFromHref('/research/MSFT?view=financials#alerta'), 'alerta');
    });
    it('devuelve null sin ancla o con ancla vacía', () => {
        assert.equal(hashFromHref('/research/MSFT'), null);
        assert.equal(hashFromHref('/research/MSFT?view=financials'), null);
        assert.equal(hashFromHref('/research/MSFT#'), null);
    });
    it('decodifica y tolera porcentajes inválidos', () => {
        assert.equal(hashFromHref('/ruta#secci%C3%B3n'), 'sección');
        assert.equal(hashFromHref('/ruta#100%'), '100%');
    });
});

describe('scrollToHashAnchor', () => {
    it('hace scroll cuando el elemento existe y repite una vez para absorber layout shift', () => {
        const sched = fakeScheduler();
        const calls: unknown[] = [];
        scrollToHashAnchor('grafico', {
            getElementById: (id) => id === 'grafico' ? { scrollIntoView: (o) => calls.push(o) } : null,
            getCurrentHash: () => '#grafico',
            setTimeoutFn: sched.setTimeoutFn,
        });
        sched.flush();
        assert.deepEqual(calls, [{ block: 'start' }, { block: 'start' }]);
    });
    it('la pasada de asentamiento se salta si el hash ya cambió', () => {
        const sched = fakeScheduler();
        const calls: unknown[] = [];
        let current = '#grafico';
        scrollToHashAnchor('grafico', {
            getElementById: () => ({ scrollIntoView: (o) => { calls.push(o); current = '#/otra'; } }),
            getCurrentHash: () => current,
            setTimeoutFn: sched.setTimeoutFn,
        });
        sched.flush();
        assert.equal(calls.length, 1);
    });
    it('reintenta hasta que el elemento aparece (navegación cruzada)', () => {
        const sched = fakeScheduler();
        const calls: unknown[] = [];
        let ticks = 0;
        scrollToHashAnchor('alerta', {
            getElementById: () => (++ticks >= 3 ? { scrollIntoView: (o) => calls.push(o) } : null),
            getCurrentHash: () => '#alerta',
            setTimeoutFn: sched.setTimeoutFn,
        });
        sched.flush();
        assert.equal(calls.length, 2); // encontrado al 3er intento + asentamiento
        assert.ok(ticks >= 3, `esperaba reintentos, ticks=${ticks}`);
    });
    it('se rinde tras la ventana sin lanzar ni hacer scroll', () => {
        const sched = fakeScheduler();
        const calls: unknown[] = [];
        scrollToHashAnchor('fantasma', {
            getElementById: () => null,
            getCurrentHash: () => '#fantasma',
            setTimeoutFn: sched.setTimeoutFn,
        });
        sched.flush(100);
        assert.equal(calls.length, 0);
        assert.equal(sched.queue.length, 0);
    });
    it('aborta si el hash de la URL cambia (el usuario navegó)', () => {
        const sched = fakeScheduler();
        const calls: unknown[] = [];
        let current = '#grafico';
        scrollToHashAnchor('grafico', {
            getElementById: () => { current = '/otra'; return null; },
            getCurrentHash: () => current,
            setTimeoutFn: sched.setTimeoutFn,
        });
        sched.flush();
        assert.equal(calls.length, 0);
        assert.equal(sched.queue.length, 0);
    });
});

describe('la paleta desplaza al ancla tras router.push', () => {
    it('go() aplica scrollToHashAnchor cuando el href lleva hash', () => {
        const source = readFileSync('components/SearchCommand.tsx', 'utf8');
        assert.ok(source.includes('import { hashFromHref, scrollToHashAnchor } from "@/lib/search/scroll-to-hash"'));
        const goBody = source.slice(source.indexOf('const go = useCallback'));
        assert.ok(goBody.indexOf('router.push(href)') < goBody.indexOf('scrollToHashAnchor(hash)'));
        assert.ok(goBody.includes('hashFromHref(href)'));
    });
});
