import type { Page } from '@playwright/test';

/**
 * Espera a que React haya hidratado todo el contenido interactivo de <main>.
 *
 * `networkidle` no basta en la ficha: secciones de servidor dentro de
 * <Suspense> (p. ej. AnalystTargetsSection) llegan en streaming y se hidratan
 * tarde. Si se abre la paleta (Radix modal) antes, Radix marca el resto del DOM
 * con aria-hidden (hideOthers) y React compara su HTML esperado con ese DOM ya
 * mutado: «A tree hydrated but some attributes of the server rendered HTML
 * didn't match», que el overlay de Next dev muestra como un role="dialog" que
 * Escape no cierra.
 *
 * React 19 pone una clave `__reactFiber$…` en cada nodo DOM que ya controla; los
 * nodos de un límite Suspense aún sin hidratar no la tienen. Solo se miran los
 * elementos que el propio React renderiza y que son interactivos o titulares
 * (el enlace de atribución de lightweight-charts, #tv-attr-logo, lo crea la
 * librería y nunca tiene fibra).
 */
export async function waitForHydration(page: Page) {
    await page.waitForFunction(() => {
        const nodes = Array.from(document.querySelectorAll('main h1, main h2, main h3, main button, main a[href]:not(#tv-attr-logo)'));
        if (nodes.length === 0) return false;
        return nodes.every((node) => Object.keys(node).some((key) => key.startsWith('__reactFiber$')));
    });
}
