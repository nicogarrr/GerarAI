import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import LlmUsagePanel, { LegCard } from '@/components/settings/LlmUsagePanel';
import type { LlmUsage, LlmUsageLeg } from '@/lib/actions/llm-settings.actions';

const goLeg: LlmUsageLeg = {
    id: 'opencode-go',
    label: 'OpenCode Go',
    provider: 'opencode-go-subscription',
    model: 'deepseek-v4.1-flash',
    active: true,
    state: 'limited',
    estimated: false,
    limited_until: '2026-11-02T00:00:00Z',
    quota: {
        rolling: { percent: 0 },
        weekly: { status: 'rate-limited', percent: 100, resetsAt: '2026-11-02T00:00:00Z' },
        monthly: { percent: 59, resetsAt: '2026-11-25T12:05:14Z' },
    },
    today: { date: '2026-11-01', calls: 3, tokens: 1200 },
};

const freeLeg: LlmUsageLeg = {
    id: 'opencode-free',
    label: 'OpenCode free',
    provider: 'opencode-free',
    model: 'deepseek-v4.1-flash-free',
    active: true,
    state: 'ok',
    estimated: true,
    limited_until: null,
    today: { date: '2026-11-01', calls: 1, tokens: 300 },
};

const geminiLeg: LlmUsageLeg = {
    id: 'gemini',
    label: 'Gemini (AI Studio)',
    provider: 'gemini',
    model: 'gemini-3.5-flash-lite',
    active: false,
    state: 'off',
    estimated: true,
    limited_until: null,
    today: { date: '2026-11-01', calls: 0, tokens: 0 },
    published_limits: { 'gemini-3.5-flash-lite': { rpm: 15, rpd: 500 } },
};

const usage: LlmUsage = {
    source: 'platform',
    generated_at: '2026-11-01T07:30:00Z',
    legs: [goLeg, freeLeg, geminiLeg],
};

describe('LlmUsagePanel', () => {
    it('muestra las tres patas con su estado y el origen del dato', () => {
        render(<LlmUsagePanel usage={usage} />);
        expect(screen.getByTestId('llm-usage-opencode-go')).toBeTruthy();
        expect(screen.getByTestId('llm-usage-opencode-free')).toBeTruthy();
        expect(screen.getByTestId('llm-usage-gemini')).toBeTruthy();
        // Go: cuota agotada con fecha de reset y dato real del proveedor.
        const go = screen.getByTestId('llm-usage-opencode-go');
        expect(go.textContent).toContain('Cuota agotada');
        expect(go.textContent).toContain('Dato del proveedor');
        expect(go.textContent).toContain('100%');
        // Free: operativo, marcado como estimado, contadores propios.
        const free = screen.getByTestId('llm-usage-opencode-free');
        expect(free.textContent).toContain('Operativo');
        expect(free.textContent).toContain('Estimado');
        expect(free.textContent).toContain('300');
        // Gemini desactivado: no muestra contadores.
        const gemini = screen.getByTestId('llm-usage-gemini');
        expect(gemini.textContent).toContain('Desactivado');
        expect(gemini.textContent).not.toContain('Hoy:');
    });

    it('con clave propia (tenant) explica que el consumo no se muestra', () => {
        render(<LlmUsagePanel usage={{ source: 'tenant', generated_at: usage.generated_at, legs: [], message: 'tenant_byok' }} />);
        expect(screen.getByText(/tu propia clave/)).toBeTruthy();
        expect(screen.queryByTestId('llm-usage-opencode-go')).toBeNull();
    });
});

describe('LegCard', () => {
    it('sin cuota del proveedor no inventa barras de porcentaje', () => {
        const sinQuota = { ...goLeg, quota: null, state: 'ok' as const, limited_until: null };
        const { container } = render(<LegCard leg={sinQuota} />);
        expect(container.textContent).toContain('Operativo');
        expect(container.textContent).not.toContain('Semanal');
    });
});
