import { readFileSync } from 'node:fs';

import { describe, expect, it } from 'vitest';

// Zonas táctiles 44px medidas en prod 18-nov-2026 (viewport 320px):
//  - /research/AAPL, lista de eventos del gráfico (PriceEventsPanel): el botón
//    de fecha medía 16px y el toggle «Detalle» ~13px de alto. La fila ya tenía
//    el patrón aprobado en el enlace de fuente (min-h-11 real, no pseudo:
//    los vecinos son interactivos y la fila envuelve). Se extiende a ambos
//    botones con sm:min-h-0 para devolver el ritmo denso en escritorio.
//  - /insider (InsiderSignalsView): el enlace del ticker en el título medía
//    22px (inline aislado → pseudo before:-inset-y-3.5/-x-1.5, patrón de /temas; la caja mide ~20px
//    y con ±14px el área efectiva medida es ~48px — con -inset-y-2 eran 36px y
//    con -inset-y-3 ~43px, ambos <44 medidos por Auditoría/barrido en Chrome) y el enlace SEC «Ver filing» ~16px (min-h-11 real).

const panel = readFileSync('components/research/PriceEventsPanel.tsx', 'utf8');
const signals = readFileSync('components/insider/InsiderSignalsView.tsx', 'utf8');

describe('PriceEventsPanel: fecha y «Detalle» con zona táctil 44px en móvil', () => {
    it('el botón de fecha lleva min-h-11 con salida sm:min-h-0', () => {
        expect(panel).toContain('inline-flex min-h-11 min-w-11 items-center tabular-nums text-gray-400 underline-offset-2 hover:underline sm:min-h-0 sm:min-w-0');
    });

    it('el toggle Detalle/Menos lleva min-h-11 con salida sm:min-h-0', () => {
        expect(panel).toContain('inline-flex min-h-11 min-w-11 items-center text-xs text-gray-500 hover:text-gray-200 sm:min-h-0 sm:min-w-0');
    });

    it('no quedan los botones sin expansión', () => {
        expect(panel).not.toContain('className="tabular-nums text-gray-400 underline-offset-2 hover:underline"');
        expect(panel).not.toContain('className="text-xs text-gray-500 hover:text-gray-200">{open');
    });
});

describe('InsiderSignalsView: ticker del título y enlace SEC con 44px', () => {
    it('el ticker del título lleva pseudo-expansión (enlace inline aislado)', () => {
        expect(signals).toContain("relative font-mono text-teal-300 before:absolute before:-inset-x-1.5 before:-inset-y-3.5 before:content-[''] hover:text-teal-200 hover:underline");
    });

    it('el enlace SEC lleva min-h-11 con salida sm:min-h-0', () => {
        expect(signals).toContain('inline-flex min-h-11 items-center gap-1 text-xs text-teal-300 hover:text-teal-200 hover:underline sm:min-h-0');
    });

    it('no quedan las clases antiguas', () => {
        expect(signals).not.toContain('className="font-mono text-teal-300 hover:text-teal-200 hover:underline"');
        expect(signals).not.toContain('before:-inset-y-2 before:content-'); // 36px efectivos: insuficiente (Auditoría)
        expect(signals).not.toContain('before:-inset-y-3 ' + "before:content-"); // ~43px medidos: sigue sin llegar a 44
        expect(signals).not.toContain('className="inline-flex items-center gap-1 text-xs text-teal-300 hover:text-teal-200 hover:underline"');
    });
});
