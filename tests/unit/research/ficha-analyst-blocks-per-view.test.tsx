import { readFileSync } from 'node:fs';

import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { FichaHeaderAnalystBlocks } from '@/components/research/FichaHeaderAnalystBlocks';
import { showAnalystBlocks, TABS, type View } from '@/lib/research/research-views';

// Visibilidad por pestaña de los bloques de cabecera de la ficha research.
// Los paneles de analistas, historial de analistas y señales DCA se
// renderizaban en TODAS las pestañas y empujaban el contenido propio de
// cada una ~1588px hacia abajo en móvil (medido por Piloto en Tesis,
// 18-nov-2026). Regla: identidad, navegación y cotización compacta quedan
// en todas las pestañas; analistas/historial/DCA solo en Resumen/Finanzas.
//
// Cobertura: la página (async RSC con ~40 lecturas de backend) no es
// montable en vitest — V8 la reporta 0/0 porque ningún test la importa —
// así que la decisión vive en showAnalystBlocks (pura) y en
// FichaHeaderAnalystBlocks (presentacional), ambos ejecutados aquí por
// comportamiento. page.tsx queda guardado por inspección estructural del
// JSX real (región exacta del elemento, no hasta </header>).

const VIEWS_CON_BLOQUES: View[] = ['overview', 'financials'];
const VIEWS_SIN_BLOQUES: View[] = ['thesis', 'valuation', 'changes', 'documents'];

function renderGate(activeView: View) {
    return render(
        <FichaHeaderAnalystBlocks
            activeView={activeView}
            analystTargets={<div data-testid="analistas" />}
            analystHistory={<div data-testid="historial-analistas" />}
            dca={<div data-testid="dca" />}
        />,
    );
}

describe('showAnalystBlocks: puerta pura por vista', () => {
    it.each(VIEWS_CON_BLOQUES)('%s muestra los bloques', (view) => {
        expect(showAnalystBlocks(view)).toBe(true);
    });

    it.each(VIEWS_SIN_BLOQUES)('%s no muestra los bloques', (view) => {
        expect(showAnalystBlocks(view)).toBe(false);
    });

    it('los dos grupos cubren exactamente las pestañas de entrada, sin solape', () => {
        // activeView solo toma el módulo de entrada de cada pestaña: los
        // grupos con/sin bloques deben particionar esas seis vistas.
        const entrada = TABS.map((tab) => tab.entry).sort();
        const cubiertas = [...VIEWS_CON_BLOQUES, ...VIEWS_SIN_BLOQUES].sort();
        expect(new Set(cubiertas).size).toBe(cubiertas.length);
        expect(cubiertas).toEqual(entrada);
    });
});

describe('FichaHeaderAnalystBlocks: comportamiento de render por vista', () => {
    it.each(VIEWS_CON_BLOQUES)('%s monta los tres bloques', (view) => {
        renderGate(view);
        expect(screen.getByTestId('analistas')).toBeTruthy();
        expect(screen.getByTestId('historial-analistas')).toBeTruthy();
        expect(screen.getByTestId('dca')).toBeTruthy();
    });

    it.each(VIEWS_SIN_BLOQUES)('%s no monta ningún bloque', (view) => {
        renderGate(view);
        expect(screen.queryByTestId('analistas')).toBeNull();
        expect(screen.queryByTestId('historial-analistas')).toBeNull();
        expect(screen.queryByTestId('dca')).toBeNull();
    });
});

describe('page.tsx: cableado estructural', () => {
    const SRC = readFileSync('app/(root)/research/[ticker]/page.tsx', 'utf8');

    /** Región JSX exacta del elemento FichaHeaderAnalystBlocks (apertura a cierre propio). */
    function gateRegion(): string {
        const open = SRC.indexOf('<FichaHeaderAnalystBlocks');
        expect(open, 'la página no usa FichaHeaderAnalystBlocks').toBeGreaterThan(-1);
        // El cierre del elemento es la línea con la indentación propia
        // (10 espacios + />): los /> internos de las props van más indentados.
        const close = SRC.indexOf('\n          />', open);
        expect(close, 'no se encuentra el cierre del elemento').toBeGreaterThan(-1);
        return SRC.slice(open, close);
    }

    it.each([
        ['objetivos de analistas', 'id="analistas"'],
        ['historial de analistas', 'id="historial-analistas"'],
        ['señales DCA', 'DcaHitRatesSection'],
    ])('%s se pasa dentro del elemento de la puerta', (_what, marker) => {
        expect(gateRegion(), `${marker} fuera de la puerta`).toContain(marker);
    });

    it.each([
        ['objetivos de analistas', 'id="analistas"'],
        ['historial de analistas', 'id="historial-analistas"'],
    ])('%s aparece una sola vez en la página', (_what, marker) => {
        expect(SRC.split(marker).length - 1, `${marker} duplicado`).toBe(1);
    });

    it('la puerta recibe la vista activa de la página', () => {
        expect(gateRegion()).toContain('activeView={activeView}');
    });

    it('la cotización (#grafico) queda fuera y antes de la puerta: visible en todas las pestañas', () => {
        const quote = SRC.indexOf('id="grafico"');
        expect(quote, 'no se encuentra #grafico').toBeGreaterThan(-1);
        expect(quote, '#grafico quedó dentro de la puerta').toBeLessThan(SRC.indexOf('<FichaHeaderAnalystBlocks'));
    });

    it('QuickGlancePanel enlaza #analistas, ancla que existe en Resumen (puerta abierta)', () => {
        // El panel solo se monta en buildOverviewContent y la puerta abre en
        // overview: el enlace interno no puede quedar huérfano.
        const glance = readFileSync('components/research/QuickGlancePanel.tsx', 'utf8');
        expect(glance).toContain('href="#analistas"');
        expect(showAnalystBlocks('overview')).toBe(true);
    });
});
