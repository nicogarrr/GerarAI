import { useEffect, useRef, type RefObject } from 'react';

type NativeNavDrawerOptions = {
    /** Mientras sea true el drawer esta abierto y el comportamiento activo. */
    active: boolean;
    onClose: () => void;
    dialogRef: RefObject<HTMLDialogElement | null>;
    closeButtonRef: RefObject<HTMLButtonElement | null>;
    triggerRef: RefObject<HTMLButtonElement | null>;
};

/**
 * Comportamiento del drawer de navegación móvil sobre <dialog> NATIVO modal
 * (guía Modern Web Guidance, dialog regla 1). El navegador aporta lo que la
 * versión anterior reconstruía a mano en useNavDrawer: página inerte, foco
 * contenido, top layer, Esc (cancel -> close) y devolución del foco al
 * disparador. Aquí solo queda lo que el navegador NO hace:
 *
 * - abrir con showModal() al montar y propagar el cierre nativo a React
 *   (evento 'close' -> onClose, que desmonta el componente);
 * - cerrar al cruzar a md+ (el drawer se oculta con md:hidden y un modal
 *   nativo invisible no puede quedar activo);
 * - cierre por fondo donde closedby="any" no existe (Safari, ver guía):
 *   se mide la posición del puntero, no el target - el propio <dialog> es
 *   target de su padding y de los huecos entre sus hijos;
 * - foco inicial en el botón de cerrar (paridad con la versión manual).
 *
 * No se modifica el scroll del body: la contención va en CSS con
 * overscroll-behavior como mejora progresiva, sin retirar la barra raíz.
 * El top layer bloquea interacción, pero no garantiza scroll lock en Safari.
 *
 * Sin directiva 'use client': un hook la hereda del componente que lo usa.
 */
export function useNativeNavDrawer({ active, onClose, dialogRef, closeButtonRef, triggerRef }: NativeNavDrawerOptions): void {
    // onClose puede cambiar de identidad entre renders del padre; el efecto
    // solo se reejecuta al abrir/cerrar, nunca a mitad de una interacción.
    const onCloseRef = useRef(onClose);
    useEffect(() => {
        onCloseRef.current = onClose;
    });

    useEffect(() => {
        if (!active) return;
        const dialog = dialogRef.current;
        if (!dialog) return;

        // closedby se lee al abrir: debe estar puesto ANTES de showModal.
        // React todavía no tipa el atributo; setAttribute evita el cast.
        dialog.setAttribute('closedby', 'any');
        if (!dialog.open) dialog.showModal();

        // Cierre nativo (Esc, gesto atrás, backdrop con closedby o fallback,
        // breakpoint): se propaga a React, que desmonta el drawer. Si el
        // cierre fue por resize a md+ el disparador está oculto y el foco no
        // puede quedar en un elemento invisible (#1076): se suelta al documento.
        const onNativeClose = () => {
            // Ignore an old queued close event after a StrictMode reopen.
            if (dialog.open) return;
            const trigger = triggerRef.current;
            if (trigger && trigger.getClientRects().length === 0) {
                (document.activeElement as HTMLElement | null)?.blur?.();
            }
            onCloseRef.current();
        };
        dialog.addEventListener('close', onNativeClose);

        // closedby="any" no existe en Safari: cierre por fondo manual como
        // mejora progresiva, exigiendo presión Y suelta fuera (un arrastre de
        // selección que termina en el fondo no despide el drawer).
        let removeLightDismiss: (() => void) | undefined;
        if (!('closedBy' in HTMLDialogElement.prototype)) {
            const outside = (e: PointerEvent) => {
                const r = dialog.getBoundingClientRect();
                return e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom;
            };
            let pressedOutside = false;
            const onDown = (e: PointerEvent) => { pressedOutside = outside(e); };
            const onUp = (e: PointerEvent) => { if (pressedOutside && outside(e)) dialog.close(); };
            dialog.addEventListener('pointerdown', onDown);
            dialog.addEventListener('pointerup', onUp);
            removeLightDismiss = () => {
                dialog.removeEventListener('pointerdown', onDown);
                dialog.removeEventListener('pointerup', onUp);
            };
        }

        // Cruzar a md+ con el drawer abierto lo oculta (md:hidden): se cierra
        // de verdad para no dejar un modal nativo invisible activo.
        const mq = window.matchMedia('(min-width: 768px)');
        const onBreakpoint = () => {
            if (mq.matches && dialog.open) dialog.close();
        };
        mq.addEventListener('change', onBreakpoint);

        // showModal enfoca el diálogo; la paridad con la versión anterior pide
        // el foco en el botón de cerrar (primer control del panel).
        closeButtonRef.current?.focus();
        // The lazy chunk can arrive after the viewport already crossed md.
        onBreakpoint();

        return () => {
            mq.removeEventListener('change', onBreakpoint);
            removeLightDismiss?.();
            dialog.removeEventListener('close', onNativeClose);
            if (dialog.open) dialog.close();
        };
    }, [active, dialogRef, closeButtonRef, triggerRef]);
}
