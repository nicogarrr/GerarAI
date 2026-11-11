import { readFileSync } from 'node:fs';

import { contrastRatio } from './contrast-helpers';

// Guard de texto legible. Nace del NO FAV del auditor (11 nov): los grises de
// esta app NO son los de Tailwind — app/globals.css los redefine
// (gray-500=#a1a1aa, gray-400=#d4d4d8, gray-600=#3f3f46). Todo ratio se mide
// con los tokens parseados del CSS real, nunca con hex hardcodeados.
//
// Regla: un texto legible necesita
//   1. tamaño explícito >= 12 px (text-xs o superior; text-[10px]/text-[11px]
//      o ausencia de tamaño -> fallo), y
//   2. un color base explícito `text-<color>` (sin sufijo /opacidad y sin
//      prefijo hover:/focus-...) que mida >= 4.5:1 contra el fondo real
//      indicado. Token desconocido -> fallo cerrado.

const CSS_PATH = 'app/globals.css';

/** Tokens --color-* parseados del CSS real de la app. */
export function themeTokens(): Record<string, string> {
    const css = readFileSync(CSS_PATH, 'utf8');
    const out: Record<string, string> = {};
    for (const m of css.matchAll(/--color-([\w-]+):\s*(#[0-9a-fA-F]{6})/g)) {
        out[m[1]] = m[2].toLowerCase();
    }
    // `text-white` no pasa por --color-*: es blanco literal.
    out['white'] = '#ffffff';
    return out;
}

const PX: Record<string, number> = {
    'text-xs': 12,
    'text-sm': 14,
    'text-base': 16,
    'text-lg': 18,
    'text-xl': 20,
    'text-2xl': 24,
    'text-3xl': 30,
    'text-4xl': 36,
};

/** Tamaño en px del token de tamaño explícito, o null si no hay ninguno. */
export function explicitSizePx(tokens: string[]): number | null {
    for (const t of tokens) {
        if (t in PX) return PX[t];
        const arbitrary = t.match(/^text-\[(\d+)px\]$/);
        if (arbitrary) return Number(arbitrary[1]);
    }
    return null;
}

/**
 * Color base explícito: token `text-<color>` sin prefijo de variante y sin
 * sufijo /opacidad. Devuelve el nombre del color o null.
 */
// Utilidades text-* que no son color: no cuentan como base ni como intento de color.
const NON_COLOR = new Set([
    'left', 'center', 'right', 'justify', 'start', 'end',
    'balance', 'pretty', 'wrap', 'nowrap', 'ellipsis', 'clip',
]);

export function explicitBaseColor(tokens: string[]): string | null {
    for (const t of tokens) {
        if (t.includes(':')) continue; // hover:, focus:, dark:... no son base
        const m = t.match(/^text-([\w-]+)$/);
        if (!m) continue;
        if (t in PX || /^text-\[/.test(t)) continue; // es tamaño, no color
        if (NON_COLOR.has(m[1])) continue; // alineación o truncado, no color
        if (t.includes('/')) continue; // text-gray-500/80: tinta con opacidad, no vale
        return m[1];
    }
    return null;
}

export interface LegibleCheck {
    ok: boolean;
    reason?: string;
    ratio?: number;
}

/**
 * Verifica color + tamaño de un texto contra su fondo real.
 * `bg` es un token --color-* (p.ej. 'surface-0', 'gray-800').
 */
export function checkLegible(tokens: string[], bg: string, tokensCss = themeTokens()): LegibleCheck {
    const px = explicitSizePx(tokens);
    if (px === null) return { ok: false, reason: 'sin tamaño explícito' };
    if (px < 12) return { ok: false, reason: `tamaño ${px}px < 12px` };
    const color = explicitBaseColor(tokens);
    if (color === null) return { ok: false, reason: 'sin color base explícito (o con sufijo de opacidad)' };
    const fg = tokensCss[color];
    if (!fg) return { ok: false, reason: `token de color desconocido: ${color}` };
    const bgHex = tokensCss[bg];
    if (!bgHex) return { ok: false, reason: `token de fondo desconocido: ${bg}` };
    const ratio = contrastRatio(fg, bgHex);
    if (ratio < 4.5) return { ok: false, reason: `${color} sobre ${bg} mide ${ratio.toFixed(2)}:1 < 4.5:1`, ratio };
    return { ok: true, ratio };
}
