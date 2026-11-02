import React from 'react';
import { readFileSync } from 'node:fs';
import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({ preparing: vi.fn(), locale: 'es' }));
vi.mock('@/lib/research/news-preparing', () => ({ getNewsPreparing: (t: string) => mocks.preparing(t) }));
vi.mock('next/headers', () => ({ cookies: async () => ({ get: () => (mocks.locale === 'en' ? { value: 'en' } : undefined) }) }));
vi.mock('@/components/research/DcaPreparingRefresh', () => ({ default: () => <span data-testid="refresh" /> }));
import { NewsPreparingNotice } from '@/components/research/NewsPreparingNotice';

describe('NewsPreparingNotice', () => {
  beforeEach(() => { mocks.preparing.mockReset(); mocks.locale = 'es'; });

  it('con la petición de noticias pendiente dice «preparando» y se recarga sola', async () => {
    mocks.preparing.mockResolvedValue(true);
    render(await NewsPreparingNotice({ ticker: 'ABCD', fallback: <p>Sin noticias recientes de esta empresa.</p> }));
    const el = screen.getByTestId('news-preparing');
    expect(el).toHaveTextContent('Preparando las noticias de esta empresa');
    expect(screen.getByTestId('refresh')).toBeInTheDocument();
    expect(screen.queryByText('Sin noticias recientes de esta empresa.')).not.toBeInTheDocument();
    expect(mocks.preparing).toHaveBeenCalledWith('ABCD');
  });

  it('en inglés dice «Preparing…»', async () => {
    mocks.locale = 'en';
    mocks.preparing.mockResolvedValue(true);
    render(await NewsPreparingNotice({ ticker: 'ABCD', fallback: null }));
    expect(screen.getByTestId('news-preparing')).toHaveTextContent("Preparing this company's news");
  });

  it('sin nada pendiente enseña el vacío de siempre y no refresca', async () => {
    mocks.preparing.mockResolvedValue(false);
    render(await NewsPreparingNotice({ ticker: 'ABCD', fallback: <p>Sin noticias recientes de esta empresa.</p> }));
    expect(screen.getByText('Sin noticias recientes de esta empresa.')).toBeInTheDocument();
    expect(screen.queryByTestId('news-preparing')).not.toBeInTheDocument();
    expect(screen.queryByTestId('refresh')).not.toBeInTheDocument();
  });

  it('la ficha lo usa en «Últimas noticias» y en la sección de noticias vacías', () => {
    const page = readFileSync('app/(root)/research/[ticker]/page.tsx', 'utf8');
    expect(page.match(/<NewsPreparingNotice /g)?.length).toBe(2);
  });
});
