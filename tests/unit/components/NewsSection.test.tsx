import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

const getNews = vi.fn();
vi.mock('@/lib/actions/finnhub.actions', () => ({ getNews: (...args: unknown[]) => getNews(...args) }));
import NewsSection from '@/components/NewsSection';

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
});
