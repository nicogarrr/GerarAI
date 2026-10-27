'use client';

import { useEffect } from 'react';

/**
 * Service worker (app shell + fallback offline). Solo en build de producción
 * (lo decide el layout): en dev las cachés del SW estorban al hot-reload.
 *
 * Antes era un `<script dangerouslySetInnerHTML>` inline en el layout raíz:
 * el último script inline de la app. Con la CSP de `script-src` sin
 * 'unsafe-inline' (nonce por middleware) habría que noncearlo a mano; como
 * componente cliente pasa a ser parte del bundle y hereda la confianza del
 * bootstrap nonceado vía 'strict-dynamic'. El registro ocurre en cuanto
 * hidrata el cliente en vez de esperar al evento `load`: mismo efecto (el
 * registro es asíncrono y no bloquea) y menos código.
 */
export default function ServiceWorkerRegister() {
    useEffect(() => {
        if ('serviceWorker' in navigator) {
            navigator.serviceWorker.register('/sw.js');
        }
    }, []);
    return null;
}
