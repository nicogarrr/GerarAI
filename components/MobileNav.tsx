'use client';

import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Menu, X } from 'lucide-react';
import { GerarAIWordmark } from '@/components/GerarAIWordmark';
import NavItems from '@/components/NavItems';
import SearchCommand from '@/components/SearchCommand';
import { BrainGlassesIcon } from '@/components/brain/BrainGlassesIcon';

/**
 * Navegacion movil: boton hamburger (>=44px) que abre un drawer con el MISMO
 * arbol que el sidebar de escritorio.
 *
 * El breakpoint es `md` en los dos lados a proposito. Antes el trigger era
 * `sm:hidden` y el sidebar `md:flex`, asi que entre 640px y 767px no existia
 * ninguna navegacion por secciones: solo logo, buscador y avatar.
 */
export default function MobileNav({ initialStocks }: { initialStocks?: StockWithWatchlistStatus[] }) {
    const [open, setOpen] = useState(false);
    const triggerRef = useRef<HTMLButtonElement>(null);
    const drawerRef = useRef<HTMLDivElement>(null);
    const closeButtonRef = useRef<HTMLButtonElement>(null);
    const dialogRef = useRef<HTMLDivElement>(null);
    // Escape cierra, Tab circula dentro del drawer y el scroll del body se
    // bloquea mientras esta abierto. El foco entra por el boton de cerrar y
    // vuelve al disparador al cerrar.
    useEffect(() => {
        if (!open) return;
        const trigger = triggerRef.current;
        const onKey = (e: KeyboardEvent) => {
            if (e.key === 'Escape') {
                e.preventDefault();
                setOpen(false);
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
            if (mq.matches) setOpen(false);
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
    }, [open]);

    const close = () => setOpen(false);

    return (
        <>
            <button
                type="button"
                ref={triggerRef}
                onClick={() => setOpen(true)}
                aria-label="Abrir menú de navegación"
                aria-expanded={open}
                aria-controls="mobile-nav-drawer"
                className="inline-flex min-h-11 min-w-11 items-center justify-center rounded-lg p-2 text-gray-300 transition-colors hover:bg-gray-700/50 hover:text-white md:hidden"
            >
                <Menu className="h-6 w-6" aria-hidden="true" />
            </button>

            {/* Portal a document.body: el header usa backdrop-blur, que convierte
                position:fixed de los descendientes en relativo al header y
                aplastaba el drawer sobre el contenido (capas solapadas). */}
            {open &&
                createPortal(
                    <div
                        ref={dialogRef}
                        tabIndex={-1}
                        className="fixed inset-0 z-[60] md:hidden"
                        role="dialog"
                        aria-modal="true"
                        aria-labelledby="mobile-nav-title"
                    >
                        <h2 id="mobile-nav-title" className="sr-only">Menú de navegación</h2>
                        <button
                            type="button"
                            aria-label="Cerrar menú por fondo"
                            onClick={close}
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
                                    onClick={close}
                                    aria-label="Cerrar menú de navegación"
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
                                aria-label="Navegación móvil"
                                onClick={(event) => {
                                    if ((event.target as HTMLElement).closest('a[href]')) close();
                                }}
                            >
                                <button type="button" className="mb-3 flex min-h-11 w-full items-center gap-3 rounded-lg px-3 py-2 text-left text-sm font-medium text-teal-300 hover:bg-gray-800" onClick={() => { setOpen(false); window.dispatchEvent(new Event('gerarai:open-brain')); }}>
                                    <BrainGlassesIcon className="h-5 w-5" />Cerebro
                                </button>
                                <NavItems />
                            </nav>
                        </aside>
                    </div>,
                    document.body,
                )}
        </>
    );
}
