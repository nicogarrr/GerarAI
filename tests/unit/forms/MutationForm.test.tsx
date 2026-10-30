import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const m = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn(), showError: vi.fn() }));
vi.mock('sonner', () => ({ toast: { success: m.success, error: m.error } }));
vi.mock('@/lib/toast', () => ({ showErrorToast: m.showError }));

import { MutationForm } from '@/components/forms/MutationForm';

function renderForm(action: (formData: FormData) => Promise<unknown>) {
    render(
        <MutationForm action={action} successMessage="Documento ingerido" data-testid="form">
            <input name="titulo" defaultValue="x" />
            <button type="submit">Enviar</button>
        </MutationForm>,
    );
}

beforeEach(() => vi.clearAllMocks());

describe('MutationForm con resultado tipado (carril B)', () => {
    it('un { ok: false } de validacion es error inline, NUNCA exito', async () => {
        // Antes del contrato MutationForm celebraba cualquier resolucion:
        // el rechazo «Elige un documento» salia como «Documento ingerido».
        renderForm(async () => ({ ok: false, cause: 'validation', message: 'Elige un documento para subir.' }));
        fireEvent.click(screen.getByRole('button', { name: 'Enviar' }));
        await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('Elige un documento para subir.'));
        expect(m.success).not.toHaveBeenCalled();
        // La validacion no ofrece reintento: el toast accionable es solo
        // para offline/stale/duplicate.
        expect(m.showError).not.toHaveBeenCalled();
    });

    it('un { ok: true } sigue siendo exito con el successMessage', async () => {
        renderForm(async () => ({ ok: true }));
        fireEvent.click(screen.getByRole('button', { name: 'Enviar' }));
        await waitFor(() => expect(m.success).toHaveBeenCalledWith('Documento ingerido'));
        expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    });

    it('una accion que resuelve void sigue siendo exito (compatibilidad)', async () => {
        renderForm(async () => undefined);
        fireEvent.click(screen.getByRole('button', { name: 'Enviar' }));
        await waitFor(() => expect(m.success).toHaveBeenCalledWith('Documento ingerido'));
    });

    it('un throw sigue yendo al error inline clasificado', async () => {
        renderForm(async () => { throw new Error('fetch failed'); });
        fireEvent.click(screen.getByRole('button', { name: 'Enviar' }));
        await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent(/motor de análisis no responde/i));
        expect(m.success).not.toHaveBeenCalled();
        // offline SI tiene toast accionable con reintento.
        expect(m.showError).toHaveBeenCalledOnce();
    });
});
