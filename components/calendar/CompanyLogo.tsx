'use client';

import { useState } from 'react';

import { NameAvatar } from '@/components/ui/name-avatar';

type Props = {
    ticker: string;
    name: string;
    className?: string;
};

/**
 * Logo real de empresa: imagen pública y gratuita de Financial Modeling Prep
 * (sin clave, por ticker). Si el proveedor no tiene ese ticker (404), cae al
 * mosaico de iniciales de siempre: nunca se muestra el logo de otra empresa.
 */
export function CompanyLogo({ ticker, name, className }: Props) {
    const [failed, setFailed] = useState(false);

    if (failed) {
        return <NameAvatar name={name || ticker} className={className} />;
    }

    return (
        // eslint-disable-next-line @next/next/no-img-element -- proveedor externo de logos con fallback controlado; next/image exigiría fijar el dominio en config
        <img
            src={`https://financialmodelingprep.com/image-stock/${encodeURIComponent(ticker)}.png`}
            alt=""
            loading="lazy"
            referrerPolicy="no-referrer"
            onError={() => setFailed(true)}
            className={`bg-white object-contain p-1 ${className ?? ''}`}
        />
    );
}
