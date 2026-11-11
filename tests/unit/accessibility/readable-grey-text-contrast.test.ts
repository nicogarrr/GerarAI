import { readFileSync } from 'node:fs';

import { describe, expect, it } from 'vitest';

import { contrastRatio } from './contrast-helpers';
import { checkLegible, explicitBaseColor, explicitSizePx, themeTokens } from './legible-text-guard';

// Texto de lectura en temas, cuellos, macro-calendar, LiveMarketsPanel,
// SignInForm y ManualDemoPanel, y ticks de ShareCapitalChart. Auditoría de
// contraste (11 nov) rehecha tras el NO FAV: los grises de esta app NO son
// los de Tailwind — app/globals.css los redefine (gray-500=#a1a1aa,
// gray-400=#d4d4d8) — y todo ratio se mide con los tokens parseados del CSS
// real (ver legible-text-guard.ts).
//
// Con tokens reales, gray-500 mide 6.91-7.72:1 sobre surface-0/1 y gray-800:
// ya cumplía AA. Lo que NO cumplía y se corrige aquí:
//   - texto a 10-11 px en los elementos auditados (temas badge y razón,
//     cuellos badge y meta) -> se sube a text-xs (12px).
// Los ticks de PortfolioNavChart (#6b7280 duro, 3.94:1 sobre surface-1) los
// cubre la PR del agente de cartera; los de ShareCapitalChart ya son #9ca3af.

function classTokens(className: string): string[] {
    return className.split(/\s+/).filter(Boolean);
}

/** className de la línea con el ancla (o hasta `back` líneas antes, para JSX multilínea). */
function classNamesWith(src: string, anchor: RegExp, back = 0): string[][] {
    const lines = src.split('\n');
    return lines
        .flatMap((line, i) => (anchor.test(line) ? lines.slice(Math.max(0, i - back), i + 1) : []))
        .flatMap((line) => [...line.matchAll(/className="([^"]*)"/g)].map((m) => classTokens(m[1])));
}

function expectLegible(tokens: string[][], bg: string, what: string): void {
    expect(tokens.length, `no se encuentra ${what}`).toBeGreaterThan(0);
    for (const t of tokens) {
        const check = checkLegible(t, bg);
        expect(check.ok, `${what}: ${check.reason ?? ''}`).toBe(true);
    }
}

describe('texto de lectura en temas/cuellos/macro/mercados/auth/paper-trading', () => {
    it('los tokens del tema se parsean del CSS real (no hardcodes de Tailwind)', () => {
        const css = themeTokens();
        expect(css['gray-500']).toBe('#a1a1aa');
        expect(css['gray-400']).toBe('#d4d4d8');
        expect(css['surface-0']).toBe('#0a0a0b');
        expect(css['gray-800']).toBe('#18181b');
    });

    it('temas: el rank, la razón del ticker y el badge son legibles', () => {
        const src = readFileSync('app/(root)/temas/page.tsx', 'utf8');
        expectLegible(classNamesWith(src, /\{rank === null/), 'surface-0', 'el rank del tema');
        expectLegible(classNamesWith(src, /themeReasonText\(row\.reason/, 1), 'surface-0', 'la razón del ticker');
        // El badge lleva color dinámico por kind dentro de un template
        // literal: tamaño explícito >= 12px (su contraste, medido abajo, cumple).
        const badgeTpl = src.match(/className=\{`([^`]*font-bold uppercase[^`]*)`\}/s);
        expect(badgeTpl, 'no se encuentra el badge del tema').not.toBeNull();
        const badgeTokens = classTokens(badgeTpl![1].replace(/\$\{[^}]*\}/g, ' '));
        expect(explicitSizePx(badgeTokens), 'el badge del tema no puede bajar de 12px').toBeGreaterThanOrEqual(12);
    });

    it('cuellos: el badge N/D y la meta de descubrimiento son legibles', () => {
        const src = readFileSync('app/(root)/cuellos/page.tsx', 'utf8');
        expectLegible(classNamesWith(src, /bg-gray-800 px-1\.5 py-0\.5/), 'gray-800', 'el badge N/D');
        expectLegible(classNamesWith(src, /discoveryMeta/, 1), 'surface-0', 'la meta de descubrimiento');
    });

    it('macro-calendar: la fecha de presentación es legible', () => {
        const src = readFileSync('app/(root)/macro-calendar/page.tsx', 'utf8');
        expectLegible(classNamesWith(src, /entry\.filed_at/), 'surface-0', 'la fecha de presentación');
    });

    it('LiveMarketsPanel: símbolos, identidad, hora, notas, vacío y pie son legibles', () => {
        const src = readFileSync('components/markets/LiveMarketsPanel.tsx', 'utf8');
        expectLegible(classNamesWith(src, /\{spec\.symbol\}/), 'surface-0', 'el símbolo sin cotización');
        expectLegible(classNamesWith(src, /identityLine\(quote/), 'surface-0', 'la línea de identidad');
        expectLegible(classNamesWith(src, /quote\.timestamp \? timeFormatter/, 1), 'surface-0', 'la hora de la cotización');
        expectLegible(classNamesWith(src, /flex items-center justify-between gap-2 text-xs/), 'surface-0', 'la cabecera de actualización');
        expectLegible(classNamesWith(src, /\{t\(tab\.note\)\}/), 'surface-0', 'la nota de cada pestaña');
        expectLegible(classNamesWith(src, /groupEmpty/, 1), 'surface-0', 'el estado vacío de grupo');
        expectLegible(classNamesWith(src, /markets\.live\.footer/, 1), 'surface-0', 'el pie del panel');
    });

    it('SignInForm: el subtítulo 2FA y el botón de volver son legibles', () => {
        const src = readFileSync('components/forms/SignInForm.tsx', 'utf8');
        expectLegible(classNamesWith(src, /auth\.twoFactor\.subtitle/, 1), 'surface-0', 'el subtítulo de 2FA');
        expectLegible(classNamesWith(src, /w-full text-center text-sm/), 'surface-0', 'el botón de volver');
    });

    it('ManualDemoPanel: nota de valoración, avisos de no cableado y valoración obsoleta son legibles', () => {
        const src = readFileSync('components/paper-trading/ManualDemoPanel.tsx', 'utf8');
        expectLegible(classNamesWith(src, /paperTrading\.valuation\.note/, 1), 'surface-1', 'la nota de valoración');
        expectLegible(classNamesWith(src, /paperTrading\.panel\.notWired/, 1), 'surface-1', 'el aviso de panel no cableado');
        expectLegible(classNamesWith(src, /valuation\.(stale|unavailable)/, 2), 'surface-1', 'la valoración obsoleta o no disponible');
    });

    it('ShareCapitalChart: los ticks miden >= 4.5:1 con tokens reales', () => {
        const src = readFileSync('components/research/ShareCapitalChart.tsx', 'utf8');
        const fills = [...src.matchAll(/tick=\{\{[^}]*fill: '(#[0-9a-f]{6})'/g)].map((m) => m[1]);
        expect(fills.length, 'no se encuentran los ticks del gráfico').toBeGreaterThan(0);
        const css = themeTokens();
        for (const fill of fills) {
            // fill es un hex duro del chart: se mide tal cual contra surface-1 real.
            expect(contrastRatio(fill, css['surface-1']), `tick ${fill} bajo AA sobre surface-1`).toBeGreaterThanOrEqual(4.5);
        }
    });

    it('mutantes: el guard real rechaza gray-600, gray-500/80, sin color base y <12px', () => {
        // Invoca el guard real (checkLegible), no una copia.
        expect(checkLegible(['text-xs', 'text-gray-600'], 'surface-0').ok, 'gray-600 (1.89:1) debe fallar').toBe(false);
        expect(checkLegible(['text-xs', 'text-gray-500/80'], 'surface-0').ok, 'gray-500/80 (sin base plena) debe fallar').toBe(false);
        expect(checkLegible(['text-xs'], 'surface-0').ok, 'sin color base debe fallar').toBe(false);
        expect(checkLegible(['text-[11px]', 'text-gray-400'], 'surface-0').ok, '11px debe fallar').toBe(false);
        expect(checkLegible(['text-[10px]', 'text-gray-400'], 'surface-0').ok, '10px debe fallar').toBe(false);
        expect(checkLegible(['text-gray-400'], 'surface-0').ok, 'sin tamaño explícito debe fallar').toBe(false);
        expect(checkLegible(['text-xs', 'text-nonexistent-500'], 'surface-0').ok, 'token desconocido debe fallar cerrado').toBe(false);
        // Y acepta lo que de verdad cumple (medido: gray-500 real = 7.72:1, gray-400 real = 13.39:1 sobre surface-0):
        expect(checkLegible(['text-xs', 'text-gray-500'], 'surface-0').ok).toBe(true);
        expect(checkLegible(['text-xs', 'text-gray-400'], 'surface-0').ok).toBe(true);
        // text-center u otras utilidades text-* no color no estorban:
        expect(explicitBaseColor(classTokens('py-6 text-center text-sm text-gray-500'))).toBe('gray-500');
    });
});
