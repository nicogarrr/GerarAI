import { render, screen } from '@testing-library/react';
import { beforeAll, describe, expect, it } from 'vitest';

import { AstOrbitPanel } from '@/components/research/AstOrbitPanel';

const object = {
    norad_cat_id: 61047, object_name: 'BLUEBIRD 1', sma_km: 6898.24, epoch: '2026-10-30T12:00:00Z',
    signal: { delta_sma_km: 1.25, hours: 48, status: 'subida' },
    history: [{ epoch: '2026-10-28T12:00:00Z', sma_km: 6897 }, { epoch: '2026-10-30T12:00:00Z', sma_km: 6898.24 }],
};
const data = { status: 'disponible', objects: [object], fetched_at: '2026-10-31T10:00:00Z', cadence_hours: 2, usage_note: null, supgp: { status: 'sin_datos', objects: [], fetched_at: null } } as never;

describe('órbitas AST en inglés', () => {
    beforeAll(() => {
        Object.defineProperty(window, 'matchMedia', { configurable: true, value: () => ({ matches: false, addEventListener: () => undefined, removeEventListener: () => undefined }) });
    });

    it('sale en inglés con English picked', () => {
        render(<AstOrbitPanel analysis={null} data={data} locale="en" />);
        expect(screen.getByText('AST constellation orbits')).toBeInTheDocument();
        expect(screen.getByText('Semi-major axis: 6,898.2 km')).toBeInTheDocument();
        expect(screen.getByText('Trend: +1.25 km in 48 h')).toBeInTheDocument();
        expect(screen.getByText('Reading not available right now. Reload in a few seconds.')).toBeInTheDocument();
        expect(screen.getByText('No current supplemental data. SupGP may be unavailable even when GP is available.')).toBeInTheDocument();
        expect(screen.getByText('2 saved epochs. The chart doesn\'t confirm a deployment.')).toBeInTheDocument();
        expect(screen.getByRole('link', { name: 'See the method and the limits of the calculation' })).toBeInTheDocument();
        expect(document.body.textContent).not.toMatch(/Semieje|Tendencia|épocas|Sin datos/);
    });

    it('en español se ve igual que antes', () => {
        render(<AstOrbitPanel analysis={null} data={data} />);
        expect(screen.getByText('Órbitas de la constelación AST')).toBeInTheDocument();
        expect(screen.getByText(/^Semieje mayor: 6\.?898,2 km$/)).toBeInTheDocument();
        expect(screen.getByText('Tendencia: +1,25 km en 48 h')).toBeInTheDocument();
        expect(screen.getByText('2 épocas guardadas. La gráfica no confirma despliegue.')).toBeInTheDocument();
    });
});
