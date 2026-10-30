'use client';
import { useT } from '@/lib/i18n/client';

import dynamic from 'next/dynamic';
import { useRef, useState } from 'react';
import { Menu } from 'lucide-react';

// El drawer (buscador, árbol de secciones y CTA del cerebro) solo hace falta
// al abrir el menú: importado estático viajaba en el bundle inicial de TODAS
// las rutas. El gatillo hamburguesa queda eager con precarga del chunk en
// pointerdown/focus; el drawer llega al abrir y conserva su gestión de foco,
// Escape, ciclo de Tab y bloqueo de scroll (ver MobileNavDrawer).
const loadMobileNavDrawer = () => import('./MobileNavDrawer');
const MobileNavDrawer = dynamic(loadMobileNavDrawer, { loading: () => null });

/**
 * Navegacion movil: boton hamburger (>=44px) que abre un drawer con el MISMO
 * arbol que el sidebar de escritorio.
 *
 * El breakpoint es `md` en los dos lados a proposito. Antes el trigger era
 * `sm:hidden` y el sidebar `md:flex`, asi que entre 640px y 767px no existia
 * ninguna navegacion por secciones: solo logo, buscador y avatar.
 */
export default function MobileNav({ initialStocks }: { initialStocks?: StockWithWatchlistStatus[] }) {
    const t = useT();
    const [open, setOpen] = useState(false);
    const triggerRef = useRef<HTMLButtonElement>(null);

    return (
        <>
            <button
                type="button"
                ref={triggerRef}
                onClick={() => setOpen(true)}
                onPointerDown={() => void loadMobileNavDrawer()}
                onFocus={() => void loadMobileNavDrawer()}
                aria-label={t('shell.nav.openMenu')}
                aria-expanded={open}
                aria-controls="mobile-nav-drawer"
                className="inline-flex min-h-11 min-w-11 items-center justify-center rounded-lg p-2 text-gray-300 transition-colors hover:bg-gray-700/50 hover:text-white md:hidden"
            >
                <Menu className="h-6 w-6" aria-hidden="true" />
            </button>

            {open && (
                <MobileNavDrawer
                    onClose={() => setOpen(false)}
                    triggerRef={triggerRef}
                    initialStocks={initialStocks}
                />
            )}
        </>
    );
}
