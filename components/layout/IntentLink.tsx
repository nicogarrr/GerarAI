'use client';

import Link from 'next/link';
import { useState, type ComponentProps } from 'react';

/**
 * Enlace de navegacion que precarga la pagina COMPLETA solo cuando el usuario
 * muestra intencion (raton encima, foco de teclado o primer toque), no al
 * montar el menu.
 *
 * Antes cada carga de pagina disparaba `prefetch` forzado de todos los
 * destinos del menu (Sidebar + NavItems repiten los mismos ~16 destinos):
 * ~32 renders de servidor de 1-2,5 s que competian con los datos de la propia
 * pagina. Con intencion, la navegacion sigue siendo instantanea para el
 * destino al que el usuario se dirige.
 */
export default function IntentLink(props: Omit<ComponentProps<typeof Link>, 'prefetch'>) {
    const [intent, setIntent] = useState(false);
    const { onMouseEnter, onFocus, onTouchStart, ...rest } = props;
    return (
        <Link
            {...rest}
            prefetch={intent ? true : false}
            onMouseEnter={(event) => {
                setIntent(true);
                onMouseEnter?.(event);
            }}
            onFocus={(event) => {
                setIntent(true);
                onFocus?.(event);
            }}
            onTouchStart={(event) => {
                setIntent(true);
                onTouchStart?.(event);
            }}
        />
    );
}
