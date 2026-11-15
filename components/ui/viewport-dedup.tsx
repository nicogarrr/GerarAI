'use client';

import { useEffect, useState, type ReactNode } from 'react';

/**
 * De-duplicacion de arboles movil/escritorio (scorecard v1, hallazgo 4).
 *
 * SSR y la primera pintada del cliente renderizan AMBOS arboles, exactamente
 * como antes: el HTML del servidor no cambia, no hay flash ni CLS, y el
 * contenido sigue completo sin JS. Tras montar, solo queda montado el arbol
 * del viewport activo (el descartado ya estaba oculto con display:none, asi
 * que nada visible cambia). Al imprimir se vuelven a montar los dos: las
 * clases print:* deciden como siempre (p. ej. la tabla de /research/sources
 * sale en papel aunque el viewport sea movil).
 */
export function useViewportDedup(query: string): 'mobile' | 'desktop' | null {
    const [viewport, setViewport] = useState<'mobile' | 'desktop' | null>(null);
    useEffect(() => {
        // jsdom y navegadores muy antiguos no tienen matchMedia: sin el se
        // mantienen los dos arboles (comportamiento de siempre, sin dedup).
        if (typeof window.matchMedia !== 'function') return;
        const media = window.matchMedia(query);
        const print = window.matchMedia('print');
        const update = () => setViewport(print.matches ? null : media.matches ? 'desktop' : 'mobile');
        update();
        media.addEventListener('change', update);
        print.addEventListener('change', update);
        return () => {
            media.removeEventListener('change', update);
            print.removeEventListener('change', update);
        };
    }, [query]);
    return viewport;
}

/** Envoltorio para server components: recibe ambos arboles ya renderizados. */
export function ViewportDedup({ mobile, desktop, query = '(min-width: 768px)' }: { mobile: ReactNode; desktop: ReactNode; query?: string }) {
    const viewport = useViewportDedup(query);
    return (
        <>
            {viewport !== 'mobile' ? desktop : null}
            {viewport !== 'desktop' ? mobile : null}
        </>
    );
}
