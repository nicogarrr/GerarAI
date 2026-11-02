import { readFileSync } from 'node:fs';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render } from '@testing-library/react';
import { ChangesFeed } from '@/components/research/ChangesFeed';
import { LocaleProvider } from '@/lib/i18n/client';

beforeEach(() => {
  vi.stubGlobal('matchMedia', () => ({ matches: false, addEventListener() {}, removeEventListener() {} }));
});

// Severidades REALES de las alertas de revisión (review_alert_service._severity, leídas del .py).
const PY = readFileSync('data-engine/app/services/review_alert_service.py', 'utf8');
const BODY = /def _severity\([^)]*\) -> str:([\s\S]*?)\n\n/.exec(PY)?.[1] ?? '';
const SEVERITIES = [...BODY.matchAll(/return "([a-z]+)"/g)].map((m) => m[1]);

const alerts = SEVERITIES.map((severity, i) => ({ id: i + 1, review_id: null, severity, message: `m${i}`, created_at: `2026-10-0${i + 1}T10:00:00Z` }));

describe('alertas del feed «Qué ha cambiado»: severidad traducida', () => {
  it('las severidades de prueba son las del backend', () => {
    expect(SEVERITIES).toEqual(['critical', 'high', 'medium', 'low']);
  });
  it('en castellano: «Alerta (alta)», nunca «Alerta (high)»', () => {
    const { container } = render(<ChangesFeed alerts={alerts} changes={[]} reviews={[]} ticker="ASTS" />);
    const text = container.textContent ?? '';
    for (const word of ['crítica', 'alta', 'media', 'baja']) expect(text).toContain(`Alerta (${word})`);
    for (const raw of SEVERITIES) expect(text).not.toContain(`(${raw})`);
  });
  it('en inglés: «Alert (high)»', () => {
    const { container } = render(<LocaleProvider locale="en"><ChangesFeed alerts={alerts} changes={[]} reviews={[]} ticker="ASTS" /></LocaleProvider>);
    const text = container.textContent ?? '';
    for (const word of ['critical', 'high', 'medium', 'low']) expect(text).toContain(`Alert (${word})`);
  });
});
