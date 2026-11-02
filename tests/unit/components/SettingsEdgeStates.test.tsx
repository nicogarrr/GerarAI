import { render } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const h = vi.hoisted(() => ({ locale: 'es' }));
vi.mock('next/headers', () => ({ cookies: async () => ({ get: () => ({ value: h.locale }) }) }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ refresh: vi.fn(), push: vi.fn() }), usePathname: () => '/settings' }));
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() } }));
vi.mock('@/lib/research/client', () => ({ researchRequest: vi.fn(), jsonBody: JSON.stringify }));

import SettingsContent from '@/components/settings/SettingsContent';
import { providerLabel, statusMessage } from '@/components/settings/LlmSettingsForm';
import { createTranslator } from '@/lib/i18n/translate';
import { LocaleProvider } from '@/lib/i18n/client';

const FRESH = {"/api/settings/dca": {"up_min_level": 3, "down_max_level": 1, "configured": false, "legacy_override_count": 0, "legacy_min_level": 2, "alerts_enabled": true, "trims_enabled": false}, "/api/settings/ibkr": {"last_sync": null, "connected": false, "account_id": null, "query_id": null, "status": "not_connected", "message": "Conecta una cuenta IBKR mediante Flex, solo lectura.", "last_attempt_at": null, "last_success_at": null, "statement_date": null, "complete_query": false}, "/api/settings/llm": {"source": "platform", "status": "disabled", "provider": "opencode-go", "base_url": null, "model": null, "fallback_model": null, "reasoning_effort": "high", "enabled": false, "configured": false, "api_key_configured": false, "api_key_last4": null, "key_version": null, "billing_scope": "platform", "encryption_available": false, "message": "El proveedor de GerarAI no esta configurado.", "error": null, "providers": [{"id": "opencode-go", "label": "OpenCode Go", "base_url": "https://opencode.ai/zen/go/v1", "default_model": "deepseek-v4.1-flash", "requires_custom_url": false}, {"id": "openrouter", "label": "OpenRouter", "base_url": "https://openrouter.ai/api/v1", "default_model": "google/gemma-4-31b-it:free", "requires_custom_url": false}, {"id": "gemini", "label": "Google Gemini", "base_url": "https://generativelanguage.googleapis.com/v1beta/openai", "default_model": "gemini-3.5-flash-lite", "requires_custom_url": false}, {"id": "openai", "label": "OpenAI", "base_url": "https://api.openai.com/v1", "default_model": "gpt-4.1-mini", "requires_custom_url": false}, {"id": "groq", "label": "Groq", "base_url": "https://api.groq.com/openai/v1", "default_model": "openai/gpt-oss-120b", "requires_custom_url": false}, {"id": "custom", "label": "Otro compatible con OpenAI", "base_url": "", "default_model": "", "requires_custom_url": true}]}, "/api/settings/llm/usage": {"source": "platform", "generated_at": "2026-11-02T00:49:30.517085Z", "legs": [{"id": "opencode-go", "label": "OpenCode Go", "provider": "opencode-go-subscription", "model": "deepseek-v4.1-flash", "active": false, "state": "off", "estimated": false, "limited_until": null, "quota": null, "today": {"date": "2026-11-02", "calls": 0, "tokens": 0}, "published_limits": null}, {"id": "opencode-free", "label": "OpenCode free", "provider": "opencode-free", "model": "deepseek-v4.1-flash-free", "active": false, "state": "off", "estimated": true, "limited_until": null, "quota": null, "today": {"date": "2026-11-02", "calls": 0, "tokens": 0}, "published_limits": null}, {"id": "gemini", "label": "Gemini (AI Studio)", "provider": "gemini", "model": "gemini-3.5-flash-lite", "active": false, "state": "off", "estimated": true, "limited_until": null, "quota": null, "today": {"date": "2026-11-02", "calls": 0, "tokens": 0}, "published_limits": {"gemini-3.5-flash-lite": {"rpm": 15, "rpd": 500, "tpm": 250000}, "gemini-3.8-flash": {"rpm": 5, "rpd": 20}}}], "message": null}, "/api/portfolio/configuration": {"id": null, "name": "Main", "base_currency": "EUR", "is_default": true, "tax_currency": "EUR", "fx_source": {"source": null, "latest_rate_date": null, "base_currency": "EUR"}}, "/api/taxes/declarant": {"nif": "", "apellidos_nombre": "", "numero_declaracion": "", "telefono": "", "filed_720_before": null, "custody": {}, "custody_entities": {}, "first_acquisition_dates": {}, "partidas": []}};

async function show(locale: 'es' | 'en') {
    h.locale = locale;
    const ui = await SettingsContent({
        dca: FRESH['/api/settings/dca'], declarant: FRESH['/api/taxes/declarant'], llm: FRESH['/api/settings/llm'],
        llmUsage: FRESH['/api/settings/llm/usage'], currency: FRESH['/api/portfolio/configuration'], ibkr: FRESH['/api/settings/ibkr'],
    } as never);
    const view = render(<LocaleProvider locale={locale}>{ui}</LocaleProvider>);
    return (view.container.textContent ?? '').replace(/\s+/g, ' ');
}

describe('Ajustes de una cuenta nueva (datos reales del backend)', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        window.matchMedia ??= ((query: string) => ({
            matches: false, media: query, onchange: null, addListener: vi.fn(), removeListener: vi.fn(),
            addEventListener: vi.fn(), removeEventListener: vi.fn(), dispatchEvent: vi.fn(),
        })) as never;
    });

    it('en castellano: todas las secciones, sin valores rotos', async () => {
        const text = await show('es');
        expect(text).not.toMatch(/NaN|undefined|Infinity|\[object/);
        expect(text).toContain('El proveedor de GerarAI no está configurado.');
        expect(text).toContain('Otro compatible con OpenAI');
        expect(text).toContain('EUR · Euro');
    });

    it('en inglés: el estado de la IA y el proveedor «otro» ya no salen en castellano', async () => {
        const text = await show('en');
        expect(text).not.toMatch(/NaN|undefined|Infinity|\[object/);
        expect(text).toContain("GerarAI's provider isn't set up.");
        expect(text).toContain('Other OpenAI-compatible');
        expect(text).not.toMatch(/no esta configurado|Otro compatible|Conecta una cuenta/);
    });

    it('cada estado de la IA propia tiene su frase en inglés; uno desconocido usa la del servidor', () => {
        const en = createTranslator('en');
        const llm = FRESH['/api/settings/llm'];
        const msg = (source: string, status: string, message = 'servidor') => statusMessage({ ...llm, source, status, message } as never, en);
        expect(msg('platform', 'platform')).toBe("You're using GerarAI's provider.");
        expect(msg('tenant', 'tenant')).toBe('Set up with your key. Usage is billed by your provider.');
        expect(msg('tenant', 'missing_key')).toBe('The provider key is missing: AI is turned off.');
        expect(msg('tenant', 'disabled')).toBe('Your own AI is turned off or its settings are not valid.');
        expect(msg('tenant', 'raro')).toBe('servidor');
        expect(providerLabel({ id: 'openai', label: 'OpenAI' }, en)).toBe('OpenAI');
    });
});
