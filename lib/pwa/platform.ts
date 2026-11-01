/**
 * Detección de plataforma para PWA (app instalada e iOS).
 *
 * Una sola fuente: estas dos comprobaciones vivían duplicadas al 100% en
 * components/pwa/InstallApp.tsx y components/alerts/PushNotifications.tsx,
 * y las dos decisiones de producto que dependen de ellas (ofrecer instalar
 * la app, exigir «añadir a pantalla de inicio» para Web Push en iOS) tienen
 * que verse igual en ambas. APIs solo de navegador: llamar tras montar.
 */

/** True si la app ya corre instalada (display-mode standalone o el flag de Safari iOS). */
export function isStandalone(): boolean {
    const nav = window.navigator as Navigator & { standalone?: boolean };
    return window.matchMedia('(display-mode: standalone)').matches || nav.standalone === true;
}

/** True en iPhone/iPad/iPod. iPadOS 13+ se presenta como Mac: se distingue por la pantalla táctil. */
export function isIos(): boolean {
    const ua = window.navigator.userAgent;
    return /iPhone|iPad|iPod/.test(ua) || (/Macintosh/.test(ua) && window.navigator.maxTouchPoints > 1);
}
