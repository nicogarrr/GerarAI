'use client';

import { usePathname, useSearchParams } from 'next/navigation';
import { useEffect, useRef } from 'react';

/**
 * Conserva la posición de scroll en navegaciones dentro de la MISMA página
 * (pestañas `?view=`, `?tab=`...). `Link scroll={false}` evita que Next suba
 * al inicio, pero no basta: mientras la vista nueva renderiza, el segmento
 * muestra su `loading.tsx` (min-h-screen), el documento colapsa a la altura
 * del viewport y el PROPIO NAVEGador clampa scrollY a 0. Cuando llega el
 * contenido, nadie restaura la posición: el usuario percibe un salto arriba.
 *
 * Estrategia: capturar scrollY en el pointerdown del enlace (antes de que
 * empiece la transición y el clamp) y restaurarlo cuando la navegación
 * completa y el hook de searchParams cambia. Navegar a OTRA ruta (pathname
 * distinto) no restaura nada: ahí se arranca arriba, como siempre.
 */
export function ScrollPreserver() {
    const pathname = usePathname();
    const searchParams = useSearchParams();
    const savedRef = useRef<{ pathname: string; y: number } | null>(null);
    const firstRef = useRef(true);

    useEffect(() => {
        const onPointerDown = (event: PointerEvent) => {
            const anchor = (event.target as HTMLElement | null)?.closest?.('a[href]');
            if (!anchor) return;
            const href = anchor.getAttribute('href') ?? '';
            // Solo enlaces internos a la misma ruta (pestañas por query string).
            if (!href.startsWith(pathname + '?') && href !== pathname) return;
            savedRef.current = { pathname, y: window.scrollY };
        };
        document.addEventListener('pointerdown', onPointerDown, true);
        return () => document.removeEventListener('pointerdown', onPointerDown, true);
    }, [pathname]);

    const navKey = `${pathname}?${searchParams?.toString() ?? ''}`;
    useEffect(() => {
        if (firstRef.current) {
            firstRef.current = false;
            return;
        }
        const saved = savedRef.current;
        savedRef.current = null;
        if (!saved || saved.pathname !== pathname || saved.y <= 0) return;
        // El contenido nuevo ya está committed: el documento vuelve a tener
        // altura y el restore no queda clampado. rAF para pintar antes.
        const frame = requestAnimationFrame(() => window.scrollTo(0, saved.y));
        return () => cancelAnimationFrame(frame);
    }, [navKey, pathname]);

    return null;
}
