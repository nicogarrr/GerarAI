'use client';

import { useEffect, useRef, useState } from 'react';

import { NameAvatar } from '@/components/ui/name-avatar';
import { analyzeLogoPixels } from '@/lib/logo-analysis';
import { DARK_LOGO_BACKGROUND, logoSources } from '@/lib/logos/logo-sources';

type Props = {
    ticker: string;
    name: string;
    className?: string;
};

type LogoArt = { src: string; background: string | null; forKey: string };

/**
 * Logo real de empresa con cadena de fuentes (lib/logos/logo-sources.ts):
 * FMP image-stock por ticker -> icono oficial de la web de la empresa vía
 * nuestra ruta cacheada /api/logo -> iniciales. Verdad medida (2026-10-27):
 *
 * - UBER, UNH, HIMS y V NO estaban vacíos: FMP los sirve como glifo BLANCO
 *   sobre transparente. El análisis anterior contaba el blanco como «nada» y
 *   caía a las iniciales. Ahora el análisis mide por alfa y, si el glifo es
 *   claro, se pinta sobre fondo oscuro para que se lea.
 * - Placeholder real (PNG vacío) o 404 (AENA sin sufijo) -> siguiente fuente.
 * - Muchos PNG llevan el margen blanco horneado (BN, AMZN…): se recorta a
 *   la caja de contenido para que el logo llene el contenedor.
 * - Un logo rectangular (CGEO.L) rellena la caja con el color de su propia
 *   esquina, no con un marco blanco; un logo oscuro con transparencia (AAPL)
 *   sigue sobre fondo blanco para que el glifo se lea.
 *
 * Sin canvas (navegador raro o CORS retirado) se degrada a mostrar la imagen
 * tal cual. Nunca un hueco vacío ni el logo de otra empresa.
 */
export function CompanyLogo({ ticker, name, className }: Props) {
    const sources = logoSources(ticker);
    const [art, setArt] = useState<LogoArt | null>(null);
    // Índice de la fuente en curso; la clave ata cada estado a su ticker.
    const [attempt, setAttempt] = useState<{ ticker: string; index: number }>({ ticker, index: 0 });
    const [plainFor, setPlainFor] = useState<string | null>(null);
    const img = useRef<HTMLImageElement>(null);

    const index = attempt.ticker === ticker ? attempt.index : 0;
    const src = sources[index] ?? null;
    const key = `${ticker}#${index}`;
    const ready = art?.forKey === key ? art : null;
    const failed = src === null;
    const plain = plainFor === key;
    const loading = !ready && !failed && !plain;

    const next = () => setAttempt({ ticker, index: index + 1 });

    const inspect = (el: HTMLImageElement) => {
        if (el.naturalWidth === 0) {
            next();
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
                setPlainFor(key);
                return;
            }
            ctx.drawImage(el, 0, 0, w, h);
            const analysis = analyzeLogoPixels(w, h, ctx.getImageData(0, 0, w, h).data);
            if (analysis.blank) {
                next();
                return;
            }
            const { x, y, w: cw, h: ch } = analysis.bbox;
            const cropped =
                cw >= w && ch >= h
                    ? el.src
                    : (() => {
                          const crop = document.createElement('canvas');
                          crop.width = cw;
                          crop.height = ch;
                          crop.getContext('2d')?.drawImage(canvas, x, y, cw, ch, 0, 0, cw, ch);
                          return crop.toDataURL('image/png');
                      })();
            const background = analysis.background ?? (analysis.onDark ? DARK_LOGO_BACKGROUND : null);
            setArt({ src: cropped, background, forKey: key });
        } catch {
            // Canvas contaminado o no disponible: la imagen se muestra tal cual.
            setPlainFor(key);
        }
    };

    useEffect(() => {
        const el = img.current;
        if (!el || !el.complete || !loading) return;
        inspect(el);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [key, loading]);

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
            {/* eslint-disable-next-line @next/next/no-img-element -- fuentes de logo con análisis de píxeles y fallback controlado; next/image exigiría fijar el dominio en config */}
            <img
                key={key}
                ref={img}
                src={ready ? ready.src : src}
                alt=""
                crossOrigin="anonymous"
                referrerPolicy="no-referrer"
                onLoad={(e) => {
                    if (!ready) inspect(e.currentTarget);
                }}
                onError={next}
                className={
                    ready
                        ? 'absolute inset-0 size-full object-contain'
                        : `absolute inset-0 size-full bg-white object-contain p-1 ${loading ? 'opacity-0' : ''}`
                }
            />
        </span>
    );
}
