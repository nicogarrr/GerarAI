import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { AnalystTargetsView } from '@/components/research/AnalystTargetsView';
import { LocaleProvider } from '@/lib/i18n/client';
import type { components } from '@/lib/research/openapi.generated';

type Data = components['schemas']['AnalystTargets'];

// Lo que manda el backend: texto en castellano + código estable.
const base = { symbol: 'TEST', source: 'x', source_url: null, fetched_at: 1793120400 } as const;
const withReference = {
  ...base, status: 'available', currency: 'USD', reference_price: 50,
  reference_price_source: 'fuente de mercado, precio al obtener los datos', reference_price_source_code: 'market_at_fetch',
  consensus: { median: 60, mean: 61, low: 40, high: 80 }, rows: [],
  note: 'Solo hay consenso agregado, sin detalle por firma.', note_code: 'consensus_only',
} as Data;
const etf = {
  ...base, status: 'empty', rows: [], consensus: null, instrument_type: 'ETF', note_code: 'not_equity',
  note: 'El valor TEST está identificado como un ETF, no como una acción, así que no hay precios objetivo de analistas que mostrar para una empresa con este ticker.',
} as Data;
const failed = { ...base, status: 'unavailable', rows: [], note: 'No se pudo consultar el consenso ahora; reintenta en unos minutos.', note_code: 'fetch_failed' } as Data;
const empty = { ...base, status: 'empty', rows: [], note: 'No hay precios objetivo por analista para este valor.', note_code: 'no_targets' } as Data;

const SPANISH = /fuente de mercado|precio al obtener|Solo hay consenso|identificado como|No se pudo consultar|No hay precios objetivo/;

describe('analistas: textos del backend traducidos por código', () => {
  it('en inglés: fuente del precio de referencia y nota de consenso en inglés', () => {
    render(<LocaleProvider locale="en"><AnalystTargetsView data={withReference} currency="USD" /></LocaleProvider>);
    expect(screen.getByText(/market source, price when the data was fetched/)).toBeInTheDocument();
    expect(screen.getByText('Aggregate consensus only, no per-firm detail.')).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(SPANISH);
  });

  it('en inglés: ETF, fallo de consulta y sin objetivos', () => {
    const { unmount } = render(<LocaleProvider locale="en"><AnalystTargetsView data={etf} /></LocaleProvider>);
    expect(screen.getByText('TEST is identified as an ETF, not as a stock, so there are no analyst price targets to show for a company with this ticker.')).toBeInTheDocument();
    unmount();
    const second = render(<LocaleProvider locale="en"><AnalystTargetsView data={failed} /></LocaleProvider>);
    expect(screen.getByText('The consensus could not be retrieved right now; retry in a few minutes.')).toBeInTheDocument();
    second.unmount();
    render(<LocaleProvider locale="en"><AnalystTargetsView data={empty} /></LocaleProvider>);
    expect(screen.getByText('No analyst price targets for this stock.')).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(SPANISH);
  });

  it('en castellano: los mismos textos que mandaba el backend', () => {
    const { unmount } = render(<LocaleProvider locale="es"><AnalystTargetsView data={withReference} currency="USD" /></LocaleProvider>);
    expect(screen.getByText(/fuente de mercado, precio al obtener los datos/)).toBeInTheDocument();
    expect(screen.getByText(withReference.note as string)).toBeInTheDocument();
    unmount();
    render(<LocaleProvider locale="es"><AnalystTargetsView data={etf} /></LocaleProvider>);
    expect(screen.getByText(etf.note as string)).toBeInTheDocument();
  });

  it('sin código (backend antiguo) se conserva el texto recibido', () => {
    const legacy = { ...empty, note_code: null, note: 'nota antigua' } as Data;
    render(<LocaleProvider locale="en"><AnalystTargetsView data={legacy} /></LocaleProvider>);
    expect(screen.getByText('nota antigua')).toBeInTheDocument();
  });
});
