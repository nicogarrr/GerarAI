import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { AppError } from '@/lib/types/errors';
import { renderWithRateLimit } from '@/lib/research/render-with-rate-limit';
const refresh = vi.hoisted(() => vi.fn());
vi.mock('next/navigation', () => ({ useRouter: () => ({ refresh }) }));
afterEach(() => { vi.useRealTimers(); vi.clearAllMocks(); });

it('renders a clear 429 state before Next redacts the server error, with a cooldown and manual retry', async () => {
    const result = await renderWithRateLimit(async () => { throw new AppError('Rate limit exceeded', 'RESEARCH_API_ERROR', 429); });
    vi.useFakeTimers();
    render(result);
    expect(screen.getByRole('alert')).toHaveTextContent('Demasiadas peticiones');
    expect(screen.getByRole('alert')).toHaveTextContent('Espera a que termine la cuenta atrás antes de volver a intentarlo. Tus datos no han cambiado.');
    const retry = screen.getByRole('button');
    expect(retry).toBeDisabled();
    fireEvent.click(retry);
    expect(refresh).not.toHaveBeenCalled();
    await act(async () => { vi.advanceTimersByTime(59_000); });
    expect(retry).toBeDisabled();
    await act(async () => { vi.advanceTimersByTime(1_000); });
    expect(retry).toBeEnabled();
    expect(refresh).not.toHaveBeenCalled(); // never auto-retry into a sliding window
    fireEvent.click(retry);
    expect(refresh).toHaveBeenCalledOnce();
    expect(retry).toBeDisabled(); // a rapid second click cannot generate another burst
});

it.each([401, 403, 404, 500])('preserves non-429 error %i instead of inventing throttling', async status => {
    const error = new AppError('other', 'RESEARCH_API_ERROR', status);
    await expect(renderWithRateLimit(async () => { throw error; })).rejects.toBe(error);
});
it('preserves redirects and success output', async () => {
    const redirect = Object.assign(new Error('NEXT_REDIRECT'), { digest: 'NEXT_REDIRECT;replace;/sign-in;307;' });
    await expect(renderWithRateLimit(async () => { throw redirect; })).rejects.toBe(redirect);
    const element = <p>MSFT</p>;
    expect(await renderWithRateLimit(async () => element)).toBe(element);
});

it('uses the longer server cooldown instead of enabling retry after 60 seconds', async () => {
    const result = await renderWithRateLimit(async () => { throw new AppError('limited', 'RESEARCH_API_ERROR', 429, { retryAfterSeconds: 120 }); });
    vi.useFakeTimers();
    render(result);
    await act(async () => { vi.advanceTimersByTime(60_000); });
    expect(screen.getByRole('button')).toBeDisabled();
    await act(async () => { vi.advanceTimersByTime(60_000); });
    expect(screen.getByRole('button')).toBeEnabled();
});

it('keeps the route wired through the server boundary, not the redacted client error screen', async () => {
    const { readFileSync } = await import('node:fs');
    const source = readFileSync('app/(root)/research/[ticker]/page.tsx', 'utf8');
    expect(source).toContain('return renderWithRateLimit(() => ResearchCompanyContent(props));');
});

it('shows the cooldown in English too', async () => {
    const { LocaleProvider } = await import('@/lib/i18n/client');
    const result = await renderWithRateLimit(async () => { throw new AppError('limited', 'RESEARCH_API_ERROR', 429); });
    render(<LocaleProvider locale="en">{result}</LocaleProvider>);
    expect(screen.getByRole('alert')).toHaveTextContent('Too many requests');
    expect(screen.getByRole('alert')).toHaveTextContent('Wait for the countdown to finish before trying again. Your data has not changed.');
    expect(screen.getByRole('button', { name: 'Retry in 60 s' })).toBeDisabled();
});

it.each([60, 120])('a new server 429 restarts the cooldown immediately even with waitSeconds=%i', async seconds => {
    const response = () => renderWithRateLimit(async () => { throw new AppError('limited', 'RESEARCH_API_ERROR', 429, { retryAfterSeconds: seconds }); });
    const first = await renderWithRateLimit(async () => { throw new AppError('limited', 'RESEARCH_API_ERROR', 429); });
    vi.useFakeTimers();
    const view = render(first);
    await act(async () => { vi.advanceTimersByTime(60_000); });
    expect(screen.getByRole('button')).toBeEnabled();
    const second = await response();
    view.rerender(second);
    // No tick elapses here: a fresh response must lock the button on commit.
    expect(screen.getByRole('button')).toBeDisabled();
    expect(screen.getByRole('button')).toHaveTextContent(`Reintentar en ${seconds} s`);
    await act(async () => { vi.advanceTimersByTime((seconds - 1) * 1000); });
    expect(screen.getByRole('button')).toBeDisabled();
    await act(async () => { vi.advanceTimersByTime(1000); });
    expect(screen.getByRole('button')).toBeEnabled();
});
