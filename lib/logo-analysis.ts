/**
 * Análisis de píxeles de un logo de proveedor (FMP image-stock).
 *
 * Problemas medidos sobre el universo (2026-10-20 y 2026-10-27):
 * - Placeholder invisible: para un ticker sin logo el proveedor puede
 *   devolver HTTP 200 con un PNG vacío (100% transparente o blanco), así que
 *   `onload` dispara y la caja blanca parecía «logo cargado». Blank = menos
 *   del 2% de píxeles con contenido -> la UI pasa a la siguiente fuente.
 * - Logo BLANCO sobre transparente (UBER, UNH, HIMS, V; medido 2026-10-27):
 *   NO es un placeholder. El PNG trae el glifo en blanco puro con canal alfa.
 *   La versión anterior contaba el blanco como «sin contenido» y declaraba
 *   blank estos logos reales -> iniciales. Ahora, si la imagen tiene
 *   transparencia y casi todo lo opaco es blanco, el contenido se mide por
 *   alfa y se pide fondo oscuro (`onDark`) para que el glifo se lea.
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
    /** Caja del contenido visible, con respiro de 2px. */
    bbox: LogoBBox;
    /** Color CSS de la esquina del logo original; null si es transparente. */
    background: string | null;
    /** true si el glifo es claro sobre transparente: pintar sobre fondo oscuro. */
    onDark: boolean;
    /** Fracción de píxeles con contenido (0-1). */
    contentRatio: number;
};

const NEAR_WHITE = 248;
const TRIM_WHITE = 250;
const MIN_CONTENT_RATIO = 0.02;
const BREATHE = 2;
const OPAQUE = 10;
/** Fracción mínima de píxeles transparentes para tratar la imagen como recortada. */
const MIN_TRANSPARENT_RATIO = 0.05;
/** Fracción de lo opaco que es blanco a partir de la cual el logo es «claro». */
const LIGHT_GLYPH_RATIO = 0.6;

function isWhite(data: Uint8ClampedArray, i: number, white: number): boolean {
    return data[i] >= white && data[i + 1] >= white && data[i + 2] >= white;
}

export function analyzeLogoPixels(width: number, height: number, data: Uint8ClampedArray): LogoAnalysis {
    const total = width * height;
    // Primera pasada: ¿hay transparencia real y el glifo opaco es blanco?
    let transparent = 0;
    let opaque = 0;
    let opaqueWhite = 0;
    for (let i = 0; i < total * 4; i += 4) {
        if (data[i + 3] < OPAQUE) {
            transparent++;
            continue;
        }
        opaque++;
        if (isWhite(data, i, NEAR_WHITE)) opaqueWhite++;
    }
    const onDark =
        transparent / total >= MIN_TRANSPARENT_RATIO && opaque > 0 && opaqueWhite / opaque >= LIGHT_GLYPH_RATIO;

    // Logo claro: cuenta todo lo opaco. Resto: lo opaco que no es blanco.
    const isContent = (i: number, white: number) =>
        data[i + 3] >= OPAQUE && (onDark || !isWhite(data, i, white));

    let content = 0;
    let minX = width, minY = height, maxX = -1, maxY = -1;
    for (let y = 0; y < height; y++) {
        for (let x = 0; x < width; x++) {
            const i = (y * width + x) * 4;
            if (!isContent(i, NEAR_WHITE)) continue;
            content++;
            if (isContent(i, TRIM_WHITE)) {
                if (x < minX) minX = x;
                if (x > maxX) maxX = x;
                if (y < minY) minY = y;
                if (y > maxY) maxY = y;
            }
        }
    }
    const contentRatio = content / total;
    if (contentRatio < MIN_CONTENT_RATIO || maxX < 0) {
        return {
            blank: true,
            bbox: { x: 0, y: 0, w: width, h: height },
            background: null,
            onDark: false,
            contentRatio,
        };
    }
    const corner = data.slice(0, 4);
    const background = corner[3] >= OPAQUE ? `rgb(${corner[0]}, ${corner[1]}, ${corner[2]})` : null;
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
        onDark: onDark && background === null,
        contentRatio,
    };
}
