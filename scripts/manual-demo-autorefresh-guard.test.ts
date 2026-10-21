/**
 * Guarda del auto-refresco de la valoración demo (pedido de Nico 21-oct-2026:
 * «No se actualiza sola»). La valoración mostrada se reconsulta sola, pero el
 * registro de operaciones sigue manual y el fanout al proveedor queda acotado.
 *
 * Ejecución: node --experimental-strip-types --test scripts/manual-demo-autorefresh-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const panel = readFileSync('components/paper-trading/ManualDemoPanel.tsx', 'utf8');

describe('auto-refresco de la valoración demo', () => {
    it('reutiliza la acción de valoración existente (sin endpoint ni fanout nuevo)', () => {
        // Solo llama a refreshValuation (prop): nada de fetch propio ni actions.
        assert.doesNotMatch(panel, /fetch\(|lib\/actions\//);
        assert.match(panel, /refreshValuation\(\)/);
    });

    it('cadencia de 60 s, la del patrón Mercados del mismo proveedor', () => {
        assert.match(panel, /VALUATION_REFRESH_MS = 60_000/);
        assert.match(panel, /window\.setInterval\(tick, VALUATION_REFRESH_MS\)/);
        assert.match(panel, /window\.clearInterval\(timer\)/);
    });

    it('puertas de sostenibilidad: pestaña visible, posiciones abiertas y sin solapes en vuelo', () => {
        assert.match(panel, /document\.visibilityState !== 'visible' \|\| inFlight\) return/);
        assert.match(panel, /if \(!refreshValuation \|\| !hasPositions\) return/);
        assert.match(panel, /let inFlight = false/);
        assert.match(panel, /inFlight = false/);
        // Repuesta al volver a la pestaña solo si pasó un ciclo completo.
        assert.match(panel, /visibilitychange/);
        assert.match(panel, /Date\.now\(\) - lastAttempt >= VALUATION_REFRESH_MS/);
    });

    it('el botón manual se conserva como refresco inmediato', () => {
        assert.match(panel, /Actualizar cotizaciones|Consultar cotizaciones/);
        assert.match(panel, /onClick=\{onRefresh\}/);
    });

    it('el copy ya no afirma que no se actualiza sola y sigue siendo honesto', () => {
        assert.doesNotMatch(panel, /No se actualiza sola/);
        assert.match(panel, /Se actualiza cada minuto mientras esta pestaña está visible/);
    });

    it('el registro de operaciones sigue manual: nada de autoprellenar fills con cotización', () => {
        const ticket = readFileSync('components/paper-trading/OrderTicket.tsx', 'utf8');
        assert.doesNotMatch(ticket, /setPrice\(.*quote|setPrice\(.*valuation|markPrice/i);
        assert.match(ticket, /no es una ejecución de\s+mercado/i);
    });
});
