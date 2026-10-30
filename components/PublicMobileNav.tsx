'use client';

import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import Link from 'next/link';
import { Menu, X } from 'lucide-react';
import { GerarAIWordmark } from '@/components/GerarAIWordmark';
import { useT } from '@/lib/i18n/client';

export interface PublicNavLinkItem {
    href: string;
    label: string;
}

/**
 * Navegacion movil del header PUBLICO. Antes la lista de paginas (Metodologia,
 * Ayuda) ocupaba una segunda fila permanente del header sticky por
 * debajo de md (`public-header-inner` en columna), robando viewport al
 * contenido en cada pagina publica. Ahora el header es una sola fila en todos
 * los viewports y esos enlaces viven en un drawer con hamburger (>=44px).
 *
 * Misma disciplina que MobileNav (portal a document.body por el backdrop-blur
 * del header, Escape cierra, Tab circula dentro, scroll del body bloqueado,
 * foco entra por el boton de cerrar y vuelve al disparador), sin buscador ni
 * sesion porque el header publico no tiene ninguno. El breakpoint es `md` en
 * los dos lados (esta clase y `.public-nav`) a proposito: entre sm y md no
 * puede quedar un hueco sin navegacion.
 */
export default function PublicMobileNav({ links, cta }: { links: PublicNavLinkItem[]; cta?: PublicNavLinkItem }) {
    const t = useT();
    const [open, setOpen] = useState(false);
    const triggerRef = useRef<HTMLButtonElement>(null);
    const closeButtonRef = useRef<HTMLButtonElement>(null);
    const dialogRef = useRef<HTMLDivElement>(null);

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
                aria-label={t('shell.publicNav.openMenu')}
                aria-expanded={open}
                aria-controls="public-mobile-nav-drawer"
                className="inline-flex min-h-11 min-w-11 items-center justify-center rounded-lg p-2 text-gray-300 transition-colors hover:bg-gray-700/50 hover:text-white md:hidden"
            >
                <Menu className="h-6 w-6" aria-hidden="true" />
            </button>

            {/* Portal a document.body: el header usa backdrop-blur, que convierte
                position:fixed de los descendientes en relativo al header (ver
                MobileNav). */}
            {open &&
                createPortal(
                    <div
                        ref={dialogRef}
                        tabIndex={-1}
                        className="fixed inset-0 z-[60] md:hidden"
                        role="dialog"
                        aria-modal="true"
                        aria-labelledby="public-mobile-nav-title"
                    >
                        <h2 id="public-mobile-nav-title" className="sr-only">{t('shell.publicNav.menuTitle')}</h2>
                        <button
                            type="button"
                            aria-label={t('shell.nav.closeBackdrop')}
                            onClick={close}
                            tabIndex={-1}
                            className="absolute inset-0 cursor-default bg-black/60 backdrop-blur-sm"
                        />
                        <aside
                            id="public-mobile-nav-drawer"
                            className="absolute right-0 top-0 flex h-full max-h-dvh w-[85vw] max-w-xs flex-col border-l border-gray-700/50 bg-gray-900 shadow-2xl"
                        >
                            <div className="flex min-h-16 items-center justify-between gap-2 border-b border-gray-700/50 px-4 py-3">
                                <GerarAIWordmark />
                                <button
                                    type="button"
                                    ref={closeButtonRef}
                                    onClick={close}
                                    aria-label={t('shell.publicNav.closeMenu')}
                                    className="inline-flex min-h-11 min-w-11 items-center justify-center rounded-lg p-2 text-gray-300 transition-colors hover:bg-gray-700/50 hover:text-white"
                                >
                                    <X className="h-6 w-6" aria-hidden="true" />
                                </button>
                            </div>

                            {/* El cierre va en cada enlace, no en el <nav> (ver
                                MobileNav). */}
                            <nav
                                className="flex-1 overflow-y-auto px-3 py-3"
                                aria-label={t('shell.publicNav.pagesAria')}
                                onClick={(event) => {
                                    if ((event.target as HTMLElement).closest('a[href]')) close();
                                }}
                            >
                                {/* La CTA de registro viaja aqui cuando no cabe en
                                    la fila (<640px): ocultarla sin copia seria
                                    perderla en los moviles mas estrechos. */}
                                {cta ? (
                                    <Link
                                        href={cta.href}
                                        onClick={close}
                                        className="mb-3 flex min-h-11 items-center justify-center rounded-lg bg-teal-500 px-3 text-sm font-semibold text-gray-950 transition-colors hover:bg-teal-400 sm:hidden"
                                    >
                                        {cta.label}
                                    </Link>
                                ) : null}
                                <ul className="flex flex-col gap-1">
                                    {links.map((link) => (
                                        <li key={link.href}>
                                            <Link
                                                href={link.href}
                                                className="flex min-h-11 items-center rounded-lg px-3 text-sm font-medium text-gray-300 transition-colors hover:bg-gray-700/30 hover:text-white"
                                            >
                                                {link.label}
                                            </Link>
                                        </li>
                                    ))}
                                </ul>
                            </nav>
                        </aside>
                    </div>,
                    document.body,
                )}
        </>
    );
}
