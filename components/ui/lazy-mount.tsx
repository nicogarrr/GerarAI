'use client';

import { useEffect, useRef, useState, type ReactNode } from 'react';

type Props = {
    children: ReactNode;
    /** Placeholder dentro de la caja reservada hasta el montaje (esqueleto). */
    fallback?: ReactNode;
    className?: string;
    /** Margen del IntersectionObserver. 0 por defecto: monta al asomar 1px. */
    rootMargin?: string;
};

/**
 * Montaje diferido al acercarse al viewport, para componentes pesados bajo
 * el pliegue. Caso: los gráficos recharts de la pestaña Resumen de
 * /portfolio (346 KB decodificados) viajaban en la carga inicial pese a
 * `dynamic(ssr:false)`, porque la pestaña por defecto los monta al hidratar
 * (medido 18-nov-2026: el gráfico NAV arranca a 864px y el donut a 1178px
 * con viewport de 844px). La caja reserva siempre el sitio (CLS 0), lo
 * montado no se desmonta nunca y sin IntersectionObserver (navegador viejo)
 * monta de inmediato: diferir es mejora, nunca requisito para ver el
 * contenido.
 */
export default function LazyMount({ children, fallback = null, className, rootMargin = '0px' }: Props) {
    const ref = useRef<HTMLDivElement>(null);
    const [visible, setVisible] = useState(false);
    useEffect(() => {
        if (visible) return;
        const el = ref.current;
        if (!el) return;
        if (typeof IntersectionObserver === 'undefined') {
            // Sin IO (navegador viejo) monta en el próximo frame: diferir es
            // mejora, nunca requisito. Async a propósito: un setState
            // síncrono en el efecto cascada renders (regla react-hooks).
            const id = requestAnimationFrame(() => setVisible(true));
            return () => cancelAnimationFrame(id);
        }
        const observer = new IntersectionObserver((entries) => {
            if (entries.some((entry) => entry.isIntersecting)) {
                setVisible(true);
                observer.disconnect();
            }
        }, { rootMargin });
        observer.observe(el);
        return () => observer.disconnect();
    }, [visible, rootMargin]);
    return <div ref={ref} className={className}>{visible ? children : fallback}</div>;
}
