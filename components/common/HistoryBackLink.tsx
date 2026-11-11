'use client';

import Link from 'next/link';
import { usePathname, useSearchParams } from 'next/navigation';
import { useEffect, useSyncExternalStore, type ComponentProps, type MouseEvent, type ReactNode } from 'react';

import { historyBackSteps, inAppHistoryStore, shouldUseHistoryBack } from '@/lib/nav/in-app-history';

/**
 * Apunta cada navegación interna en la pila de lib/nav/in-app-history.
 * Se monta una vez en el layout autenticado; no pinta nada.
 */
export function InAppHistoryTracker() {
    const pathname = usePathname();
    const search = useSearchParams()?.toString() ?? '';
    useEffect(() => {
        const record = () => {
            if (pathname) inAppHistoryStore.record(`${pathname}${search ? `?${search}` : ''}${window.location.hash}`);
        };
        record();
        window.addEventListener('hashchange', record);
        return () => window.removeEventListener('hashchange', record);
    }, [pathname, search]);
    return null;
}

type HistoryBackLinkProps = Omit<ComponentProps<typeof Link>, 'href'> & {
    /** Padre de siempre: destino si la página se abrió directamente. */
    href: string;
    /** Ver shouldUseHistoryBack. */
    sameDestinationOnly?: boolean;
    /** Contenido cuando el enlace vuelve por historial a otra página (enlace genérico «Volver»). */
    historyChildren?: ReactNode;
};

/**
 * Enlace «← Volver» que respeta de dónde viene el usuario: si la página
 * anterior es de la app (y, por defecto, la misma ruta que `href`), vuelve
 * por el historial — misma pestaña `?view=`, mismo scroll, sin renderizar la
 * ficha otra vez —; si no, navega a `href` como antes. Sin JS o con clic
 * central/Cmd sigue siendo un enlace normal a `href`.
 */
export function HistoryBackLink({ href, sameDestinationOnly = true, historyChildren, children, onClick, ...rest }: HistoryBackLinkProps) {
    const stack = useSyncExternalStore(inAppHistoryStore.subscribe, inAppHistoryStore.getSnapshot, inAppHistoryStore.getServerSnapshot);
    const useHistory = shouldUseHistoryBack(stack, href, sameDestinationOnly);
    const handleClick = (event: MouseEvent<HTMLAnchorElement>) => {
        onClick?.(event);
        if (event.defaultPrevented || !useHistory) return;
        if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
        event.preventDefault();
        // = router.back() del App Router, sin exigir el router montado (las
        // páginas que lo usan se renderizan también en tests de servidor).
        const steps = historyBackSteps(stack);
        if (steps === 1) window.history.back();
        else window.history.go(-steps);
    };
    return (
        <Link {...rest} href={href} onClick={handleClick} data-back-mode={useHistory ? 'history' : 'link'}>
            {useHistory && historyChildren !== undefined ? historyChildren : children}
        </Link>
    );
}
