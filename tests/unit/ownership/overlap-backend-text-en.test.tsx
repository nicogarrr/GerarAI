import { readFileSync } from 'node:fs';
import path from 'node:path';

import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({ locale: 'en', message: 'Sin informes 13F sincronizados.' as string | null }));
vi.mock('next/headers', () => ({ cookies: async () => ({ get: () => ({ value: mocks.locale }) }) }));
vi.mock('@/lib/actions/investors.actions', () => ({
    getPortfolioOverlap: async () => ({
        positions: [
            { ticker: 'AAPL', name: 'Apple', cusip: '037833100', identity_source: 'CUSIP derivado del ISIN registrado', status: 'sin_coincidencias', holders: [] },
            { ticker: 'MSFT', name: 'Microsoft', cusip: '594918104', identity_source: 'Referencia openfigi · 2026-10-01', status: 'sin_coincidencias', holders: [] },
            { ticker: 'XYZ', name: 'Xyz', cusip: null, identity_source: 'Identidad en conflicto: los ISIN registrados no coinciden.', status: 'sin_coincidencias', holders: [] },
        ],
        not_owned: [], unresolved_positions: 1, report_dates: [], managers_with_data: 0, managers_without_data: 3, managers_partial: 0, message: mocks.message,
    }),
}));

import { Overlap } from '@/app/(root)/ownership/_components/Overlap';
import { OVERLAP_TEXT_EN, overlapText } from '@/lib/ownership/overlap-text';

const BACKEND = readFileSync(path.resolve(__dirname, '../../../data-engine/app/services/investor_overlap.py'), 'utf8');

describe('solape con tu cartera: textos del backend en inglés', () => {
    it('el backend sigue mandando cada frase de la tabla', () => {
        for (const sentence of Object.keys(OVERLAP_TEXT_EN)) expect(BACKEND).toContain(`"${sentence}"`);
        expect(BACKEND).toContain('f"Referencia {reference.source} · {reference.as_of.isoformat()}"');
    });

    it('con English: aviso y origen del CUSIP en inglés', async () => {
        mocks.locale = 'en';
        render(await Overlap({}));
        expect(screen.getByText('No 13F reports synced.')).toBeTruthy();
        expect(screen.getByText('CUSIP derived from the recorded ISIN')).toBeTruthy();
        expect(screen.getByText('Reference openfigi · 2026-10-01')).toBeTruthy();
        expect(screen.getByText('Identity conflict: the recorded ISINs do not match.')).toBeTruthy();
        expect(document.body.textContent).not.toMatch(/Sin informes|derivado|Referencia|Identidad/);
    });

    it('en castellano se pinta igual que antes', async () => {
        mocks.locale = 'es';
        render(await Overlap({}));
        expect(screen.getByText('Sin informes 13F sincronizados.')).toBeTruthy();
        expect(screen.getByText('CUSIP derivado del ISIN registrado')).toBeTruthy();
        expect(screen.getByText('Referencia openfigi · 2026-10-01')).toBeTruthy();
    });

    it('cartera vacía y textos desconocidos', () => {
        expect(overlapText('Cartera sin posiciones abiertas.', 'en')).toBe('Portfolio with no open positions.');
        expect(overlapText('Otro texto', 'en')).toBe('Otro texto');
        expect(overlapText(null, 'en')).toBeNull();
    });
});
