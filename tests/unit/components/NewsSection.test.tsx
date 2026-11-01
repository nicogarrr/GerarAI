import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

const getNews = vi.fn();
vi.mock('@/lib/actions/finnhub.actions', () => ({ getNews: (...args: unknown[]) => getNews(...args) }));
// NewsSection es un server component traducido con getT(): lib/i18n/server
// lee la cookie de locale vía next/headers; sin cookie el locale es «es».
vi.mock('next/headers', () => ({ cookies: async () => ({ get: () => undefined }) }));
vi.mock('@/components/calendar/CompanyLogo', () => ({
    CompanyLogo: ({ ticker, className }: { ticker: string; className?: string }) => (
        <span data-testid="company-logo" data-ticker={ticker} className={className} />
    ),
}));
// ExternalNewsHeadline observa intersección para traducir; jsdom no la tiene.
class IO {
    observe() {}
    unobserve() {}
    disconnect() {}
}
(globalThis as unknown as { IntersectionObserver: typeof IO }).IntersectionObserver = IO as never;
import NewsSection from '@/components/NewsSection';

const hace = (horas: number) => Math.floor(Date.now() / 1000) - horas * 3600;
const articulo = (over: Record<string, unknown>) => ({
    id: 1,
    headline: 'Apple beats earnings expectations as revenue rises',
    summary: 'resumen',
    source: 'Yahoo',
    url: 'https://example.com/a',
    datetime: hace(22),
    image: '',
    category: 'company',
    related: 'AAPL',
    ...over,
});

describe('NewsSection', () => {
    it('si las noticias fallan, «Reintentar» recarga Inicio en vez de cambiar de página', async () => {
        getNews.mockRejectedValue(new Error('proveedor caído'));
        render(await NewsSection({ symbols: ['AAPL'] }));
        expect(screen.getByText(/No se pudieron cargar las noticias/)).toBeInTheDocument();
        expect(screen.getByRole('link', { name: 'Reintentar' })).toHaveAttribute('href', '/inicio');
    });

    it('sin noticias: estado vacío y enlace al análisis de noticias', async () => {
        getNews.mockResolvedValue([]);
        render(await NewsSection({}));
        expect(screen.getByText('No hay noticias disponibles en este momento.')).toBeInTheDocument();
        expect(screen.getByRole('link', { name: 'Ver el análisis de noticias' })).toHaveAttribute('href', '/research/news');
        expect(screen.queryByRole('link', { name: 'Reintentar' })).toBeNull();
    });

    it('fila estilo feed (1-nov-2026): logo + nombre + antigüedad compacta, sin fuente pintada', async () => {
        getNews.mockResolvedValue([articulo({})]);
        render(await NewsSection({ symbols: ['AAPL'] }));
        // El bloque logo+nombre ES la insignia: enlaza a la ficha.
        expect(screen.getByTestId('company-logo')).toHaveAttribute('data-ticker', 'AAPL');
        // Logo y nombre enlazan a la ficha (el bloque entero es la insignia).
        screen.getAllByRole('link', { name: 'AAPL' }).forEach((l) => expect(l).toHaveAttribute('href', '/research/AAPL'));
        // Antigüedad compacta estilo referencia («22 h»), no la fecha larga.
        expect(screen.getByText('22 h')).toBeInTheDocument();
        // Sin etiqueta de fuente en la UI (regla de Nico).
        expect(screen.queryByText('Yahoo')).toBeNull();
    });

    it('mencionada (no en cartera) se etiqueta neutral y general no lleva logo de empresa', async () => {
        getNews.mockResolvedValue([
            articulo({ id: 1, related: 'NVDA', headline: 'NVIDIA stock rises on data center demand', url: 'https://example.com/nvda' }),
            articulo({ id: 2, related: '', headline: 'Wall Street cierra mixto', url: 'https://example.com/gen' }),
        ]);
        render(await NewsSection({ symbols: ['AAPL'] }));
        expect(screen.getByText('Mencionada · NVDA')).toBeInTheDocument();
        expect(screen.getByText('Mercado general')).toBeInTheDocument();
    });

    it('titulares duplicados se muestran una sola vez', async () => {
        getNews.mockResolvedValue([
            articulo({ id: 1, url: 'https://example.com/uno' }),
            articulo({ id: 2, url: 'https://example.com/dos', headline: 'Apple beats earnings expectations as revenue rises' }),
        ]);
        render(await NewsSection({ symbols: ['AAPL'] }));
        expect(screen.getAllByText(/Apple beats earnings expectations/)).toHaveLength(1);
    });
});
