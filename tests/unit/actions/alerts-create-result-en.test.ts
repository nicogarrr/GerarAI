import { readFileSync } from 'node:fs';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const { researchRequest, requireAuthenticatedUser, invalidate, locale } = vi.hoisted(() => ({
    researchRequest: vi.fn(),
    requireAuthenticatedUser: vi.fn(),
    invalidate: vi.fn(),
    locale: { value: 'en' },
}));
vi.mock('next/headers', () => ({ cookies: async () => ({ get: () => ({ value: locale.value }) }) }));
vi.mock('@/lib/research/client', () => ({ researchRequest, jsonBody: JSON.stringify }));
vi.mock('@/lib/cache/memoryTTL', () => ({ cachedFetch: (_key: string, fetcher: () => Promise<unknown>) => fetcher() }));
vi.mock('@/lib/cache/requestCache', () => ({ requestCache: { invalidate } }));
vi.mock('@/lib/auth/require-user', () => ({ requireAuthenticatedUser }));

import { AppError } from '@/lib/types/errors';
import { createAlertResult } from '@/lib/actions/alerts.actions';

// Frase real del motor (ui_errors.py, symbol_not_recognized), leída del .py.
const UI_ERRORS = readFileSync('data-engine/app/core/ui_errors.py', 'utf8');
const UNKNOWN_ES = UI_ERRORS.match(/"symbol_not_recognized": \{\s*"es": "([^"]+)",\s*"en": "([^"]+)"/)!;
const sentence = (template: string, ticker: string) => template.replace('{ticker}', ticker);

const input = { symbol: 'zzzqx', type: 'price_above' as const, condition: { operator: '>' as const, value: 250 } };

describe('alta de alerta: rechazos en el idioma de la pantalla', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        requireAuthenticatedUser.mockResolvedValue({ id: 'u1' });
    });

    it('en inglés, el 422 «Símbolo no reconocido» del motor sale en inglés (la misma frase que el motor tiene en inglés)', async () => {
        locale.value = 'en';
        researchRequest.mockResolvedValueOnce({ id: 1 }).mockRejectedValueOnce(new AppError(sentence(UNKNOWN_ES[1], 'ZZZQX'), 'RESEARCH_API_ERROR', 422));
        await expect(createAlertResult(input)).resolves.toEqual({ ok: false, cause: 'validation', message: sentence(UNKNOWN_ES[2], 'ZZZQX') });
    });

    it('en inglés, el 404 tampoco sale en castellano', async () => {
        locale.value = 'en';
        researchRequest.mockResolvedValueOnce({ id: 1 }).mockRejectedValueOnce(new AppError('Not Found', 'RESEARCH_API_ERROR', 404));
        await expect(createAlertResult(input)).resolves.toEqual({ ok: false, cause: 'validation', message: sentence(UNKNOWN_ES[2], 'ZZZQX') });
    });

    it('en inglés, la alerta repetida dice «You already have this alert set up.»', async () => {
        locale.value = 'en';
        researchRequest.mockResolvedValueOnce({ id: 1 }).mockRejectedValueOnce(new AppError('duplicate', 'RESEARCH_API_ERROR', 409));
        await expect(createAlertResult(input)).resolves.toEqual({ ok: false, cause: 'duplicate', message: 'You already have this alert set up.' });
    });

    it('en castellano, las frases de siempre', async () => {
        locale.value = 'es';
        researchRequest.mockResolvedValueOnce({ id: 1 }).mockRejectedValueOnce(new AppError('Not Found', 'RESEARCH_API_ERROR', 404));
        await expect(createAlertResult(input)).resolves.toMatchObject({ message: sentence(UNKNOWN_ES[1], 'ZZZQX') });
        researchRequest.mockResolvedValueOnce({ id: 1 }).mockRejectedValueOnce(new AppError('duplicate', 'RESEARCH_API_ERROR', 409));
        await expect(createAlertResult(input)).resolves.toMatchObject({ message: 'Ya tienes esta alerta configurada.' });
    });
});
