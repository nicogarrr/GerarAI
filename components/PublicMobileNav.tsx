'use client';

import { useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import Link from 'next/link';
import { Menu, X } from 'lucide-react';
import { GerarAIWordmark } from '@/components/GerarAIWordmark';
import { useT } from '@/lib/i18n/client';
import { useNativeNavDrawer } from '@/hooks/useNativeNavDrawer';

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
 * del header; modal nativo con showModal para aislamiento, foco y Escape,
 * sin trap manual ni cambios en overflow del body), sin buscador ni
 * sesion porque el header publico no tiene ninguno. El breakpoint es `md` en
 * los dos lados (esta clase y `.public-nav`) a proposito: entre sm y md no
 * puede quedar un hueco sin navegacion.
 */
export default function PublicMobileNav({ links, cta }: { links: PublicNavLinkItem[]; cta?: PublicNavLinkItem }) {
    const t = useT();
    const [open, setOpen] = useState(false);
    const triggerRef = useRef<HTMLButtonElement>(null);
    const closeButtonRef = useRef<HTMLButtonElement>(null);
    const dialogRef = useRef<HTMLDialogElement>(null);

    // Native close events sync React state; the shared hook also handles md
    // resize and progressive backdrop dismissal without a body scroll lock.
    useNativeNavDrawer({ active: open, onClose: () => setOpen(false), dialogRef, closeButtonRef, triggerRef });

    const close = () => dialogRef.current?.close();

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
                    <dialog
                        ref={dialogRef}
                        id="public-mobile-nav-drawer"
                        aria-labelledby="public-mobile-nav-title"
                        className="fixed left-auto right-0 top-0 z-[60] m-0 open:flex h-full max-h-dvh w-[85vw] max-w-xs flex-col border-l border-gray-700/50 bg-gray-900 p-0 text-gray-300 shadow-2xl md:hidden [&:modal]:overscroll-contain backdrop:bg-black/60 backdrop:backdrop-blur-sm backdrop:overscroll-contain backdrop:overflow-hidden"
                    >
                        <h2 id="public-mobile-nav-title" className="sr-only">{t('shell.publicNav.menuTitle')}</h2>
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
                            className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-3 py-3"
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
                    </dialog>,
                    document.body,
                )}
        </>
    );
}
