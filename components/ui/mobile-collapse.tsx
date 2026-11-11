'use client';

import * as React from 'react';
import { ChevronDown } from 'lucide-react';

import { cn } from '@/lib/utils';

/**
 * Bloque plegado en móvil (cerrado por defecto) y siempre visible desde `md`.
 *
 * En móvil cabecera y contenido son UNA sola tarjeta: el título va arriba y,
 * al abrir, el contenido se despliega dentro, debajo de una línea, sin hueco
 * ni segundo borde. La tarjeta propia del hijo (borde y radio) se neutraliza
 * solo por debajo de `md`; desde `md` el hijo se pinta tal cual y la cabecera
 * no existe.
 *
 * `inset`: el bloque ya vive dentro de otra tarjeta (p. ej. «Lectura técnica»
 * dentro del gráfico); entonces no pinta marco propio, solo la línea superior,
 * para no anidar una tarjeta dentro de otra.
 */
const DESKTOP = '(min-width: 768px)';
function subscribeDesktop(notify: () => void) {
    const media = window.matchMedia(DESKTOP);
    media.addEventListener('change', notify);
    return () => media.removeEventListener('change', notify);
}
const isDesktop = () => window.matchMedia(DESKTOP).matches;
const serverDesktop = () => false;

export default function MobileCollapse({ title, children, inset = false, deferMount = false }: { title: string; children: React.ReactNode; inset?: boolean; deferMount?: boolean }) {
    const [open, setOpen] = React.useState(false);
    const [opened, setOpened] = React.useState(false);
    const desktop = React.useSyncExternalStore(
        deferMount ? subscribeDesktop : () => () => {},
        deferMount ? isDesktop : serverDesktop,
        serverDesktop,
    );
    const id = React.useId();
    return (
        <div
            className={cn(
                inset
                    ? 'max-md:border-t max-md:border-gray-800'
                    : 'max-md:overflow-hidden max-md:rounded-xl max-md:border max-md:border-gray-800 max-md:bg-surface-1',
            )}
            data-open={open ? 'true' : 'false'}
            data-testid="mobile-collapse"
        >
            <button
                aria-controls={id}
                aria-expanded={open}
                className="flex min-h-[44px] w-full items-center justify-between gap-3 px-4 text-left text-sm font-semibold text-gray-100 outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-teal-400 md:hidden"
                onClick={() => { setOpened(true); setOpen((value) => !value); }}
                type="button"
            >
                {title}
                <ChevronDown aria-hidden="true" className={cn('h-5 w-5 shrink-0 text-gray-500 transition-transform', open && 'rotate-180')} />
            </button>
            <div
                className={cn(
                    open ? 'block' : 'hidden md:block',
                    'max-md:border-t max-md:border-gray-800',
                    // Una sola tarjeta en móvil: fuera el borde/radio/sombra de la tarjeta del hijo.
                    'max-md:*:rounded-none! max-md:*:border-0! max-md:*:shadow-none!',
                )}
                id={id}
            >
                {!deferMount || desktop || opened ? children : null}
            </div>
        </div>
    );
}
