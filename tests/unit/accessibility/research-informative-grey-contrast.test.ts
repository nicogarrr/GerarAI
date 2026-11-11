import { readFileSync } from 'node:fs';

import { describe, expect, it } from 'vitest';

import { checkLegible, themeTokens } from './legible-text-guard';

// Texto informativo gris en la ficha research: WCAG 2.2 SC 1.4.3 + tamaño de
// letra. Auditoría rehecha tras el NO FAV (11 nov): los grises de esta app NO
// son los de Tailwind — app/globals.css los redefine (gray-500=#a1a1aa,
// gray-400=#d4d4d8) — y todo ratio se mide con los tokens parseados del CSS
// real (ver legible-text-guard.ts).
//
// Con tokens reales, gray-500 mide 6.91-7.72:1 sobre las superficies: ya
// cumplía AA en color. Lo que NO cumplía y se corrige en esta PR:
//   - ThesisMemo: leyenda del medidor a 10px y títulos de procedencia a 11px.
//   - QuickGlancePanel: notas bajo cada etiqueta a 11px.
// Los demás elementos auditados (page.tsx, CompanyPositionPanel,
// ExpertThesisPanel) quedan cubiertos aquí como guardia de regresión: se
// midió que ya cumplen y no llevan cambio visual.

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

describe('gris informativo en research (tokens reales del tema)', () => {
    it('los tokens del tema se parsean del CSS real (no hardcodes de Tailwind)', () => {
        const css = themeTokens();
        expect(css['gray-500']).toBe('#a1a1aa');
        expect(css['gray-400']).toBe('#d4d4d8');
        expect(css['surface-0']).toBe('#0a0a0b');
    });

    it('ThesisMemo: la leyenda del medidor y los títulos de grupo de procedencia son legibles', () => {
        const src = readFileSync('components/research/ThesisMemo.tsx', 'utf8');
        expectLegible(classNamesWith(src, /\{legend\}/), 'surface-0', 'la leyenda del medidor de ThesisMemo');
        expectLegible(classNamesWith(src, /PROVENANCE_GROUP_KEYS/), 'surface-0', 'los títulos de grupo de procedencia de ThesisMemo');
    });

    it('QuickGlancePanel: las notas bajo cada etiqueta son legibles', () => {
        const src = readFileSync('components/research/QuickGlancePanel.tsx', 'utf8');
        expectLegible(classNamesWith(src, /\{note\}/), 'surface-1', 'las notas de QuickGlancePanel');
    });

    it('page.tsx: los textos informativos de escenarios, historial y foso son legibles', () => {
        const src = readFileSync('app/(root)/research/[ticker]/page.tsx', 'utf8');
        expectLegible(classNamesWith(src, /\{trackRecord\}/), 'surface-0', 'trackRecord');
        expectLegible(classNamesWith(src, /\{sbcLine\}/), 'surface-0', 'sbcLine');
        expectLegible(classNamesWith(src, /\{assumptionsText\}/), 'surface-0', 'assumptionsText');
        expectLegible(classNamesWith(src, /ml-auto text-xs/), 'surface-0', 'la fecha de cada versión');
        expectLegible(classNamesWith(src, /fichaFirstVersionNoDiff/), 'surface-0', 'el aviso de primera versión sin diff');
        expectLegible(classNamesWith(src, /\{definition \?/), 'surface-0', 'la definición del foso');
        expectLegible(classNamesWith(src, /fichaMoatClaims/), 'surface-0', 'el recuento de claims del foso');
        expectLegible(classNamesWith(src, /financialPeriod\(metric\.period/), 'surface-0', 'periodo de la métrica financiera');
        const peerTarget = [...src.matchAll(/className="([^"]*)"[^>]*>\{t\('research\.fichaPeerTarget/g)].map((m) => classTokens(m[1]));
        expectLegible(peerTarget, 'surface-0', 'objetivo de la métrica de pares');
        expectLegible(classNamesWith(src, /fichaUnknownAuthor/), 'surface-0', 'autor de la lectura');
    });

    it('CompanyPositionPanel: las etiquetas de la posición son legibles', () => {
        const src = readFileSync('components/research/CompanyPositionPanel.tsx', 'utf8');
        // Las <dt> heredan el tamaño del bloque (text-sm del panel): el guard
        // exige tamaño explícito, así que se comprueba con el tamaño heredado.
        const dts = [...src.matchAll(/<dt className="([^"]*)"/g)].map((m) => classTokens(m[1]));
        expect(dts.length, 'no se encuentran las etiquetas del panel de posición').toBeGreaterThan(0);
        for (const t of dts) {
            const check = checkLegible(['text-sm', ...t], 'surface-1');
            expect(check.ok, `etiqueta del panel de posición: ${check.reason ?? ''}`).toBe(true);
        }
    });

    it('ExpertThesisPanel: la nota y el timeout del juez son legibles', () => {
        const src = readFileSync('components/research/ExpertThesisPanel.tsx', 'utf8');
        expectLegible(classNamesWith(src, /brain\.expertTeam\.thesis\.note/, 1), 'surface-1', 'la nota de la tesis');
        expectLegible(classNamesWith(src, /expert-thesis-judge-timeout/), 'surface-1', 'el aviso de juez sin veredicto');
    });

    it('mutantes: el guard real rechaza gray-600, gray-500/80, sin color base y <12px', () => {
        expect(checkLegible(['text-xs', 'text-gray-600'], 'surface-0').ok, 'gray-600 (1.89:1 medido) debe fallar').toBe(false);
        expect(checkLegible(['text-xs', 'text-gray-500/80'], 'surface-0').ok, 'gray-500/80 (sin base plena) debe fallar').toBe(false);
        expect(checkLegible(['text-xs'], 'surface-0').ok, 'sin color base debe fallar').toBe(false);
        expect(checkLegible(['text-[10px]', 'text-gray-400'], 'surface-0').ok, '10px debe fallar').toBe(false);
        expect(checkLegible(['text-[11px]', 'text-gray-400'], 'surface-0').ok, '11px debe fallar').toBe(false);
        expect(checkLegible(['text-gray-400'], 'surface-0').ok, 'sin tamaño explícito debe fallar').toBe(false);
        expect(checkLegible(['text-xs', 'text-nonexistent-500'], 'surface-0').ok, 'token desconocido debe fallar cerrado').toBe(false);
        // Y acepta lo que de verdad cumple (gray-500 real = 7.72:1 sobre surface-0):
        expect(checkLegible(['text-xs', 'text-gray-500'], 'surface-0').ok).toBe(true);
        expect(checkLegible(['text-xs', 'text-gray-400'], 'surface-0').ok).toBe(true);
    });
});
