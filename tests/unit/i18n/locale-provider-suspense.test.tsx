import { Suspense } from 'react';
import { act, render, screen } from '@testing-library/react';
import { expect, test, vi } from 'vitest';

const state = vi.hoisted(() => ({ spanish: false, english: false, finishSpanish: () => {}, finishEnglish: () => {}, promises: new Set<unknown>() }));
vi.mock('react', async (importOriginal) => {
    const actual = await importOriginal<typeof import('react')>();
    return { ...actual, use: (...args: Parameters<typeof actual.use>) => {
        state.promises.add(args[0]);
        return actual.use(...args);
    } };
});
vi.mock('#i18n-en-compact', () => ({
    loadCompactEnglish: () => new Promise<void>((resolve) => { state.finishEnglish = resolve; }),
}));
vi.mock('@/lib/i18n/messages/index.ts', () => ({
    I18N_AREAS: ['common', 'brain'],
    hasSpanishAreas: () => state.spanish,
    hasEnglishMessages: () => state.english,
    loadSpanishAreas: () => state.spanish ? Promise.resolve() : new Promise<void>((resolve) => {
        const previous = state.finishSpanish;
        state.finishSpanish = () => { previous(); state.spanish = true; resolve(); };
    }),
    registerCompactEnglish: () => { state.english = true; },
    getSpanishRecoveryVersion: () => 0,
    subscribeSpanishRecovery: () => () => {},
}));
import { LocaleProvider } from '@/lib/i18n/client';

test('cold English keeps the same suspended promise when Spanish finishes first', async () => {
    const errors = vi.spyOn(console, 'error').mockImplementation(() => {});
    await act(async () => { render(<Suspense fallback={<p>Loading locale</p>}><LocaleProvider locale="en"><p>Brain ready</p></LocaleProvider></Suspense>); });
    expect(screen.getByText('Loading locale')).toBeInTheDocument();
    await act(async () => { state.finishSpanish(); });
    expect(screen.queryByText('Brain ready')).not.toBeInTheDocument();
    await act(async () => { state.finishEnglish(); });
    expect(await screen.findByText('Brain ready')).toBeInTheDocument();
    // A suspended render must not replace its first thenable with the next
    // locale dependency when the Spanish stage finishes.
    expect(state.promises.size).toBe(1);
    expect(errors.mock.calls.flat().join('\n')).not.toContain('uncached promise');
});
