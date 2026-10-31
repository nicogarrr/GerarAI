import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
const save = vi.hoisted(() => vi.fn());
const toastSuccess = vi.hoisted(() => vi.fn());
const showError = vi.hoisted(() => vi.fn());
vi.mock('@/lib/actions/dca-settings.actions', () => ({ saveDcaAlertSettings: save }));
vi.mock('sonner', () => ({ toast: { success: toastSuccess } }));
vi.mock('@/lib/toast', () => ({ showErrorToast: showError }));
import DcaAlertsForm from '@/components/settings/DcaAlertsForm';
const initial = { configured: false, up_min_level: 3, down_max_level: 1, legacy_override_count: 2, legacy_min_level: 2, alerts_enabled: true, trims_enabled: false };

describe('global DCA directional settings', () => {
    it('shows effective defaults, explains thresholds and legacy overrides', () => {
        render(<DcaAlertsForm initial={initial} />);
        expect(screen.getByLabelText('Al subir, avisar desde')).toHaveValue('3');
        expect(screen.getByLabelText('Al bajar, avisar hasta')).toHaveValue('1');
        expect(screen.getByText(/No cambia el veredicto ni realiza órdenes/)).toBeInTheDocument();
        expect(screen.getByText(/Tienes 2 ajustes antiguos por empresa: se conservan, pero ya no se aplican/)).toBeInTheDocument();
    });
    it('saves independent thresholds, reports success only after persistence', async () => {
        save.mockResolvedValue({ ...initial, configured: true, up_min_level: 4, down_max_level: 0 });
        render(<DcaAlertsForm initial={initial} />);
        fireEvent.change(screen.getByLabelText('Al subir, avisar desde'), { target: { value: '4' } });
        fireEvent.change(screen.getByLabelText('Al bajar, avisar hasta'), { target: { value: '0' } });
        fireEvent.click(screen.getByRole('button', { name: 'Guardar avisos DCA' }));
        await waitFor(() => expect(save).toHaveBeenCalledWith(4, 0));
        // Exito via toast, como el resto de formularios de Ajustes.
        await waitFor(() => expect(toastSuccess).toHaveBeenCalledWith('Avisos DCA guardados para todas tus empresas. Los ajustes antiguos por empresa se conservan sin efecto.'));
        expect(screen.getByText(/Valores activos: subida desde 4X; bajada desactivada/)).toBeInTheDocument();
    });
    it('does not claim success when backend fails and keeps saved values', async () => {
        save.mockRejectedValue(new Error('Fallo'));
        render(<DcaAlertsForm initial={{ ...initial, alerts_enabled: false }} />);
        fireEvent.change(screen.getByLabelText('Al subir, avisar desde'), { target: { value: '4' } });
        fireEvent.click(screen.getByRole('button', { name: 'Guardar avisos DCA' }));
        await waitFor(() => expect(showError).toHaveBeenCalled());
        expect(toastSuccess).not.toHaveBeenCalled();
        expect(screen.getByText(/Valores activos: subida desde 3X/)).toBeInTheDocument();
        expect(screen.getByRole('status')).toHaveTextContent('desactivados en el servidor');
    });
    it('without legacy overrides it does not talk about «(0)» of them', async () => {
        save.mockResolvedValue({ ...initial, legacy_override_count: 0, configured: true });
        render(<DcaAlertsForm initial={{ ...initial, legacy_override_count: 0 }} />);
        expect(screen.queryByText(/ajustes? antiguos? por empresa/)).not.toBeInTheDocument();
        fireEvent.click(screen.getByRole('button', { name: 'Guardar avisos DCA' }));
        await waitFor(() => expect(toastSuccess).toHaveBeenCalledWith('Avisos DCA guardados para todas tus empresas.'));
    });
});
