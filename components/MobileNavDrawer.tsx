'use client';
import { openBrain } from '@/lib/brain/open-brain';

import { useRef, useState, useCallback, type RefObject } from 'react';
import { createPortal } from 'react-dom';
import { X } from 'lucide-react';
import { GerarAIWordmark } from '@/components/GerarAIWordmark';
import NavItems from '@/components/NavItems';
import SearchCommand from '@/components/SearchCommand';
import { BrainGlassesIcon } from '@/components/brain/BrainGlassesIcon';
import { useT } from '@/lib/i18n/client';
import { DialogPortalContainerProvider } from '@/hooks/useDialogPortalContainer';
import { useNativeNavDrawer } from '@/hooks/useNativeNavDrawer';

type Props = {
    onClose: () => void;
    triggerRef: RefObject<HTMLButtonElement | null>;
    initialStocks?: StockWithWatchlistStatus[];
};

/**
 * Drawer de la navegación móvil: MISMO árbol que el sidebar de escritorio.
 * Carga diferido al abrir el menú (ver MobileNav): su JS no viaja en el
 * bundle inicial de ninguna ruta. El gatillo hamburguesa queda eager.
 *
 * <dialog> NATIVO modal (guía Modern Web Guidance, dialog regla 1): sin
 * role="dialog" ni aria-modal escritos a mano, sin trampa de foco, sin inert
 * y sin bloqueo manual de scroll del body. El aislamiento lo aporta
 * showModal() (ver hooks/useNativeNavDrawer). El fondo es ::backdrop, no un
 * botón absoluto. open:flex respeta el estado cerrado nativo. El buscador
 * Radix anidado conserva su portal dentro del modal para no quedar inerte.
 */
export default function MobileNavDrawer({ onClose, triggerRef, initialStocks }: Props) {
    const t = useT();
    const dialogRef = useRef<HTMLDialogElement>(null);
    const closeButtonRef = useRef<HTMLButtonElement>(null);
    const [portalContainer, setPortalContainer] = useState<HTMLDialogElement | null>(null);
    const setDialogRef = useCallback((node: HTMLDialogElement | null) => {
        dialogRef.current = node;
        setPortalContainer(node);
    }, []);
    const closeDrawer = () => {
        dialogRef.current?.close();
    };
    // showModal al montar, propagación del cierre nativo, cierre por fondo y
    // por breakpoint md+: comportamiento compartido en hooks/useNativeNavDrawer.
    useNativeNavDrawer({ active: true, onClose, dialogRef, closeButtonRef, triggerRef });

    return createPortal(
        <dialog
            ref={setDialogRef}
            id="mobile-nav-drawer"
            aria-labelledby="mobile-nav-title"
            className="fixed left-0 top-0 z-[60] m-0 open:flex h-full max-h-dvh w-[85vw] max-w-xs flex-col border-r border-gray-700/50 bg-gray-900 p-0 text-gray-300 shadow-2xl md:hidden [&:modal]:overscroll-contain backdrop:bg-black/60 backdrop:backdrop-blur-sm backdrop:overscroll-contain backdrop:overflow-hidden"
        >
            <DialogPortalContainerProvider value={portalContainer}>
                <h2 id="mobile-nav-title" className="sr-only">{t('shell.nav.menuTitle')}</h2>
                <div className="flex min-h-16 items-center justify-between gap-2 border-b border-gray-700/50 px-4 py-3">
                    <GerarAIWordmark />
                    <button
                        type="button"
                        ref={closeButtonRef}
                        onClick={closeDrawer}
                        aria-label={t('shell.nav.closeMenu')}
                        className="inline-flex min-h-11 min-w-11 items-center justify-center rounded-lg p-2 text-gray-300 transition-colors hover:bg-gray-700/50 hover:text-white"
                    >
                        <X className="h-6 w-6" aria-hidden="true" />
                    </button>
                </div>

                {/* El buscador va dentro del drawer: `initialStocks`
                    llegaba por toda la cadena layout -> Header ->
                    MobileNav -> NavItems y se descartaba con
                    `void initialStocks`. Aqui se usa de verdad. */}
                <div className="border-b border-gray-700/50 px-3 py-3">
                    <SearchCommand
                        renderAs="button"
                        initialStocks={initialStocks}
                    />
                </div>

                {/* El cierre va en cada enlace, no en el <nav>: antes
                    un clic en el titulo de seccion o en el fondo
                    cerraba el menu. */}
                <nav
                    className="min-h-0 flex-1 overflow-y-auto overscroll-contain"
                    aria-label={t('shell.nav.mobileAria')}
                    onClick={(event) => {
                        if ((event.target as HTMLElement).closest('a[href]')) closeDrawer();
                    }}
                >
                    <button type="button" className="mb-3 flex min-h-11 w-full items-center gap-3 rounded-lg px-3 py-2 text-left text-sm font-medium text-teal-300 hover:bg-gray-800" onClick={() => { closeDrawer(); openBrain(); }}>
                        <BrainGlassesIcon className="h-5 w-5" />Cerebro
                    </button>
                    <NavItems />
                </nav>
            </DialogPortalContainerProvider>
        </dialog>,
        document.body,
    );
}
