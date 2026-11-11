import { describe, expect, it } from 'vitest';

import { previousInAppUrl, recordNavigation, shouldUseHistoryBack } from '@/lib/nav/in-app-history';

// Flujo real (auditoría r5-fa-flujo, 11-nov): watchlist → ficha → informe → «volver».
function visit(...urls: string[]) {
    return urls.reduce<readonly string[]>((stack, url) => recordNavigation(stack, url), []);
}

describe('pila de navegación interna', () => {
    it('una página abierta directamente no tiene «atrás» interno', () => {
        const stack = visit('/research/NVDA/informe');
        expect(previousInAppUrl(stack)).toBeNull();
        expect(shouldUseHistoryBack(stack, '/research/NVDA')).toBe(false);
        expect(shouldUseHistoryBack(stack, '/research', false)).toBe(false);
    });

    it('vuelve por historial a la ficha con su pestaña ?view=', () => {
        const stack = visit('/watchlist', '/research/NVDA?view=valoracion', '/insider?ticker=NVDA');
        expect(previousInAppUrl(stack)).toBe('/research/NVDA?view=valoracion');
        expect(shouldUseHistoryBack(stack, '/research/NVDA')).toBe(true);
    });

    it('«← NVDA» no vuelve por historial si se llegó desde otra página', () => {
        const stack = visit('/watchlist', '/insider?ticker=NVDA');
        expect(shouldUseHistoryBack(stack, '/research/NVDA')).toBe(false);
        // El enlace genérico «Volver» sí vuelve a la watchlist.
        expect(shouldUseHistoryBack(stack, '/research', false)).toBe(true);
    });

    it('detecta el «atrás» y no deja una página fantasma en la pila', () => {
        const stack = visit('/watchlist', '/research/NVDA', '/watchlist');
        expect(stack).toEqual(['/watchlist']);
        expect(previousInAppUrl(stack)).toBeNull();
    });

    it('repetir la misma URL no cambia la pila', () => {
        const once = visit('/inicio', '/research/AAPL');
        expect(recordNavigation(once, '/research/AAPL')).toBe(once);
    });

    it('compara rutas sin query, ancla ni barra final', () => {
        const stack = visit('/research/NVDA/?view=tesis#tesis-actual', '/research/NVDA/informe');
        expect(shouldUseHistoryBack(stack, '/research/NVDA')).toBe(true);
    });

    it('acota la pila', () => {
        const stack = visit(...Array.from({ length: 80 }, (_, i) => `/research/T${i}`));
        expect(stack.length).toBe(50);
        expect(previousInAppUrl(stack)).toBe('/research/T78');
    });
});
