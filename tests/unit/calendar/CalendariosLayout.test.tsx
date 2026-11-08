import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

vi.mock('next/navigation', () => ({ usePathname: () => '/calendar' }));

import { CalendariosLayout } from '@/components/calendar/CalendariosLayout';

// Layout compartido de /calendar, /macro-calendar y /corporate-actions: las
// tres rutas montan las mismas pestañas sin copiar JSX.

describe('CalendariosLayout', () => {
    it('monta las pestañas de calendario encima del contenido de la ruta', () => {
        render(
            <CalendariosLayout>
                <p>contenido de la ruta</p>
            </CalendariosLayout>,
        );
        expect(screen.getByRole('link', { name: 'Catalizadores' })).toBeInTheDocument();
        expect(screen.getByRole('link', { name: 'Macro y 8-K' })).toBeInTheDocument();
        expect(screen.getByText('contenido de la ruta')).toBeInTheDocument();
    });
});
