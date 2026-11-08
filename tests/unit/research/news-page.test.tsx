// Server component traducido con getT(): lib/i18n/server lee la cookie de
// locale vía next/headers; sin cookie el locale es «es».
vi.mock('next/headers', () => ({ cookies: async () => ({ get: () => undefined }) }));
import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

/**
 * /research/news (página): parsing defensivo de searchParams — carril solo de
 * la lista conocida, ticker normalizado a mayúsculas sin espacios, página
 * acotada a 1..1000 — y el enlace de vuelta a la ficha cuando hay ticker.
 */
let sectionProps: Record<string, unknown> = {};
vi.mock('@/app/(root)/research/news/NewsFeedSection', () => ({
    NewsFeedSection: (props: Record<string, unknown>) => {
        sectionProps = props;
        return null;
    },
}));
vi.mock('@/lib/actions/ticker-context.actions', () => ({
    getTickerContext: () => Promise.resolve({ portfolioTickers: [], watchlistTickers: [] }),
}));
vi.mock('@/lib/actions/research.actions', () => ({
    analyzeManualNews: vi.fn(),
    ingestResearchNewsFeed: vi.fn(),
}));

import ResearchNewsPage from '@/app/(root)/research/news/page';

const show = async (query: Record<string, string>) =>
    render(await ResearchNewsPage({ searchParams: Promise.resolve(query) }));

beforeEach(() => {
    sectionProps = {};
});

describe('/research/news: parsing de searchParams', () => {
    it('carril fuera de la lista conocida cae a null (todas)', async () => {
        await show({ lane: 'crypto' });
        expect(sectionProps.lane).toBeNull();
    });

    it.each(['macro', 'empresa', 'para-ti', 'gobierno'] as const)('carril %s pasa tal cual', async (lane) => {
        await show({ lane });
        expect(sectionProps.lane).toBe(lane);
    });

    it('ticker: recorta espacios y pasa a mayúsculas; vacío cuenta como ausente', async () => {
        await show({ ticker: ' aapl ' });
        expect(sectionProps.ticker).toBe('AAPL');
        await show({ ticker: '   ' });
        expect(sectionProps.ticker).toBeNull();
    });

    it('página: no numérica o menor que 1 cae a 1; por encima de 1000 se acota', async () => {
        await show({ pagina: 'abc' });
        expect(sectionProps.page).toBe(1);
        await show({ pagina: '0' });
        expect(sectionProps.page).toBe(1);
        await show({ pagina: '-5' });
        expect(sectionProps.page).toBe(1);
        await show({ pagina: '10000' });
        expect(sectionProps.page).toBe(1000);
        await show({ pagina: '2' });
        expect(sectionProps.page).toBe(2);
    });

    it('con ticker vuelve a su ficha; sin ticker vuelve a /research', async () => {
        await show({ ticker: 'brk.b' });
        expect(screen.getByRole('link', { name: 'Volver a BRK.B' })).toHaveAttribute('href', '/research/BRK.B');
        await show({});
        expect(screen.getByRole('link', { name: 'Research' })).toHaveAttribute('href', '/research');
    });
});
