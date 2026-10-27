import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { LlmSettings } from '@/lib/actions/llm-settings.actions';
const testConnection = vi.fn();
vi.mock('@/lib/actions/llm-settings.actions', () => ({
    testLlmConnection: (...args: unknown[]) => testConnection(...args),
    saveLlmSettings: vi.fn(),
}));
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
import LlmSettingsForm from '@/components/settings/LlmSettingsForm';
const initial: LlmSettings = {
    source: 'platform', status: 'platform', provider: 'opencode-go', model: 'model',
    base_url: 'https://example.com/v1', fallback_model: null, reasoning_effort: null,
    enabled: true, configured: true, api_key_configured: false, api_key_last4: null,
    key_version: null, billing_scope: 'platform', encryption_available: true,
    message: 'Usando el proveedor de GerarAI.',
    providers: [{ id: 'opencode-go', label: 'OpenCode Go', base_url: 'https://example.com/v1', default_model: 'model', requires_custom_url: false }],
};
beforeEach(() => { testConnection.mockReset(); });
describe('prueba de conexion de IA', () => {
    it('sin clave propia no llama al endpoint del tenant ni ofrece probar la plataforma', () => {
        render(<LlmSettingsForm initial={initial} />);
        expect(screen.getByRole('button', { name: 'Probar conexión' })).toBeDisabled();
        expect(screen.getByText(/Esta prueba comprueba tu clave API propia/)).toBeVisible();
        fireEvent.click(screen.getByRole('button', { name: 'Probar conexión' }));
        expect(testConnection).not.toHaveBeenCalled();
    });
    it('con clave nueva permite probar sin guardar', async () => {
        testConnection.mockResolvedValue({ ok: true, message: 'Conexión comprobada', status_code: 200 });
        render(<LlmSettingsForm initial={initial} />);
        fireEvent.change(screen.getByLabelText(/^Clave API/), { target: { value: 'synthetic-key' } });
        fireEvent.click(screen.getByRole('button', { name: 'Probar conexión' }));
        await waitFor(() => expect(testConnection).toHaveBeenCalledWith(expect.objectContaining({ api_key: 'synthetic-key' })));
    });
    it('una clave guardada del mismo proveedor se puede probar', () => {
        render(<LlmSettingsForm initial={{ ...initial, source: 'tenant', status: 'tenant', api_key_configured: true }} />);
        expect(screen.getByRole('button', { name: 'Probar conexión' })).toBeEnabled();
    });
    it('el fallo queda en pantalla con una salida util y no filtra el error del proveedor', async () => {
        testConnection.mockRejectedValue(new Error('https://provider.test?api_key=secret'));
        render(<LlmSettingsForm initial={{ ...initial, api_key_configured: true }} />);
        fireEvent.click(screen.getByRole('button', { name: 'Probar conexión' }));
        await waitFor(() => expect(screen.getByText(/No se pudo comprobar tu clave/)).toBeVisible());
        expect(screen.queryByText(/api_key=secret/)).not.toBeInTheDocument();
    });
});
