/**
 * Tinta legible (negra o blanca) sobre el color de una zona DCA.
 *
 * El motor manda el color de fondo de cada zona y una tinta sugerida, pero
 * esa tinta no siempre cumple WCAG AA: texto blanco sobre el verde de «2X DCA»
 * (#00AA78) da 2,99:1 y sobre el rojo de «RECORTE FUERTE» (#FF193C) 3,85:1.
 * Aquí se elige, entre negro y blanco, la que más contraste da con ese fondo.
 * El color de la zona no se toca nunca.
 */

function channel(hex: string, offset: number): number {
    const value = parseInt(hex.slice(offset, offset + 2), 16) / 255;
    return value <= 0.03928 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
}

/** Luminancia relativa WCAG de un color `#RRGGBB` (o `#RGB`); null si no es hex. */
export function relativeLuminance(color: string): number | null {
    const raw = color.trim().replace(/^#/, '');
    const hex = raw.length === 3 ? raw.split('').map((c) => c + c).join('') : raw;
    if (!/^[0-9a-fA-F]{6}$/.test(hex)) return null;
    return 0.2126 * channel(hex, 0) + 0.7152 * channel(hex, 2) + 0.0722 * channel(hex, 4);
}

/** Razón de contraste WCAG entre dos luminancias. */
function contrast(a: number, b: number): number {
    const [hi, lo] = a >= b ? [a, b] : [b, a];
    return (hi + 0.05) / (lo + 0.05);
}

/**
 * Negro o blanco, la que más contraste dé sobre `background`. Si el fondo no
 * es un hex reconocible, devuelve `fallback` (la tinta que mandó el motor).
 */
export function readableInk(background: string | null | undefined, fallback?: string | null): string | undefined {
    const lum = background ? relativeLuminance(background) : null;
    if (lum === null) return fallback ?? undefined;
    return contrast(lum, 0) >= contrast(lum, 1) ? '#000000' : '#FFFFFF';
}
