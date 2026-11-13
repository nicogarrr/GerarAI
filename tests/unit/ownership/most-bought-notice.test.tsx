import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi, beforeEach } from 'vitest';

// Aviso de calidad del importe incompleto (#5484): la acción sirve el texto
// traducido y la vista lo muestra sin etiquetas de fuente.
const mocks = vi.hoisted(() => ({ locale: 'es', request: vi.fn(), user: vi.fn() }));
vi.mock('next/headers', () => ({ cookies: async () => ({ get: () => ({ value: mocks.locale }) }) }));
vi.mock('@/lib/auth/require-user', () => ({ requireAuthenticatedUser: mocks.user }));
vi.mock('@/lib/research/client', () => ({ researchRequest: mocks.request }));
vi.mock('@/app/(root)/inversores/_components/SyncPortfoliosButton', () => ({ SyncPortfoliosButton: () => null }));

const BACKEND_NOTICE = 'Importe incompleto: faltan valores declarados de algunas posiciones compradoras; el subtotal conocido no es el total.';
const EN_NOTICE = 'Incomplete amount: declared values are missing for some buying positions; the known subtotal is not the total.';

const item = (over: Record<string, unknown> = {}) => ({
    name_of_issuer: 'Fixture Issuer Corp', cusip: '123456789', buyers_count: 3, new_count: 1, sellers_count: 0,
    value_usd: null, known_value_usd: 1250000, missing_value_count: 2, notice: BACKEND_NOTICE,
    buyers: [{ slug: 'fixture-fund', name: 'Fixture Fund', change: 'new' as const }],
    ...over,
});
const payload = (items: unknown[]) => ({
    status: 'ok', managers_compared: 3, managers_without_history: 0, report_dates: ['2026-09-30'], items, limitations: [],
});

import { getMostBought } from '@/lib/actions/investors.actions';
import { MostBought } from '@/app/(root)/ownership/_components/MostBought';

beforeEach(() => { mocks.locale = 'es'; mocks.request.mockReset(); });

describe('getMostBought: aviso de importe incompleto traducido', () => {
    it('traduce el texto fijo del motor y deja pasar uno desconocido', async () => {
        mocks.request.mockResolvedValue(payload([item(), item({ cusip: '987654321', notice: 'aviso nuevo del motor' })]));
        mocks.locale = 'en';
        const data = await getMostBought();
        expect(data.items[0].notice).toBe(EN_NOTICE);
        expect(data.items[1].notice).toBe('aviso nuevo del motor');
    });

    it('sin avisos no toca la respuesta', async () => {
        mocks.request.mockResolvedValue(payload([item({ notice: null, value_usd: 2000000 })]));
        const data = await getMostBought();
        expect(data.items[0].notice).toBeNull();
        expect(data.items[0].value_usd).toBe(2000000);
    });
});

describe('MostBought: aviso de calidad en la vista', () => {
    it('en castellano muestra el aviso y N/D en el importe', async () => {
        mocks.request.mockResolvedValue(payload([item()]));
        render(await MostBought({}));
        expect(screen.getByRole('status')).toHaveTextContent(BACKEND_NOTICE);
        expect(screen.getByText(/N\/D/)).toBeTruthy();
    });

    it('en inglés muestra el aviso traducido', async () => {
        mocks.request.mockResolvedValue(payload([item()]));
        mocks.locale = 'en';
        render(await MostBought({}));
        expect(screen.getByRole('status')).toHaveTextContent(EN_NOTICE);
    });

    it('sin aviso no sale el bloque', async () => {
        mocks.request.mockResolvedValue(payload([item({ notice: null, value_usd: 2000000 })]));
        render(await MostBought({}));
        expect(screen.queryByRole('status')).toBeNull();
    });
});
