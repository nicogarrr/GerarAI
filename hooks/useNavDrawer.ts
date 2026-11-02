import { useEffect, useRef, type RefObject } from 'react';

type NavDrawerOptions = {
    /** Mientras sea true el drawer esta abierto y el comportamiento activo. */
    active: boolean;
    onClose: () => void;
    dialogRef: RefObject<HTMLDivElement | null>;
    closeButtonRef: RefObject<HTMLButtonElement | null>;
    triggerRef: RefObject<HTMLButtonElement | null>;
};

/**
 * Comportamiento compartido de los drawers de navegación móvil
 * (MobileNavDrawer autenticado y PublicMobileNav público, que llevaban dos
 * copias del mismo efecto): Escape cierra, Tab circula dentro, el scroll del
 * body se bloquea mientras esta abierto, cruzar a md+ con el drawer abierto
 * lo cierra, y el foco entra por el botón de cerrar y vuelve al disparador.
 *
 * Sin directiva 'use client': un hook la hereda del componente que lo usa.
 */
export function useNavDrawer({ active, onClose, dialogRef, closeButtonRef, triggerRef }: NavDrawerOptions): void {
    // onClose puede cambiar de identidad entre renders del padre; el efecto
    // solo se reejecuta al abrir/cerrar, nunca a mitad de una interacción
    // (rearmarlo robaría el foco al botón de cerrar otra vez).
    const onCloseRef = useRef(onClose);
    useEffect(() => {
        onCloseRef.current = onClose;
    });

    useEffect(() => {
        if (!active) return;
        const close = () => onCloseRef.current();
        const trigger = triggerRef.current;
        const onKey = (e: KeyboardEvent) => {
            if (e.key === 'Escape') {
                e.preventDefault();
                close();
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
            if (mq.matches) close();
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
    }, [active, dialogRef, closeButtonRef, triggerRef]);
}
