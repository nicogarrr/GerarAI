/**
 * Enums de proveedores de datos y de noticias.
 *
 * Modulo SIN 'use server' a proposito. Next valida en
 * next/dist/build/webpack/loaders/next-flight-loader/action-validate.js que un
 * fichero 'use server' solo exporte funciones async; un `enum` de TypeScript
 * compila a un objeto y viola la regla (E352). Mientras nadie importase el
 * enum desde fuera, el dead-code elimination de Turbopack lo dejaba fuera del
 * manifiesto de actions y no reventaba: en cuanto un componente cliente (que
 * lo necesita para el campo `source`) lo importase, el build habria fallado.
 *
 * Mismo patron que lib/chat/citations.ts, que ya documenta la restriccion.
 */

export enum NewsSource {
    FINNHUB = 'finnhub',
    ALPHA_VANTAGE = 'alpha_vantage',
    NEWSAPI = 'newsapi',
    MARKETAUX = 'marketaux',
}
