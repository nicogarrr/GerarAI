import { fireEvent, render, screen, waitFor as rtlWaitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const m = vi.hoisted(() => ({
    saveTaxDeclarant: vi.fn(),
    savePortfolioBaseCurrency: vi.fn(),
    showErrorToast: vi.fn(),
    toastSuccess: vi.fn(),
}));
vi.mock('@/lib/actions/taxes.actions', () => ({ saveTaxDeclarant: m.saveTaxDeclarant }));
vi.mock('@/lib/actions/portfolio-settings.actions', () => ({ savePortfolioBaseCurrency: m.savePortfolioBaseCurrency }));
vi.mock('@/lib/toast', () => ({ showErrorToast: m.showErrorToast }));
vi.mock('sonner', () => ({ toast: { success: m.toastSuccess } }));

import BaseCurrencyForm from '@/components/settings/BaseCurrencyForm';
import TaxDeclarantForm from '@/components/settings/TaxDeclarantForm';
import type { TaxDeclarant } from '@/lib/actions/taxes.actions';

// Margen amplio: en CI cargada el primer render de Radix + jsdom tarda más de 1 s.
const waitFor = (fn: () => void) => rtlWaitFor(fn, { timeout: 5000 });

const ISIN = 'US0378331005';
const base: TaxDeclarant = {
    nif: '12345678Z',
    apellidos_nombre: 'GARCIA NICO',
    numero_declaracion: '',
    telefono: '',
    filed_720_before: null,
    custody: {},
    custody_entities: {},
    first_acquisition_dates: {},
    partidas: [ISIN, 'cash:USD'],
};

beforeEach(() => {
    vi.clearAllMocks();
});

describe('TaxDeclarantForm', () => {
    it('envía el 720 con nulls honestos: custodia vacía -> null, fecha solo para ISIN, sin entidad -> null', async () => {
        m.saveTaxDeclarant.mockImplementation(async (input) => ({ ...base, ...input, custody: {}, custody_entities: {}, first_acquisition_dates: {} }));
        render(<TaxDeclarantForm initial={base} />);
        fireEvent.change(screen.getByLabelText('País de custodia de ' + ISIN), { target: { value: '  ie ' } });
        fireEvent.change(screen.getByLabelText('Presentaste el 720 en ejercicios anteriores'), { target: { value: 'false' } });
        fireEvent.click(screen.getByRole('button', { name: 'Guardar' }));
        await waitFor(() => expect(m.saveTaxDeclarant).toHaveBeenCalledTimes(1));
        const payload = m.saveTaxDeclarant.mock.calls[0][0];
        expect(payload.filed_720_before).toBe(false);
        expect(payload.custody).toEqual({ [ISIN]: 'ie', 'cash:USD': null });
        expect(payload.custody_entities).toEqual({ [ISIN]: null, 'cash:USD': null });
        // La cuenta de efectivo no tiene fecha de primera adquisición: solo el ISIN.
        expect(payload.first_acquisition_dates).toEqual({ [ISIN]: null });
        expect(payload.nif).toBe('12345678Z');
        await waitFor(() => expect(m.toastSuccess).toHaveBeenCalledWith('Datos guardados'));
    });

    it('«Sin indicar» manda null (no false) y «Sí» manda true', async () => {
        m.saveTaxDeclarant.mockResolvedValue(base);
        render(<TaxDeclarantForm initial={{ ...base, filed_720_before: true }} />);
        expect(screen.getByLabelText('Presentaste el 720 en ejercicios anteriores')).toHaveValue('true');
        fireEvent.change(screen.getByLabelText('Presentaste el 720 en ejercicios anteriores'), { target: { value: '' } });
        fireEvent.click(screen.getByRole('button', { name: 'Guardar' }));
        await waitFor(() => expect(m.saveTaxDeclarant).toHaveBeenCalled());
        expect(m.saveTaxDeclarant.mock.calls[0][0].filed_720_before).toBeNull();
    });

    it('rellenar la entidad y la fecha del ISIN las envía; la respuesta normalizada del servidor sustituye al borrador', async () => {
        m.saveTaxDeclarant.mockResolvedValue({ ...base, nif: '12345678Z', custody: { [ISIN]: 'IE' } });
        render(<TaxDeclarantForm initial={base} />);
        fireEvent.change(screen.getAllByLabelText('Entidad depositaria')[0], { target: { value: 'Interactive Brokers Ireland' } });
        const dateInput = document.querySelector('input[type="date"]') as HTMLInputElement;
        fireEvent.change(dateInput, { target: { value: '2024-03-15' } });
        fireEvent.change(screen.getByLabelText('País de custodia de ' + ISIN), { target: { value: 'ie' } });
        fireEvent.click(screen.getByRole('button', { name: 'Guardar' }));
        await waitFor(() => expect(m.saveTaxDeclarant).toHaveBeenCalled());
        const payload = m.saveTaxDeclarant.mock.calls[0][0];
        expect(payload.custody_entities[ISIN]).toMatchObject({ name: 'Interactive Brokers Ireland', nif: '' });
        expect(payload.first_acquisition_dates).toEqual({ [ISIN]: '2024-03-15' });
        await waitFor(() => expect(screen.getByLabelText('País de custodia de ' + ISIN)).toHaveValue('IE'));
    });

    it('un error del servidor muestra el toast de error y deja el formulario usable', async () => {
        const boom = new Error('NIF no válido');
        m.saveTaxDeclarant.mockRejectedValue(boom);
        render(<TaxDeclarantForm initial={base} />);
        fireEvent.click(screen.getByRole('button', { name: 'Guardar' }));
        await waitFor(() => expect(m.showErrorToast).toHaveBeenCalledWith(boom));
        expect(m.toastSuccess).not.toHaveBeenCalled();
        expect(screen.getByRole('button', { name: 'Guardar' })).not.toBeDisabled();
    });

    it('sin partidas no pinta la sección de custodia y no manda fechas', async () => {
        m.saveTaxDeclarant.mockResolvedValue({ ...base, partidas: [] });
        render(<TaxDeclarantForm initial={{ ...base, partidas: [] }} />);
        expect(screen.queryByText(/Custodia por partida/)).toBeNull();
        fireEvent.click(screen.getByRole('button', { name: 'Guardar' }));
        await waitFor(() => expect(m.saveTaxDeclarant).toHaveBeenCalled());
        expect(m.saveTaxDeclarant.mock.calls[0][0]).toMatchObject({ custody: {}, custody_entities: {}, first_acquisition_dates: {} });
    });
});

describe('BaseCurrencyForm', () => {
    it('sin cambios no se puede guardar y explica de dónde salen los tipos', () => {
        render(<BaseCurrencyForm initial={{ base_currency: 'eur', fx_source: { source: 'BCE', latest_rate_date: '2026-10-27' } } as never} />);
        expect(screen.getByRole('button', { name: 'Guardar' })).toBeDisabled();
        expect(screen.getByText(/Tipos de cambio: BCE, último del/)).toBeInTheDocument();
        expect(screen.getByText(/IRPF y Modelo 720 van siempre en EUR/)).toBeInTheDocument();
    });

    it('sin tipos descargados lo dice en vez de inventar una fecha', () => {
        render(<BaseCurrencyForm initial={{ base_currency: null, fx_source: null } as never} />);
        expect(screen.getByText(/sin tipos descargados todavía/)).toBeInTheDocument();
        expect(screen.getByRole('combobox', { name: 'Divisa base' })).toHaveTextContent('EUR');
    });

    it('una divisa guardada fuera de la lista se sigue mostrando (no se pierde al abrir ajustes)', () => {
        render(<BaseCurrencyForm initial={{ base_currency: 'AUD', fx_source: null } as never} />);
        expect(screen.getByRole('combobox', { name: 'Divisa base' })).toHaveTextContent('AUD');
    });
});
