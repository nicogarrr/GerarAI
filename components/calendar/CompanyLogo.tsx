'use client';

import { useEffect, useRef, useState } from 'react';

import { NameAvatar } from '@/components/ui/name-avatar';

type Props = {
    ticker: string;
    name: string;
    className?: string;
};

/**
 * Logo real de empresa: imagen pública y gratuita de Financial Modeling Prep
 * (sin clave, por ticker). Mientras carga, o si el proveedor no tiene ese
 * ticker, se ve el mosaico de iniciales: nunca un hueco vacío ni el logo de
 * otra empresa. Un error que ocurre antes de hidratar (la imagen ya terminó
 * cuando React engancha `onError`) se recupera mirando `complete`.
 */
export function CompanyLogo({ ticker, name, className }: Props) {
    const [state, setState] = useState<'loading' | 'loaded' | 'failed'>('loading');
    const img = useRef<HTMLImageElement>(null);

    useEffect(() => {
        const el = img.current;
        if (!el || !el.complete) return;
        setState(el.naturalWidth > 0 ? 'loaded' : 'failed');
    }, [ticker]);

    if (state === 'failed') {
        return <NameAvatar name={name || ticker} className={className} />;
    }

    return (
        <span className={`relative inline-block shrink-0 overflow-hidden ${className ?? ''}`}>
            {state === 'loading' ? <NameAvatar name={name || ticker} className="absolute inset-0 size-full" /> : null}
            {/* eslint-disable-next-line @next/next/no-img-element -- proveedor externo de logos con fallback controlado; next/image exigiría fijar el dominio en config */}
            <img
                ref={img}
                src={`https://financialmodelingprep.com/image-stock/${encodeURIComponent(ticker)}.png`}
                alt=""
                referrerPolicy="no-referrer"
                onLoad={() => setState('loaded')}
                onError={() => setState('failed')}
                className={`absolute inset-0 size-full bg-white object-contain p-1 ${state === 'loaded' ? '' : 'opacity-0'}`}
            />
        </span>
    );
}
