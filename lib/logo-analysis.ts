/**
 * Análisis de píxeles de un logo de proveedor (FMP image-stock).
 *
 * Dos problemas medidos sobre el universo (29 tickers, 2026-10-20):
 * - Placeholder invisible: FMP devuelve HTTP 200 con un PNG vacío (100%
 *   transparente o blanco) para tickers sin logo (HIMS, UNH, UBER), así que
 *   `onload` dispara y la caja blanca parecía «logo cargado». Blank = menos
 *   del 2% de píxeles con contenido -> la UI cae a las iniciales.
 * - Relleno horneado: el PNG incluye un margen blanco enorme (BN, AMZN,
 *   ONDS… contenido en el 16-48% del lienzo) y el logo se veía pequeño con
 *   marco. Se recorta a la caja de contenido (más 2px de respiro).
 *
 * El color de fondo para rellenar el contenedor se toma de la esquina del
 * logo original: un banner rectangular (CGEO.L) «llena» la caja con su
 * propio color en vez de con un marco blanco. Nada se inventa: todo sale
 * de los píxeles del proveedor.
 */

export type LogoBBox = { x: number; y: number; w: number; h: number };
export type LogoAnalysis = {
    /** true si la imagen no tiene logo visible (placeholder del proveedor). */
    blank: boolean;
    /** Caja del contenido no blanco/no transparente, con respiro de 2px. */
    bbox: LogoBBox;
    /** Color CSS de la esquina del logo original; null si es transparente. */
    background: string | null;
    /** Fracción de píxeles con contenido (0-1). */
    contentRatio: number;
};

const NEAR_WHITE = 248;
const TRIM_WHITE = 250;
const MIN_CONTENT_RATIO = 0.02;
const BREATHE = 2;

function isContent(data: Uint8ClampedArray, i: number, white: number): boolean {
    return data[i + 3] >= 10 && !(data[i] >= white && data[i + 1] >= white && data[i + 2] >= white);
}

export function analyzeLogoPixels(width: number, height: number, data: Uint8ClampedArray): LogoAnalysis {
    let content = 0;
    let minX = width, minY = height, maxX = -1, maxY = -1;
    for (let y = 0; y < height; y++) {
        for (let x = 0; x < width; x++) {
            const i = (y * width + x) * 4;
            if (!isContent(data, i, NEAR_WHITE)) continue;
            content++;
            if (isContent(data, i, TRIM_WHITE)) {
                if (x < minX) minX = x;
                if (x > maxX) maxX = x;
                if (y < minY) minY = y;
                if (y > maxY) maxY = y;
            }
        }
    }
    const contentRatio = content / (width * height);
    if (contentRatio < MIN_CONTENT_RATIO || maxX < 0) {
        return { blank: true, bbox: { x: 0, y: 0, w: width, h: height }, background: null, contentRatio };
    }
    const corner = data.slice(0, 4);
    const background = corner[3] >= 10 ? `rgb(${corner[0]}, ${corner[1]}, ${corner[2]})` : null;
    const x = Math.max(0, minX - BREATHE);
    const y = Math.max(0, minY - BREATHE);
    return {
        blank: false,
        bbox: {
            x,
            y,
            w: Math.min(width, maxX + 1 + BREATHE) - x,
            h: Math.min(height, maxY + 1 + BREATHE) - y,
        },
        background,
        contentRatio,
    };
}
