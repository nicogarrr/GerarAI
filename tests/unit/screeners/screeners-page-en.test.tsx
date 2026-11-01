import React from 'react';
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({ locale: 'en' }));
vi.mock('next/headers', () => ({ cookies: async () => ({ get: () => ({ value: mocks.locale }) }) }));
vi.mock('react-dom', async (original) => ({ ...(await original<typeof import('react-dom')>()), useFormStatus: () => ({ pending: false }) }));
vi.mock('@/lib/actions/research-tools.actions', () => ({}));

import { generateMetadata } from '@/app/(root)/screeners/page';
import { SubmitButton } from '@/components/screeners/SubmitButton';
import es from '@/lib/i18n/messages/es/screener.json';
import en from '@/lib/i18n/messages/en/screener.json';
import { LocaleProvider } from '@/lib/i18n/client';

describe('Screeners en inglés', () => {
    it('el diccionario de la página tiene las mismas claves en los dos idiomas', () => {
        expect(Object.keys(en.screens).sort()).toEqual(Object.keys(es.screens).sort());
        expect(en.screens.resultsTitle).toBe('Filter results');
        expect(es.screens.resultsTitle).toBe('Resultados del filtro');
    });

    it('la descripción de la página sigue el idioma', async () => {
        mocks.locale = 'en';
        expect((await generateMetadata()).description).toMatch(/^Safe formulas run against the analysis engine/);
        mocks.locale = 'es';
        expect((await generateMetadata()).description).toMatch(/^Fórmulas seguras contra el motor de análisis/);
    });

    it('el botón de ejecutar sale en inglés', () => {
        render(<LocaleProvider locale="en"><SubmitButton /></LocaleProvider>);
        expect(screen.getByRole('button', { name: 'Run' })).toBeTruthy();
    });
});
