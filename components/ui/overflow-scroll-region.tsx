'use client';

import { useCallback, useEffect, useId, useRef, useState, type ReactNode } from 'react';

type OverflowScrollRegionProps = {
    /** Nombre accesible de la region (aria-label). */
    label: string;
    className?: string;
    children: ReactNode;
};

/**
 * Region con scroll horizontal que ANUNCIA de forma visible y accesible
 * cuando hay mas contenido a la derecha. Las sombras CSS de
 * `scroll-affordance-x` no se perciben en todos los navegadores, asi que
 * aqui se añade una pista textual explicita que:
 *  - solo aparece si hay overflow real (scrollWidth > clientWidth),
 *  - desaparece al llegar al final (nunca anuncia scroll que no existe),
 *  - se enlaza con aria-describedby para lectores de pantalla.
 */
export function OverflowScrollRegion({ label, className, children }: OverflowScrollRegionProps) {
    const ref = useRef<HTMLDivElement>(null);
    const hintId = useId();
    const [moreRight, setMoreRight] = useState(false);

    const update = useCallback(() => {
        const el = ref.current;
        if (!el) return;
        const remaining = el.scrollWidth - el.clientWidth - el.scrollLeft;
        setMoreRight(el.scrollWidth > el.clientWidth + 1 && remaining > 1);
    }, []);

    useEffect(() => {
        update();
        const el = ref.current;
        if (!el) return;
        const ro = new ResizeObserver(update);
        ro.observe(el);
        // El ancho del contenido (tabla) puede cambiar sin cambiar el contenedor.
        if (el.firstElementChild) ro.observe(el.firstElementChild);
        el.addEventListener('scroll', update, { passive: true });
        return () => {
            ro.disconnect();
            el.removeEventListener('scroll', update);
        };
    }, [update]);

    return (
        <div className={className}>
            {moreRight ? (
                <p className="mb-2 text-xs text-gray-500" id={hintId}>
                    Desliza para ver más columnas <span aria-hidden="true">→</span>
                </p>
            ) : null}
            <div
                ref={ref}
                aria-describedby={moreRight ? hintId : undefined}
                aria-label={label}
                className="scroll-affordance-x overflow-x-auto"
                role="region"
                tabIndex={0}
            >
                {children}
            </div>
        </div>
    );
}
