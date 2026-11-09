import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { AnalystTargetsView } from '@/components/research/AnalystTargetsView';
import { LocaleProvider } from '@/lib/i18n/client';
import type { components } from '@/lib/research/openapi.generated';

type Data = components['schemas']['AnalystTargets'];

// Fila de prensa tal como la manda el backend con press=1: medio y enlace por
// fila, fecha real del artículo; la nota viaja con código estable.
const data = {
    symbol: 'ASTS', status: 'available', currency: 'USD', fetched_at: 1794297600,
    source: 'Yahoo Finance (no oficial), agregado de analistas', source_url: null,
    reference_price: 50,
    consensus: { median: 70, mean: 72, low: 54, high: 108 },
    rows: [
        { firm: 'Cantor Fitzgerald', date: '2026-11-09', rating: 'Overweight', price_target: 90, prior_target: null, upside_percent: 80, source: 'StreetInsider', source_url: 'https://www.streetinsider.com/x' },
        { firm: 'TD Cowen', date: '2026-10-01', rating: 'Buy', price_target: 80, prior_target: 70, upside_percent: 60, source: 'Yahoo Finance (no oficial), agregado de analistas', source_url: null },
    ],
    note: 'Incluye notas de prensa recientes con su medio, fecha y enlace.', note_code: 'with_press',
} as Data;

describe('panel de analistas con complemento de prensa', () => {
    it('la fila de prensa enlaza su medio; la de Yahoo no lleva enlace por fila', () => {
        render(<LocaleProvider locale="es"><AnalystTargetsView data={data} currency="USD" /></LocaleProvider>);
        const links = screen.getAllByRole('link', { name: 'StreetInsider' });
        expect(links.length).toBeGreaterThan(0);
        expect(links[0]).toHaveAttribute('href', 'https://www.streetinsider.com/x');
        expect(links[0]).toHaveAttribute('target', '_blank');
        expect(screen.queryByRole('link', { name: /Yahoo Finance \(no oficial\)/ })).not.toBeInTheDocument();
    });

    it('la nota se traduce por código: castellano e inglés', () => {
        const { unmount } = render(<LocaleProvider locale="es"><AnalystTargetsView data={data} currency="USD" /></LocaleProvider>);
        expect(screen.getByText('Incluye notas de prensa recientes con su medio, fecha y enlace.')).toBeInTheDocument();
        unmount();
        render(<LocaleProvider locale="en"><AnalystTargetsView data={data} currency="USD" /></LocaleProvider>);
        expect(screen.getByText('Includes recent press notes with their outlet, date and link.')).toBeInTheDocument();
        expect(document.body.textContent).not.toMatch(/Incluye notas de prensa/);
    });
});
