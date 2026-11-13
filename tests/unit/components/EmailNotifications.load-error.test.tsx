import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

const { read, save } = vi.hoisted(() => ({ read: vi.fn(), save: vi.fn() }));
vi.mock('@/lib/actions/email-alerts.actions', () => ({
    getEmailAlertStatus: read,
    setEmailAlertPreference: save,
}));
import EmailNotifications from '@/components/alerts/EmailNotifications';

afterEach(() => cleanup());

describe('EmailNotifications: fallo de lectura', () => {
    it('advierte del fallo en vez de dejar el placeholder invisible para siempre', async () => {
        read.mockRejectedValue(new Error('engine down'));
        render(<EmailNotifications />);
        const notice = await screen.findByTestId('email-load-error');
        expect(notice).toHaveTextContent('No se pudo cargar el estado de los avisos por correo');
        // El aviso sale una sola vez (no duplicado en el slot inferior).
        expect(screen.getAllByRole('alert')).toHaveLength(1);
        await waitFor(() => expect(screen.queryByTestId('email-loading-space')).not.toBeInTheDocument());
    });

    it('tras guardar, un refresco fallido conserva el estado y avisa (no desaparece la sección)', async () => {
        save.mockResolvedValue(undefined);
        read.mockResolvedValueOnce({
            smtp: true, email: 'qa@example.com',
            preferences: [{ event_type: 'earnings', enabled: false }],
        });
        render(<EmailNotifications />);
        expect(await screen.findByTestId('email-bound-address')).toBeInTheDocument();
        // El guardado funciona pero el refresco posterior falla.
        read.mockRejectedValueOnce(new Error('engine down'));
        fireEvent.click(screen.getByRole('checkbox'));
        await waitFor(() => expect(save).toHaveBeenCalled());
        // La sección sigue visible con el último estado conocido…
        expect(await screen.findByTestId('email-bound-address')).toBeInTheDocument();
        // …y el fallo se advierte, no se esconde.
        expect(await screen.findByRole('alert')).toHaveTextContent('No se pudo cargar el estado de los avisos por correo');
        expect(screen.queryByTestId('email-loading-space')).not.toBeInTheDocument();
    });
});
