'use client';

import { useEffect } from 'react';
import { usePathname, useSearchParams } from 'next/navigation';

import { scrollToHashAnchor } from '@/lib/search/scroll-to-hash';

// La ficha se sirve por Suspense y sus secciones cargan datos asíncronos:
// el destino de un ancla puede tardar segundos en existir. Ventana amplia
// pero acotada (~12 s), heredada del patrón de scroll-to-hash.
const POLL_INTERVAL_MS = 150;
const MAX_POLLS = 80;

/** Id decodificado del hash actual; null si no hay ancla. */
function currentHashId(): string | null {
  const raw = window.location.hash;
  if (raw.length < 2) return null;
  const value = raw.slice(1);
  try {
    return decodeURIComponent(value);
  } catch {
    return value;
  }
}

/**
 * Scroll al ancla de la URL al llegar a la ficha.
 *
 * Bug (29-oct-2026, prod): los CTA «Revisar cambio» de Inicio
 * (/research/X?view=changes#thesis-change-…) y los enlaces a
 * #diario-decisiones llevaban a la página correcta pero SIN hacer scroll:
 * el App Router busca el elemento al comprometer la navegación, aún no
 * existe (Suspense + datos async) y nadie reintenta. Este componente
 * reintenta al montar, al cambiar la vista (?view=…) y en cada hashchange.
 *
 * No secuestra: el bucle aborta si el hash cambia (scroll-to-hash) y al
 * desmontarse el efecto (ruta/vista anterior), y la segunda pasada contra
 * layout shift la hace solo si el hash sigue activo.
 */
export function ResearchHashScroll() {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  useEffect(() => {
    // Un bucle de una ejecución anterior (otra vista) aborta en cuanto el
    // efecto se limpia: su getCurrentHash devuelve un hash que no es el
    // suyo ni el destino, y scroll-to-hash se detiene sin tocar el scroll.
    let alive = true;
    const guardedHash = () => (alive ? window.location.hash : '#__efecto-limpiado__');
    const scrollToCurrentHash = () => {
      const hash = currentHashId();
      if (!hash) return;
      scrollToHashAnchor(hash, {
        getCurrentHash: guardedHash,
        intervalMs: POLL_INTERVAL_MS,
        maxAttempts: MAX_POLLS,
      });
    };
    scrollToCurrentHash();
    window.addEventListener('hashchange', scrollToCurrentHash);
    return () => {
      alive = false;
      window.removeEventListener('hashchange', scrollToCurrentHash);
    };
  }, [pathname, searchParams]);
  return null;
}
