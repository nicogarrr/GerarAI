'use client';

/**
 * router.refresh() re-renderiza la ruta entera y el navegador pierde el
 * ancla de lectura (la cabecera de la ficha ocupa mas de una pantalla y los
 * paneles cambian de altura). Estas dos utilidades devuelven el control al
 * usuario: nada se mueve solo y, cuando el refresco lo pide el usuario, la
 * posicion se conserva.
 */

/** Mantiene el scrollY actual mientras el refresco re-renderiza (max. 2,5 s).
 *  Cualquier gesto de scroll del usuario cancela la retencion al momento. */
export function preserveScrollPosition(trigger: () => void, timeoutMs = 2500): void {
  const y = window.scrollY;
  trigger();
  let raf = 0;
  const started = performance.now();
  const cancel = () => {
    cancelAnimationFrame(raf);
    window.removeEventListener('wheel', onUserScroll, true);
    window.removeEventListener('touchmove', onUserScroll, true);
    window.removeEventListener('keydown', onUserScroll, true);
  };
  const onUserScroll = () => cancel();
  const step = () => {
    if (performance.now() - started > timeoutMs) {
      cancel();
      return;
    }
    if (Math.abs(window.scrollY - y) > 1) window.scrollTo(0, y);
    raf = requestAnimationFrame(step);
  };
  window.addEventListener('wheel', onUserScroll, true);
  window.addEventListener('touchmove', onUserScroll, true);
  window.addEventListener('keydown', onUserScroll, true);
  raf = requestAnimationFrame(step);
}

/** Hace scroll al elemento cuando existe (tras un refresco el nodo llega un
 *  poco despues); si no aparece en 4 s, no hace nada. */
export function scrollToIdWhenReady(id: string, timeoutMs = 4000): void {
  const started = performance.now();
  const tick = () => {
    const element = document.getElementById(id);
    if (element) {
      element.scrollIntoView({ block: 'start' });
      return;
    }
    if (performance.now() - started < timeoutMs) requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
}
