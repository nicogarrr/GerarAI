import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { LlmSettings } from '@/lib/actions/llm-settings.actions';
vi.mock('@/lib/actions/llm-settings.actions', () => ({
    testLlmConnection: vi.fn(),
    saveLlmSettings: vi.fn(),
}));
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
import LlmSettingsForm from '@/components/settings/LlmSettingsForm';

const base: LlmSettings = {
    source: 'platform', status: 'platform', provider: 'opencode-go', model: 'model',
    base_url: 'https://example.com/v1', fallback_model: null, reasoning_effort: null,
    enabled: true, configured: true, api_key_configured: false, api_key_last4: null,
    key_version: null, billing_scope: 'platform', encryption_available: true,
    message: 'Usando el proveedor de GerarAI.',
    providers: [{ id: 'opencode-go', label: 'OpenCode Go', base_url: 'https://example.com/v1', default_model: 'model', requires_custom_url: false }],
};

// Orden de Nico (31-oct): un usuario nuevo debe ver claro que la IA funciona
// con SU clave y SU modelo, y que GerarAI no asume ese coste.
describe('aviso «tu IA, tu clave»', () => {
    it('sin clave propia explica que la clave y el coste son del usuario', () => {
        render(<LlmSettingsForm initial={base} />);
        expect(screen.getByText(/Tu IA, tu clave/)).toBeVisible();
        expect(screen.getByText(/GerarAI no asume tu consumo/)).toBeVisible();
    });
    it('con clave propia guardada el aviso desaparece', () => {
        render(<LlmSettingsForm initial={{ ...base, source: 'tenant', status: 'tenant', api_key_configured: true, billing_scope: 'tenant' }} />);
        expect(screen.queryByText(/Tu IA, tu clave/)).not.toBeInTheDocument();
    });
});
