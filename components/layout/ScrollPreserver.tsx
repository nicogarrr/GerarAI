'use client';

import { usePathname, useSearchParams } from 'next/navigation';
import { useEffect, useRef } from 'react';

import { readScrollMemory, rememberScroll, restoreStep, writeScrollMemory } from '@/lib/nav/scroll-memory';

function sessionStore(): Storage | null {
    try {
        return window.sessionStorage;
    } catch {
        return null;
    }
}

function maxScrollY(): number {
    const doc = document.scrollingElement ?? document.documentElement;
    return Math.max(0, doc.scrollHeight - window.innerHeight);
}

function navigationType(): string | undefined {
    try {
        const entry = performance.getEntriesByType?.('navigation')?.[0] as PerformanceNavigationTiming | undefined;
        return entry?.type;
    } catch {
        return undefined;
    }
}

/**
 * Posición de scroll en la app, en dos casos:
 *
 * 1. Navegaciones dentro de la MISMA página (pestañas `?view=`, `?tab=`...).
 *    `Link scroll={false}` evita que Next suba al inicio, pero no basta:
 *    mientras la vista nueva renderiza, el segmento muestra su `loading.tsx`
 *    (min-h-screen), el documento colapsa a la altura del viewport y el
 *    PROPIO NAVEGADOR clampa scrollY a 0. Se captura scrollY en el
 *    pointerdown del enlace y se restaura cuando cambia la URL.
 *
 * 2. Volver por historial («← Volver» de la app, atrás/adelante del navegador,
 *    recarga): se vuelve a la posición en la que el usuario dejó esa URL.
 *    El navegador no sabe hacerlo con el App Router (ver
 *    lib/nav/scroll-memory.ts): guarda la posición ya recortada por la página
 *    nueva y restaura antes de que la ficha termine de llegar. Aquí se guarda
 *    la última posición de cada URL mientras el usuario hace scroll (y en el
 *    pointerdown de cualquier enlace, antes de que empiece la transición) y,
 *    al volver, se reintenta fotograma a fotograma hasta que el documento
 *    mide lo bastante y la posición aguanta. Si el usuario toca, rueda o
 *    teclea mientras tanto, manda él y se deja de restaurar.
 *
 * Navegar hacia delante a OTRA ruta no restaura nada: se arranca arriba,
 * como siempre.
 */
export function ScrollPreserver() {
    const pathname = usePathname();
    const searchParams = useSearchParams();
    const search = searchParams?.toString() ?? '';
    const navKey = search ? `${pathname}?${search}` : pathname;

    const savedRef = useRef<{ pathname: string; y: number } | null>(null);
    const firstRef = useRef(true);
    const navKeyRef = useRef(navKey);
    const trackingRef = useRef(true);
    const popPendingRef = useRef(false);
    const cancelRestoreRef = useRef<(() => void) | null>(null);

    // Restauración manual: la del navegador llega antes que el contenido y
    // con la posición equivocada (y aquí se hace la buena).
    useEffect(() => {
        const history = window.history;
        if (!('scrollRestoration' in history)) return;
        const previous = history.scrollRestoration;
        history.scrollRestoration = 'manual';
        return () => {
            history.scrollRestoration = previous;
        };
    }, []);

    // Última posición de cada URL mientras se hace scroll; congelada desde
    // que empieza una navegación hasta que la URL nueva está montada.
    useEffect(() => {
        let frame = 0;
        const save = () => {
            frame = 0;
            if (!trackingRef.current) return;
            const store = sessionStore();
            writeScrollMemory(store, rememberScroll(readScrollMemory(store), navKeyRef.current, window.scrollY));
        };
        const onScroll = () => {
            if (!frame) frame = requestAnimationFrame(save);
        };
        const onPopState = () => {
            // La URL ya es la de destino: lo último guardado es lo bueno.
            trackingRef.current = false;
            popPendingRef.current = true;
        };
        // Tocar un enlace congela la memoria (abajo); si no navega (se
        // arrastra para hacer scroll, se suelta fuera), el siguiente gesto de
        // scroll del usuario la vuelve a encender. El recorte de una
        // transición no es un gesto: no la enciende.
        const onIntent = () => {
            if (!cancelRestoreRef.current) trackingRef.current = true;
        };
        window.addEventListener('scroll', onScroll, { passive: true });
        window.addEventListener('popstate', onPopState);
        for (const type of ['wheel', 'touchmove', 'keydown'] as const) {
            window.addEventListener(type, onIntent, { passive: true });
        }
        return () => {
            window.removeEventListener('scroll', onScroll);
            window.removeEventListener('popstate', onPopState);
            for (const type of ['wheel', 'touchmove', 'keydown'] as const) {
                window.removeEventListener(type, onIntent);
            }
            if (frame) cancelAnimationFrame(frame);
        };
    }, []);

    useEffect(() => {
        const onPointerDown = (event: PointerEvent) => {
            const anchor = (event.target as HTMLElement | null)?.closest?.('a[href]');
            if (!anchor) return;
            const href = anchor.getAttribute('href') ?? '';
            if (!href.startsWith('/') || href.startsWith('//')) return;
            // Antes de la transición (y del recorte): posición real del usuario.
            cancelRestoreRef.current?.();
            const store = sessionStore();
            writeScrollMemory(store, rememberScroll(readScrollMemory(store), navKeyRef.current, window.scrollY));
            trackingRef.current = false;
            // Solo enlaces internos a la misma ruta (pestañas por query string).
            if (href.startsWith(pathname + '?') || href === pathname) {
                savedRef.current = { pathname, y: window.scrollY };
            }
        };
        document.addEventListener('pointerdown', onPointerDown, true);
        return () => document.removeEventListener('pointerdown', onPointerDown, true);
    }, [pathname]);

    useEffect(() => {
        navKeyRef.current = navKey;
        // Una restauración en curso es de la URL anterior.
        cancelRestoreRef.current?.();
        const resume = () => {
            trackingRef.current = true;
        };

        const restoreTo = (target: number) => {
            cancelRestoreRef.current?.();
            trackingRef.current = false;
            const started = performance.now();
            let stableFrames = 0;
            // El presupuesto se reinicia mientras la página siga llegando:
            // una ficha lenta (> 4 s de streaming) no pierde la posición.
            let lastMaxY = -1;
            let lastGrowthAt = started;
            let frame = 0;
            let cancelled = false;
            const stop = () => {
                if (cancelled) return;
                cancelled = true;
                cancelAnimationFrame(frame);
                for (const type of ['wheel', 'touchstart', 'keydown', 'pointerdown'] as const) {
                    window.removeEventListener(type, stop, true);
                }
                if (cancelRestoreRef.current === stop) cancelRestoreRef.current = null;
                resume();
            };
            const tick = () => {
                if (cancelled) return;
                const now = performance.now();
                const maxY = maxScrollY();
                if (maxY > lastMaxY) {
                    lastMaxY = maxY;
                    lastGrowthAt = now;
                }
                const step = restoreStep({
                    target,
                    y: window.scrollY,
                    maxY,
                    stableFrames,
                    elapsedMs: now - started,
                    sinceGrowthMs: now - lastGrowthAt,
                });
                if (step.kind !== 'scroll') {
                    stop();
                    return;
                }
                stableFrames = step.stableFrames;
                if (Math.abs(window.scrollY - step.to) > 1) window.scrollTo(0, step.to);
                frame = requestAnimationFrame(tick);
            };
            // Si el usuario toma el control, manda él.
            for (const type of ['wheel', 'touchstart', 'keydown', 'pointerdown'] as const) {
                window.addEventListener(type, stop, { capture: true, passive: true });
            }
            cancelRestoreRef.current = stop;
            frame = requestAnimationFrame(tick);
        };

        if (firstRef.current) {
            firstRef.current = false;
            // Recarga o «atrás» que vuelve a cargar la página entera.
            const type = navigationType();
            const target = readScrollMemory(sessionStore())[navKey];
            if ((type === 'reload' || type === 'back_forward') && target && target > 0) restoreTo(target);
            return;
        }

        if (popPendingRef.current) {
            popPendingRef.current = false;
            savedRef.current = null;
            const target = readScrollMemory(sessionStore())[navKey];
            if (target && target > 0) {
                restoreTo(target);
            } else {
                resume();
            }
            return;
        }

        const saved = savedRef.current;
        savedRef.current = null;
        if (!saved || saved.pathname !== pathname || saved.y <= 0) {
            // Hacia delante a otra ruta: Next sube arriba; se vuelve a apuntar
            // tras ese salto para no guardarlo como posición de la página vieja.
            const frame = requestAnimationFrame(resume);
            return () => cancelAnimationFrame(frame);
        }
        // El contenido nuevo ya está committed: el documento vuelve a tener
        // altura y el restore no queda clampado. rAF para pintar antes.
        const frame = requestAnimationFrame(() => {
            window.scrollTo(0, saved.y);
            resume();
        });
        return () => cancelAnimationFrame(frame);
    }, [navKey, pathname]);

    useEffect(() => () => cancelRestoreRef.current?.(), []);

    return null;
}
