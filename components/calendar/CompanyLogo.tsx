'use client';

import { useEffect, useRef, useState } from 'react';

import { NameAvatar } from '@/components/ui/name-avatar';
import { analyzeLogoPixels } from '@/lib/logo-analysis';

type Props = {
    ticker: string;
    name: string;
    className?: string;
};

type LogoArt = { src: string; background: string | null; forTicker: string };

/**
 * Logo real de empresa: imagen pública y gratuita de Financial Modeling Prep
 * (sin clave, por ticker). Verdad medida sobre el universo (2026-10-20):
 *
 * - FMP devuelve HTTP 200 con un PNG VACÍO para tickers sin logo (HIMS, UNH,
 *   UBER): `onload` dispara igual y la caja blanca parecía logo cargado. Al
 *   cargar se miden los píxeles en un canvas (FMP manda CORS *) y si el
 *   contenido visible es <2% se declara fallo y se ven las iniciales.
 * - Muchos PNG llevan el margen blanco horneado (BN, AMZN…): se recorta a
 *   la caja de contenido para que el logo llene el contenedor.
 * - Un logo rectangular (CGEO.L) rellena la caja con el color de su propia
 *   esquina, no con un marco blanco; un logo con transparencia (AAPL) sigue
 *   sobre fondo blanco para que el glifo oscuro se lea.
 *
 * Sin canvas (navegador raro o CORS retirado) se degrada a mostrar la imagen
 * tal cual, como antes. Nunca un hueco vacío ni el logo de otra empresa.
 */
export function CompanyLogo({ ticker, name, className }: Props) {
    const [art, setArt] = useState<LogoArt | null>(null);
    const [failedFor, setFailedFor] = useState<string | null>(null);
    const [plainFor, setPlainFor] = useState<string | null>(null);
    const img = useRef<HTMLImageElement>(null);

    const ready = art?.forTicker === ticker ? art : null;
    const failed = failedFor === ticker;
    const plain = plainFor === ticker;
    const loading = !ready && !failed && !plain;

    const inspect = (el: HTMLImageElement) => {
        if (el.naturalWidth === 0) {
            setFailedFor(ticker);
            return;
        }
        try {
            const scale = Math.min(1, 256 / Math.max(el.naturalWidth, el.naturalHeight));
            const w = Math.max(1, Math.round(el.naturalWidth * scale));
            const h = Math.max(1, Math.round(el.naturalHeight * scale));
            const canvas = document.createElement('canvas');
            canvas.width = w;
            canvas.height = h;
            const ctx = canvas.getContext('2d', { willReadFrequently: true });
            if (!ctx) {
                setPlainFor(ticker);
                return;
            }
            ctx.drawImage(el, 0, 0, w, h);
            const analysis = analyzeLogoPixels(w, h, ctx.getImageData(0, 0, w, h).data);
            if (analysis.blank) {
                setFailedFor(ticker);
                return;
            }
            const { x, y, w: cw, h: ch } = analysis.bbox;
            const src =
                cw >= w && ch >= h
                    ? el.src
                    : (() => {
                          const crop = document.createElement('canvas');
                          crop.width = cw;
                          crop.height = ch;
                          crop.getContext('2d')?.drawImage(canvas, x, y, cw, ch, 0, 0, cw, ch);
                          return crop.toDataURL('image/png');
                      })();
            setArt({ src, background: analysis.background, forTicker: ticker });
        } catch {
            // Canvas contaminado o no disponible: la imagen se muestra tal cual.
            setPlainFor(ticker);
        }
    };

    useEffect(() => {
        const el = img.current;
        if (!el || !el.complete || !loading) return;
        inspect(el);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [ticker, loading]);

    if (failed) {
        return <NameAvatar name={name || ticker} className={className} />;
    }

    return (
        <span
            className={`relative inline-block shrink-0 overflow-hidden ${className ?? ''} ${
                ready && !ready.background ? 'bg-white' : ''
            }`}
            style={ready?.background ? { background: ready.background } : undefined}
        >
            {loading ? <NameAvatar name={name || ticker} className="absolute inset-0 size-full" /> : null}
            {/* eslint-disable-next-line @next/next/no-img-element -- proveedor externo de logos con análisis de píxeles y fallback controlado; next/image exigiría fijar el dominio en config */}
            <img
                ref={img}
                src={`https://financialmodelingprep.com/image-stock/${encodeURIComponent(ticker)}.png`}
                alt=""
                crossOrigin="anonymous"
                referrerPolicy="no-referrer"
                onLoad={(e) => inspect(e.currentTarget)}
                onError={() => setFailedFor(ticker)}
                className={
                    ready
                        ? 'absolute inset-0 size-full object-contain'
                        : `absolute inset-0 size-full bg-white object-contain p-1 ${loading ? 'opacity-0' : ''}`
                }
            />
        </span>
    );
}
