'use client';

import { useEffect, useRef } from 'react';

/**
 * Deja la pestaña activa ([aria-current="page"]) completamente visible en el
 * carril horizontal de la ficha. inline:'nearest' no mueve el carril si ya
 * se ve entera; block:'nearest' limita el desplazamiento vertical.
 *
 * El efecto corre al montar y cada vez que cambia qué enlace lleva
 * aria-current: la navegación entre pestañas es la MISMA ruta con otro
 * ?view= (scroll={false}), así que el carril conserva su scroll y el
 * componente no se remonta; sin el observador la activa nueva podía quedar
 * fuera de vista.
 */
export function CompanyNavigationScroll() {
  const ref = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    const nav = ref.current?.parentElement;
    if (!nav) return;
    const scrollActiveIntoView = () => {
      const active = nav.querySelector('[aria-current="page"]');
      if (active instanceof HTMLElement) {
        active.scrollIntoView({ block: 'nearest', inline: 'nearest' });
      }
    };
    scrollActiveIntoView();
    const observer = new MutationObserver(scrollActiveIntoView);
    observer.observe(nav, { attributes: true, attributeFilter: ['aria-current'], subtree: true });
    return () => observer.disconnect();
  }, []);
  return <span ref={ref} className="hidden" aria-hidden="true" />;
}
