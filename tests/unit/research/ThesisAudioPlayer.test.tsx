import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import ThesisAudioPlayer from '@/components/research/ThesisAudioPlayer';
const fetchMock = vi.fn();
const reply = (state: string, extra = {}) => ({ ok: true, json: async () => ({ state, ...extra }) });
beforeEach(() => { vi.useFakeTimers(); vi.stubGlobal('fetch', fetchMock); fetchMock.mockReset(); });
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });
const mount = async (version: number | null = 2) => { const view = render(<ThesisAudioPlayer ticker="A/B" version={version} />); await act(async () => {}); return view; };

describe('Thesis audio lifecycle with mocked HTTP', () => {
    it('polls after successfully requesting missing audio and eventually renders the ready player', async () => {
        fetchMock.mockResolvedValueOnce(reply('missing')).mockResolvedValueOnce({ ok: true }).mockResolvedValueOnce(reply('pending')).mockResolvedValueOnce(reply('ready'));
        const view = await mount();
        expect(view.container.querySelector('audio')).toBeNull();
        await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Generar audio' })); });
        expect(screen.getByRole('status')).toHaveTextContent('Generando audio');
        await act(async () => vi.advanceTimersByTimeAsync(5000));
        await act(async () => vi.advanceTimersByTimeAsync(5000));
        expect(fetchMock).toHaveBeenCalledTimes(4);
        const audio = view.container.querySelector('audio')!;
        expect(audio).toHaveAttribute('src', '/api/thesis/A%2FB/audio?version=2');
        expect(audio).toHaveAttribute('controls'); expect(audio).toHaveAttribute('preload', 'none');
        expect(fetchMock.mock.calls[1]).toEqual(['/api/thesis/A%2FB/audio?version=2', { method: 'POST' }]);
    });
    it('polls recovered pending state and stops when ready, then handles media failure', async () => {
        fetchMock.mockResolvedValueOnce(reply('pending')).mockResolvedValueOnce(reply('ready'));
        const view = await mount(null);
        await act(async () => vi.advanceTimersByTimeAsync(5000));
        const audio = view.container.querySelector('audio')!;
        expect(audio).toHaveAttribute('src', '/api/thesis/A%2FB/audio');
        await act(async () => vi.advanceTimersByTimeAsync(15000));
        expect(fetchMock).toHaveBeenCalledTimes(2);
        fireEvent.error(audio);
        expect(screen.getByRole('button', { name: 'Reintentar' })).toBeEnabled();
    });
    it('does not offer generation if no thesis is published', async () => {
        fetchMock.mockResolvedValue(reply('missing', { hasKey: false }));
        await mount(); expect(screen.getByText(/aún no hay tesis publicada/)).toBeVisible();
        expect(screen.queryByRole('button')).not.toBeInTheDocument();
    });
    it.each(['unknown', 'absent', 'reject'])('handles status %s without a fake player', async mode => {
        if (mode === 'reject') fetchMock.mockRejectedValue(new Error('offline'));
        else fetchMock.mockResolvedValue(mode === 'absent' ? { json: async () => ({}) } : reply('unknown'));
        const view = await mount();
        expect(view.container.querySelector('audio')).toBeNull();
        expect(screen.getByRole('button', { name: 'Reintentar' })).toBeEnabled();
    });
    it.each([false, true])('re-enables generation on failure rejected=%s', async rejected => {
        fetchMock.mockResolvedValueOnce(reply('missing'));
        if (rejected) fetchMock.mockRejectedValueOnce(new Error('offline'));
        else fetchMock.mockResolvedValueOnce({ ok: false });
        await mount();
        await act(async () => { fireEvent.click(screen.getByRole('button')); });
        expect(screen.getByRole('button', { name: 'Reintentar' })).toBeEnabled();
    });
    it('blocks duplicate generation until the POST finishes', async () => {
        let finish!: (res: { ok: boolean }) => void;
        fetchMock.mockResolvedValueOnce(reply('missing')).mockReturnValueOnce(new Promise(resolve => { finish = resolve; }));
        await mount(); fireEvent.click(screen.getByRole('button')); expect(screen.getByRole('button')).toBeDisabled();
        fireEvent.click(screen.getByRole('button')); expect(fetchMock).toHaveBeenCalledTimes(2);
        await act(async () => finish({ ok: false })); expect(screen.getByRole('button')).toBeEnabled();
    });
    it('cleans pending timers and ignores late status responses on unmount', async () => {
        fetchMock.mockResolvedValue(reply('pending')); const view = await mount(); view.unmount();
        await act(async () => vi.advanceTimersByTimeAsync(10000)); expect(fetchMock).toHaveBeenCalledOnce();
        let finish!: (res: ReturnType<typeof reply>) => void;
        fetchMock.mockReturnValueOnce(new Promise(resolve => { finish = resolve; }));
        const second = render(<ThesisAudioPlayer ticker="TEST" version={1} />); second.unmount();
        await act(async () => finish(reply('ready'))); expect(second.container).toBeEmptyDOMElement();
    });
});
