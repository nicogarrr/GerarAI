/**
 * Textos del formulario de ajustes de IA: español correcto, con tildes.
 * Regresión: «Configuracion desactivada» y «HTTPS publico» sin tilde.
 */
import { readFileSync } from 'node:fs';
import { describe, expect, it, vi } from 'vitest';

vi.mock('@/lib/actions/llm-settings.actions', () => ({}));

import { statusLabel } from '@/components/settings/LlmSettingsForm';
import type { LlmSettings } from '@/lib/actions/llm-settings.actions';

const base: LlmSettings = {
    encryption_available: true,
    source: 'tenant',
    status: 'disabled',
    provider: 'opencode-go',
    base_url: null,
    model: null,
    fallback_model: null,
    reasoning_effort: null,
    enabled: false,
    api_key_configured: false,
    api_key_last4: null,
    billing_scope: 'tenant',
    message: '',
    providers: [],
} as unknown as LlmSettings;

describe('statusLabel', () => {
    it('estado disabled: «Configuración desactivada» con tilde', () => {
        expect(statusLabel({ ...base, status: 'disabled' })).toBe('Configuración desactivada');
    });
    it('resto de ramas intactas', () => {
        expect(statusLabel({ ...base, encryption_available: false })).toBe('Cifrado no disponible');
        expect(statusLabel({ ...base, source: 'platform' })).toBe('Usando proveedor de GerarAI');
        expect(statusLabel({ ...base, status: 'missing_key' })).toBe('Falta tu clave API');
        expect(statusLabel({ ...base, status: 'tenant', api_key_last4: 'abcd' })).toBe('Configurado con tu clave (...abcd)');
    });
});

describe('textos estáticos del formulario', () => {
    it('«HTTPS público» lleva tilde en etiqueta y ayuda', () => {
        const source = readFileSync('components/settings/LlmSettingsForm.tsx', 'utf8');
        expect(source).not.toContain('publico');
        expect(source).not.toContain('Configuracion');
    });
});
