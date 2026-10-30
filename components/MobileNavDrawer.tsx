'use client';

import { useEffect, useRef, type RefObject } from 'react';
import { createPortal } from 'react-dom';
import { X } from 'lucide-react';
import { GerarAIWordmark } from '@/components/GerarAIWordmark';
import NavItems from '@/components/NavItems';
import SearchCommand from '@/components/SearchCommand';
import { BrainGlassesIcon } from '@/components/brain/BrainGlassesIcon';
import { useT } from '@/lib/i18n/client';

type Props = {
    onClose: () => void;
    triggerRef: RefObject<HTMLButtonElement | null>;
    initialStocks?: StockWithWatchlistStatus[];
};

/**
 * Drawer de la navegación móvil: MISMO árbol que el sidebar de escritorio.
 * Carga diferido al abrir el menú (ver MobileNav): su JS no viaja en el
 * bundle inicial de ninguna ruta. El gatillo hamburguesa queda eager.
 */
export default function MobileNavDrawer({ onClose, triggerRef, initialStocks }: Props) {
    const t = useT();
    const drawerRef = useRef<HTMLDivElement>(null);
    const closeButtonRef = useRef<HTMLButtonElement>(null);
    const dialogRef = useRef<HTMLDivElement>(null);
    // Escape cierra, Tab circula dentro del drawer y el scroll del body se
    // bloquea mientras esta abierto. El foco entra por el boton de cerrar y
    // vuelve al disparador al cerrar.
    useEffect(() => {
        const trigger = triggerRef.current;
        const onKey = (e: KeyboardEvent) => {
            if (e.key === 'Escape') {
                e.preventDefault();
                onClose();
                return;
            }
            if (e.key !== 'Tab') return;
            const dialog = dialogRef.current;
            if (!dialog) return;
            // El backdrop lleva tabIndex=-1 a proposito (cierra por fondo, no es
            // un control del ciclo) y la CTA del drawer puede estar display:none
            // por breakpoint: un focusable invisible o sin tab stop rompe el
            // ciclo (Shift+Tab escapaba al backdrop - auditor #1076).
            const focusable = Array.from(
                dialog.querySelectorAll<HTMLElement>(
                    'button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
                ),
            ).filter((el) => el.tabIndex >= 0 && el.getClientRects().length > 0);
            if (focusable.length === 0) {
                e.preventDefault();
                dialog.focus();
                return;
            }
            const first = focusable[0];
            const last = focusable[focusable.length - 1];
            if (e.shiftKey && document.activeElement === first) {
                e.preventDefault();
                last.focus();
            } else if (!e.shiftKey && document.activeElement === last) {
                e.preventDefault();
                first.focus();
            }
        };
        // Cruzar a md+ con el drawer abierto lo oculta (md:hidden) sin
        // cerrarlo: el body quedaria con overflow:hidden y el listener Tab
        // activo contra un menu invisible. Se cierra al cambiar el breakpoint.
        const mq = window.matchMedia('(min-width: 768px)');
        const onBreakpoint = () => {
            if (mq.matches) onClose();
        };
        mq.addEventListener('change', onBreakpoint);
        document.addEventListener('keydown', onKey);
        closeButtonRef.current?.focus();
        const prevOverflow = document.body.style.overflow;
        document.body.style.overflow = 'hidden';
        return () => {
            mq.removeEventListener('change', onBreakpoint);
            document.removeEventListener('keydown', onKey);
            document.body.style.overflow = prevOverflow;
            // Al cerrar por breakpoint (resize a md+) el trigger esta oculto:
            // enfocarlo seria mandar el foco a un elemento invisible; se suelta
            // al documento en su lugar (auditor #1076).
            if (trigger && trigger.getClientRects().length > 0) trigger.focus();
            else (document.activeElement as HTMLElement | null)?.blur?.();
        };
        // onClose y triggerRef son estables para la vida del drawer (el padre
        // lo desmonta al cerrar): el efecto corre una vez por apertura.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    return createPortal(
        <div
            ref={dialogRef}
            tabIndex={-1}
            className="fixed inset-0 z-[60] md:hidden"
            role="dialog"
            aria-modal="true"
            aria-labelledby="mobile-nav-title"
        >
            <h2 id="mobile-nav-title" className="sr-only">{t('shell.nav.menuTitle')}</h2>
            <button
                type="button"
                aria-label={t('shell.nav.closeBackdrop')}
                onClick={onClose}
                tabIndex={-1}
                className="absolute inset-0 cursor-default bg-black/60 backdrop-blur-sm"
            />
            <aside
                id="mobile-nav-drawer"
                ref={drawerRef}
                className="absolute left-0 top-0 flex h-full max-h-dvh w-[85vw] max-w-xs flex-col border-r border-gray-700/50 bg-gray-900 shadow-2xl"
            >
                <div className="flex min-h-16 items-center justify-between gap-2 border-b border-gray-700/50 px-4 py-3">
                    <GerarAIWordmark />
                    <button
                        type="button"
                        ref={closeButtonRef}
                        onClick={onClose}
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
                    className="flex-1 overflow-y-auto"
                    aria-label={t('shell.nav.mobileAria')}
                    onClick={(event) => {
                        if ((event.target as HTMLElement).closest('a[href]')) onClose();
                    }}
                >
                    <button type="button" className="mb-3 flex min-h-11 w-full items-center gap-3 rounded-lg px-3 py-2 text-left text-sm font-medium text-teal-300 hover:bg-gray-800" onClick={() => { onClose(); window.dispatchEvent(new Event('gerarai:open-brain')); }}>
                        <BrainGlassesIcon className="h-5 w-5" />Cerebro
                    </button>
                    <NavItems />
                </nav>
            </aside>
        </div>,
        document.body,
    );
}
