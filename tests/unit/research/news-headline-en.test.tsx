import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { NewsHeadline } from '@/components/research/NewsHeadline';
import { ExternalNewsHeadline } from '@/components/research/ExternalNewsHeadline';
import { LocaleProvider } from '@/lib/i18n/client';
import type { ResearchNewsEvent } from '@/lib/actions/research.actions';

const fetchMock = vi.fn(async () => new Response(JSON.stringify({ status: 'translated', text: 'Titular traducido' }), { status: 200 }));

beforeEach(() => {
  fetchMock.mockClear();
  vi.stubGlobal('fetch', fetchMock);
  vi.stubGlobal('IntersectionObserver', class {
    constructor(private cb: (entries: Array<{ isIntersecting: boolean }>) => void) {}
    observe() { this.cb([{ isIntersecting: true }]); }
    disconnect() {}
  });
});
afterEach(() => { vi.unstubAllGlobals(); });

const headline = 'Acme Wins Major NASA Contract For Lunar Satellites';
const event = {
  id: 7, title: headline, original_headline: headline, headline_from_source: true, url: null, ticker: 'ACME',
  headline_translation: { text: 'Acme gana un gran contrato de la NASA' }, related_tickers: [],
} as unknown as ResearchNewsEvent;

describe('titulares de noticias con el inglés elegido', () => {
  it('NewsHeadline no traduce al español ni muestra la traducción guardada', () => {
    const { container } = render(<LocaleProvider locale="en"><NewsHeadline event={event} /></LocaleProvider>);
    expect(screen.getByText(headline)).toBeTruthy();
    expect(container.textContent).not.toMatch(/Acme gana|Automatic translation/);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('ExternalNewsHeadline no pide traducción ni etiqueta el titular como «sin traducir»', () => {
    const { container } = render(<LocaleProvider locale="en"><ExternalNewsHeadline headline={headline} /></LocaleProvider>);
    expect(screen.getByText(headline)).toBeTruthy();
    expect(container.textContent).not.toMatch(/Titular original|not translated|Traducción/);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('en español se sigue mostrando la traducción guardada y su aviso', () => {
    const { container } = render(<NewsHeadline event={event} />);
    expect(container.textContent).toContain('Acme gana un gran contrato de la NASA');
    expect(container.textContent).toContain('Ver original');
  });
});
