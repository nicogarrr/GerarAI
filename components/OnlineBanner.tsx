"use client";

import { useOnlineStatus } from "@/hooks/useOnlineStatus";
import { useT } from "@/lib/i18n/client";

/**
 * Aviso de conexion. Se renderiza en flujo normal justo encima del header, asi
 * que el header sticky (top-0) queda por debajo en el eje de apilado y el
 * aviso nunca queda tapado ni se va al hacer scroll: es exactamente lo que
 * necesita saber el usuario cuando la app esta mostrando datos rancios.
 */
export const OnlineBanner = () => {
    const online = useOnlineStatus();
    const t = useT();

    // Live region PERMANENTE: montarla al irse la conexion hace que parte de
    // los lectores de pantalla no la anuncien (una region que no existia no se
    // registra). Va siempre montada y solo cambian contenido y visibilidad.
    // Con conexion queda `sr-only` (no `hidden`): display:none saca la region
    // del arbol de accesibilidad y reaparecer con texto equivale al montaje
    // dinamico de antes; sr-only la mantiene registrada y el anuncio salta
    // cuando cambia el texto. OJO: `data-online-banner` solo se emite SIN
    // conexion porque globals.css lo usa en `body:has(...)` para reservar su
    // alto en --shell-top; con el atributo siempre presente el shell quedaria
    // desplazado 2rem en permanente.
    return (
        <div
            role="status"
            aria-live="polite"
            {...(online ? {} : { 'data-online-banner': true })}
            className={online ? 'sr-only' : 'w-full bg-amber-100 py-2 text-center text-sm text-amber-900'}
        >
            {online ? null : t('shell.offline.banner')}
        </div>
    );
};

export default OnlineBanner;
