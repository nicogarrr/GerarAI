import { relativeLuminance } from '@/lib/dca/readable-ink';

/** Utilidades WCAG para los tests de contraste (blend de opacidad + ratio). */

export function lum(color: string): number {
    const [r, g, b] = parseColor(color);
    const to2 = (n: number) => n.toString(16).padStart(2, '0');
    const value = relativeLuminance(`#${to2(r)}${to2(g)}${to2(b)}`);
    if (value === null) throw new Error(`color no reconocido: ${color}`);
    return value;
}

/** Acepta `#RRGGBB` o `rgb(r, g, b)` (jsdom normaliza el estilo inline a rgb). */
export function parseColor(value: string): [number, number, number] {
    const rgb = value.match(/rgb\(\s*(\d+),\s*(\d+),\s*(\d+)\s*\)/);
    if (rgb) return [Number(rgb[1]), Number(rgb[2]), Number(rgb[3])];
    return [
        parseInt(value.slice(1, 3), 16),
        parseInt(value.slice(3, 5), 16),
        parseInt(value.slice(5, 7), 16),
    ];
}

export function blendOver(inkHex: string, bgHex: string, opacity: number): string {
    const [r1, g1, b1] = parseColor(inkHex);
    const [r2, g2, b2] = parseColor(bgHex);
    const mix = (a: number, b: number) => Math.round(opacity * a + (1 - opacity) * b);
    const to2 = (n: number) => n.toString(16).padStart(2, '0');
    return `#${to2(mix(r1, r2))}${to2(mix(g1, g2))}${to2(mix(b1, b2))}`;
}

export function contrastRatio(fgHex: string, bgHex: string): number {
    const [hi, lo] = [lum(fgHex), lum(bgHex)].sort((a, b) => b - a);
    return (hi + 0.05) / (lo + 0.05);
}

/** Tinta efectiva de un elemento: su color CSS mezclado con la opacidad de la utilidad `opacity-NN` de sus clases. */
export function effectiveInk(el: Element, fallbackInk: string): { effective: string; opacity: number } {
    const ink = (el as HTMLElement).style.color || fallbackInk;
    const opacityMatch = el.className.match(/opacity-(\d+)/);
    const opacity = opacityMatch ? Number(opacityMatch[1]) / 100 : 1;
    return { effective: ink, opacity };
}
