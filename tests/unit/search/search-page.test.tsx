import React from 'react';
import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

/**
 * Render REAL de /search frente a respuestas hostiles del backend (ref
 * 760826059): un 200 con cuerpo inesperado no puede pintarse como «sin
 * evidencia» ni reventar la página; un ítem incompleto no puede lanzar en el
 * Server Component.
 */
const mocks = vi.hoisted(() => ({ researchRequest: vi.fn() }));
vi.mock('@/lib/i18n/server', async () => {
    const { createTranslator } = await import('@/lib/i18n/translate');
    return { getLocale: async () => 'es', getT: async () => createTranslator('es') };
});
vi.mock('@/lib/research/client', () => ({ researchRequest: mocks.researchRequest, jsonBody: (v: unknown) => JSON.stringify(v) }));
vi.mock('@/components/search/TickerSearchInput', () => ({ TickerSearchInput: () => null }));
vi.mock('@/components/system/BackendOffline', () => ({
    default: ({ feature, retryHref, as }: { feature: string; retryHref: string; as?: string }) => (
        <div data-as={as ?? 'main'} data-testid="backend-offline">{feature}:{retryHref}</div>
    ),
}));
import UniversalSearchPage from '@/app/(root)/search/page';

const page = () => UniversalSearchPage({ searchParams: Promise.resolve({ q: 'test' }) } as never);
const offline = () => screen.queryByTestId('backend-offline');

beforeEach(() => {
    mocks.researchRequest.mockReset();
});

describe('/search con respuestas del backend', () => {
    it('cero legítimo (200, items=[]): estado vacío, SIN estado de error', async () => {
        mocks.researchRequest.mockResolvedValue({ query: 'test', items: [], page_info: { total_items: 0 } });
        render(await page());
        expect(screen.getByText('Ninguna evidencia coincide con la consulta y los filtros.')).toBeInTheDocument();
        expect(offline()).not.toBeInTheDocument();
    });

    it('cuerpo null: error de contrato logueado con [search] y estado local, nunca vacío falso', async () => {
        const spy = vi.spyOn(console, 'error').mockImplementation(() => undefined);
        mocks.researchRequest.mockResolvedValue(null);
        render(await page());
        expect(offline()).toHaveTextContent('Búsqueda universal:/search?q=test');
        expect(screen.queryByText('Ninguna evidencia coincide con la consulta y los filtros.')).not.toBeInTheDocument();
        expect(spy.mock.calls.some((call) => String(call[0]).includes('[search]'))).toBe(true);
        spy.mockRestore();
    });

    it('items como objeto: error de contrato, estado local', async () => {
        const spy = vi.spyOn(console, 'error').mockImplementation(() => undefined);
        mocks.researchRequest.mockResolvedValue({ items: { bad: true } });
        render(await page());
        expect(offline()).toBeInTheDocument();
        expect(spy.mock.calls.some((call) => String(call[0]).includes('[search]'))).toBe(true);
        spy.mockRestore();
    });

    it('[null] dentro de la lista: se filtra y la página pinta el vacío legítimo sin lanzar', async () => {
        mocks.researchRequest.mockResolvedValue({ query: 'test', items: [null], page_info: { total_items: 1 } });
        render(await page());
        expect(screen.getByText('Ninguna evidencia coincide con la consulta y los filtros.')).toBeInTheDocument();
        expect(offline()).not.toBeInTheDocument();
    });

    it('ítem sin scores: se pinta sin lanzar (el JSX lee scores.reranker)', async () => {
        mocks.researchRequest.mockResolvedValue({
            query: 'test',
            items: [{ entity_type: 'ticker', entity_id: 3, title: 'Empresa sin scores', text: 'texto' }],
            page_info: { total_items: 1 },
        });
        render(await page());
        expect(screen.getByText('Empresa sin scores')).toBeInTheDocument();
        expect(offline()).not.toBeInTheDocument();
    });
});
