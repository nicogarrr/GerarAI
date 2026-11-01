import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { MacroEventRow } from '@/components/calendar/MacroEventRow';
import type { MacroEvent } from '@/lib/actions/macro-calendar.actions';

const event: MacroEvent = {
    kind: 'jolts',
    date: '2026-11-03',
    start_date: '2026-11-03',
    time_et: '10:00',
    title: 'JOLTS: ofertas de empleo',
    detail: null,
    source: 'BLS',
    source_url: 'https://www.bls.gov/jlt/',
    label: 'OFICIAL',
};

describe('MacroEventRow', () => {
    it('no pinta el nombre de la fuente: el enlace del documento lleva icono y aria genérico', () => {
        render(<ul><MacroEventRow event={event} dateLabel="3 nov 2026" /></ul>);
        expect(screen.queryByText('BLS')).toBeNull();
        const link = screen.getByRole('link', { name: 'Abrir el documento oficial del evento (enlace externo)' });
        expect(link).toHaveAttribute('href', 'https://www.bls.gov/jlt/');
        expect(link).toHaveAttribute('target', '_blank');
        expect(link).toHaveAttribute('rel', expect.stringContaining('noopener'));
    });

    it('conserva el badge de calidad OFICIAL y la hora del evento', () => {
        render(<ul><MacroEventRow event={event} dateLabel="3 nov 2026" /></ul>);
        expect(screen.getByText('Oficial')).toBeInTheDocument();
        expect(screen.getByText('10:00 ET')).toBeInTheDocument();
        expect(screen.getByText('JOLTS: ofertas de empleo')).toBeInTheDocument();
    });
});
