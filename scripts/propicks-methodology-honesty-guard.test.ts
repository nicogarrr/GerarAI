/**
 * Guarda F178: la metodología de ProPicks no puede prometer lo que v1 no
 * tiene. Antes /metodologia afirmaba que la selección combina valor y
 * momentum con rebalanceo mensual y backtest por estrategia publicado,
 * mientras el embudo v1 de la misma página declara que valoración y
 * momentum aún NO entran (necesitan series de precios no persistidas).
 * La tarjeta «Sobre ProPicks IA» de /propicks listaba «✓ Evaluación de
 * momentum» y «✓ Comparación con sector», ambas falsas en v1 (el ranking
 * es por percentiles del universo, sin momentum).
 *
 * Ejecución: node --experimental-strip-types --test scripts/propicks-methodology-honesty-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, '..');
const readSource = (rel: string) => readFileSync(join(root, rel), 'utf8');

describe('propicks methodology honesty guard (F178)', () => {
    it('la metodología no promete valor/momentum ni backtest por estrategia como presente', () => {
        const page = readSource('app/(public)/metodologia/page.tsx') + readSource('lib/i18n/messages/es/landing.json');
        assert.ok(!page.includes('están publicadas con sus métricas'), 'las estrategias no se declaran publicadas');
        assert.ok(!page.includes('se rebalancea el día 1 de cada'), 'sin rebalanceo mensual prometido');
        assert.ok(
            page.includes('y el momentum aún no entran en el embudo v1'),
            'el resumen declara que valoración y momentum aún no entran en v1',
        );
        assert.ok(
            page.includes('baseline de momentum solo-precio: no es un backtest de ProPicks'),
            'el walk-forward global se etiqueta como baseline, no como backtest de ProPicks',
        );
        assert.ok(
            page.includes('El backtest por estrategia se publicará cuando existan fundamentales point-in-time'),
            'el backtest por estrategia se declara pendiente, no publicado',
        );
    });

    it('el embudo v1 sigue declarando explícitamente lo que NO incluye', () => {
        const page = readSource('app/(public)/metodologia/page.tsx') + readSource('lib/i18n/messages/es/landing.json');
        assert.ok(
            page.includes('Lo que v1 NO incluye todavía:'),
            'tripwire: la declaración de límites de v1 no debe desaparecer',
        );
    });

    it('Descubrir ya no tiene el bloque «Sobre ProPicks IA» ni lista capacidades ausentes en v1', () => {
        const card = readSource('components/proPicks/EnhancedProPicksContent.tsx');
        assert.ok(!card.includes('Sobre ProPicks IA'), 'el bloque se eliminó a petición del propietario');
        assert.ok(!card.includes('✓ Evaluación de momentum'), 'momentum no se lista como capacidad actual');
        assert.ok(!card.includes('✓ Comparación con sector'), 'sin comparación sectorial prometida');
    });
});
