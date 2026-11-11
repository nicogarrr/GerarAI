import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createTranslator } from '@/lib/i18n/translate';
const m = vi.hoisted(() => ({ get: vi.fn(), generate: vi.fn() }));
vi.mock('@/lib/actions/ai-availability.actions', () => ({ getAiAvailability: m.get }));
vi.mock('@/lib/i18n/client', () => ({ useT: () => createTranslator('es') }));
import { AiAvailabilityNotice, useAiAvailability } from '@/components/ai/AiAvailabilityNotice';

function Demo() {
    const availability = useAiAvailability('chat');
    return <><AiAvailabilityNotice availability={availability} /><button disabled={!availability.canStart} onClick={async () => { if (await availability.refresh()) m.generate(); }}>Generate</button></>;
}
const ready = { feature: 'chat', state: 'unverified', can_start: true, reason: 'not_probed', retry_after_seconds: null };
beforeEach(() => { vi.resetAllMocks(); m.get.mockResolvedValue(ready); });

describe('AI readiness before the user sends anything', () => {
    it('shows a caveat and checks only local status, never generates on mount', async () => {
        render(<Demo />);
        expect(await screen.findByText(/IA configurada/)).toBeInTheDocument();
        expect(screen.getByText(/No confirma cuota/)).toBeInTheDocument();
        expect(m.generate).not.toHaveBeenCalled();
        fireEvent.click(screen.getByRole('button', { name: 'Generate' }));
        await waitFor(() => expect(m.generate).toHaveBeenCalledTimes(1));
        expect(m.get).toHaveBeenCalledTimes(2);
    });
    it('does not offer retry or send while breaker is active; refresh never generates', async () => {
        m.get.mockResolvedValue({ ...ready, state: 'paused', can_start: false, retry_after_seconds: 60 });
        render(<Demo />);
        expect(await screen.findByText(/IA en pausa/)).toBeInTheDocument();
        expect(screen.getByRole('button', { name: 'Generate' })).toBeDisabled();
        fireEvent.click(screen.getByRole('button', { name: 'Generate' }));
        fireEvent.click(screen.getByRole('button', { name: 'Actualizar estado' }));
        await waitFor(() => expect(m.get).toHaveBeenCalledTimes(2));
        expect(m.generate).not.toHaveBeenCalled();
    });
    it('a newly opened breaker on the preflight blocks a previously ready action', async () => {
        m.get.mockResolvedValueOnce(ready).mockResolvedValue({ ...ready, state: 'paused', can_start: false });
        render(<Demo />);
        await screen.findByText(/IA configurada/);
        fireEvent.click(screen.getByRole('button', { name: 'Generate' }));
        await screen.findByText(/IA en pausa/);
        expect(m.generate).not.toHaveBeenCalled();
    });
    it('unknown status fails closed, with a status refresh rather than an AI retry', async () => {
        m.get.mockRejectedValue(new Error('offline'));
        render(<Demo />);
        await screen.findByText(/No se ha podido comprobar/);
        expect(screen.getByRole('button', { name: 'Generate' })).toBeDisabled();
        expect(m.generate).not.toHaveBeenCalled();
    });
    it.each(['off', 'degraded'])('renders %s with no automatic generation', async (state) => {
        m.get.mockResolvedValue({ ...ready, state, can_start: state === 'degraded' });
        render(<Demo />);
        await waitFor(() => expect(screen.getByRole('status')).not.toHaveTextContent('Comprobando'));
        expect(m.generate).not.toHaveBeenCalled();
    });
});

it('ignores out-of-order replies and does not start from an obsolete preflight', async () => {
    const { renderHook } = await import('@testing-library/react');
    let old!: (value: typeof ready) => void;
    m.get.mockImplementationOnce(() => new Promise(resolve => { old = resolve; })).mockResolvedValueOnce({ ...ready, state: 'paused', can_start: false });
    const { result, unmount } = renderHook(() => useAiAvailability('chat'));
    await act(async () => { expect(await result.current.refresh()).toBe(false); });
    await act(async () => { old(ready); });
    expect(result.current.canStart).toBe(false);
    expect(result.current.status?.state).toBe('paused');
    unmount();
});
