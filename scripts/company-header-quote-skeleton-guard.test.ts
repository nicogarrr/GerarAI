import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

/**
 * Guard: la cabecera de la ficha (#grafico) llega por streaming (Suspense de
 * CompanyHeaderQuote). Si el fallback no reserva la altura final, la página
 * salta bajo los ojos del usuario cuando se resuelve (~487px en móvil,
 * medido en el trace de Browser E2E del 2026-10-19). El fallback debe ser el
 * skeleton estructural que replica cotización + métricas + gráfico, nunca un
 * bloque bajo genérico.
 */
describe('ficha: el fallback de la cotización reserva la altura final (sin CLS)', () => {
    it('page.tsx usa CompanyHeaderQuoteSkeleton como fallback del Suspense', () => {
        const page = readFileSync('app/(root)/research/[ticker]/page.tsx', 'utf8');
        assert.ok(
            page.includes('fallback={<CompanyHeaderQuoteSkeleton />}'),
            'el Suspense de #grafico usa CompanyHeaderQuoteSkeleton',
        );
        assert.ok(
            !page.includes('h-40 animate-pulse rounded bg-gray-900/60'),
            'el fallback bajo genérico (h-40) no vuelve',
        );
    });
    it('el skeleton reserva cotización, tira de métricas y el hueco del gráfico', () => {
        const skeleton = readFileSync('components/research/CompanyHeaderQuoteSkeleton.tsx', 'utf8');
        assert.ok(skeleton.includes('h-[400px]'), 'reserva el gráfico con la altura del placeholder de CompanyTechnicalWorkspace');
        assert.ok(skeleton.includes('grid-cols-2') && skeleton.includes('sm:grid-cols-4'), 'replica la tira de métricas (2 cols móvil / 4 sm+)');
        assert.ok(skeleton.includes('animate-pulse'), 'sigue siendo un skeleton con pulso');
        assert.ok(!skeleton.includes("'use client'"), 'el skeleton no necesita cliente');
    });
    it('el placeholder del gráfico dinámico mantiene su reserva h-[400px]', () => {
        const workspace = readFileSync('components/research/CompanyTechnicalWorkspace.tsx', 'utf8');
        assert.ok(workspace.includes('h-[400px]'), 'CompanyTechnicalWorkspace sigue reservando 400px al cargar el chunk');
    });
});
