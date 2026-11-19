import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { LocaleProvider } from '@/lib/i18n/client';
import ThesisGenerateButton from '@/components/research/ThesisGenerateButton';
const m = vi.hoisted(() => ({ latest: vi.fn(), poll: vi.fn(), start: vi.fn(), refresh: vi.fn(), available: vi.fn(), canStart: true, view: 'thesis', scroll: vi.fn() }));
vi.mock('@/lib/actions/thesis-jobs.actions', () => ({ getLatestThesisJob: m.latest, getThesisJobStatus: m.poll, startThesisJob: m.start }));
vi.mock('next/navigation', () => { const router = { refresh: m.refresh }; return { useRouter: () => router, useSearchParams: () => ({ get: () => m.view }) }; });
vi.mock('@/lib/utils/scroll-anchor', () => ({ scrollToIdWhenReady: m.scroll }));
vi.mock('@/components/ai/AiAvailabilityNotice', () => ({ useAiAvailability: () => ({ canStart: m.canStart, refresh: m.available }), AiAvailabilityNotice: () => <p>Availability boundary</p> }));
const job = (status: string, extra = {}) => ({ id: 71, ticker: 'A/B', status, current_phase: null, ...extra });
const mount = async (props = {}) => { const ui = render(<LocaleProvider locale="en"><ThesisGenerateButton ticker="A/B" {...props} /></LocaleProvider>); await act(async () => {}); return ui; };
const advance = async (ms: number) => { await act(async () => { await vi.advanceTimersByTimeAsync(ms); }); };
beforeEach(() => { vi.useFakeTimers(); vi.clearAllMocks(); m.canStart = true; m.view = 'thesis'; m.available.mockResolvedValue(true); m.latest.mockResolvedValue(null); m.start.mockResolvedValue(job('queued')); m.poll.mockResolvedValue(job('running')); });
afterEach(() => { vi.useRealTimers(); });
describe('thesis job lifecycle without any model call', () => {
    it('recovers an existing active job, polls at 3 seconds and never starts work on mount', async () => {
        m.latest.mockResolvedValue(job('queued')); await mount(); expect(m.start).not.toHaveBeenCalled(); expect(m.poll).toHaveBeenCalledWith(71); expect(screen.getByRole('button')).toBeDisabled(); await advance(2999); expect(m.poll).toHaveBeenCalledTimes(1); await advance(1); expect(m.poll).toHaveBeenCalledTimes(2); expect(m.refresh).not.toHaveBeenCalled();
    });
    it('retries an uncertain recovery instead of offering a duplicate generation', async () => {
        m.latest.mockRejectedValueOnce(new Error('offline')).mockResolvedValue(null); await mount(); expect(screen.getByRole('button')).toBeDisabled(); await advance(3000); expect(m.latest).toHaveBeenCalledTimes(2); expect(screen.getByRole('button')).toBeEnabled(); expect(m.start).not.toHaveBeenCalled();
    });
    it('checks fresh availability before explicit start and deduplicates repeated clicks', async () => {
        let resolve!: (v: unknown) => void; m.start.mockImplementation(() => new Promise(r => { resolve = r; })); await mount(); const button = screen.getByRole('button'); await act(async () => { fireEvent.click(button); }); expect(m.available).toHaveBeenCalledOnce(); expect(m.start).toHaveBeenCalledWith('A/B', true, expect.any(String)); expect(button).toBeDisabled(); fireEvent.click(button); expect(m.start).toHaveBeenCalledOnce(); await act(async () => resolve(job('queued'))); expect(m.poll).toHaveBeenCalledWith(71);
    });
    it('locks repeated clicks while the fresh availability check is still pending', async () => {
        let resolve!: (allowed: boolean) => void;
        const pending = new Promise<boolean>(r => { resolve = r; });
        m.available.mockReturnValue(pending);
        await mount();
        const button = screen.getByRole('button');
        fireEvent.click(button);
        fireEvent.click(button);
        await act(async () => { resolve(true); });
        expect(m.start).toHaveBeenCalledOnce();
        expect(m.available).toHaveBeenCalledOnce();
        expect(m.start).toHaveBeenCalledWith('A/B', true, expect.any(String));
    });
    it('releases the pending availability lock after denial so a later click can retry', async () => {
        m.available.mockResolvedValueOnce(false).mockResolvedValue(true);
        await mount();
        await act(async () => { fireEvent.click(screen.getByRole('button')); });
        expect(m.start).not.toHaveBeenCalled();
        expect(screen.getByRole('button')).toBeEnabled();
        await act(async () => { fireEvent.click(screen.getByRole('button')); });
        expect(m.available).toHaveBeenCalledTimes(2);
        expect(m.start).toHaveBeenCalledOnce();
    });
    it.each([false, true])('does not start when availability denies the request (initial denied=%s)', async denied => {
        m.canStart = !denied; m.available.mockResolvedValue(false); await mount(); await act(async () => { fireEvent.click(screen.getByRole('button')); }); expect(m.start).not.toHaveBeenCalled(); expect(m.available).toHaveBeenCalledTimes(denied ? 0 : 1);
    });
    it('offers a deliberate anchored refresh only after this session succeeds', async () => {
        m.poll.mockResolvedValue(job('succeeded', { result: { version: 9, status: 'draft_failed_audit' } })); await mount({ emptyCopy: 'No thesis yet' }); await act(async () => { fireEvent.click(screen.getByRole('button')); }); expect(screen.queryByText('No thesis yet')).not.toBeInTheDocument(); expect(screen.queryByRole('button')).not.toBeInTheDocument(); const link = screen.getByRole('link', { name: 'View thesis v9' }); expect(link).toHaveAttribute('href', '/research/A%2FB?view=thesis'); expect(m.refresh).not.toHaveBeenCalled(); fireEvent.click(link); expect(m.refresh).toHaveBeenCalledOnce(); expect(m.scroll).toHaveBeenCalledWith('tesis-actual'); expect(screen.getByText(/9.*audit/i)).toBeInTheDocument();
    });
    it('does not announce an old successful job as a freshly generated thesis', async () => {
        m.latest.mockResolvedValue(job('succeeded', { result: { version: 8 } })); await mount(); expect(screen.queryByRole('link', { name: /View thesis/i })).not.toBeInTheDocument(); expect(screen.getByRole('link', { name: 'Add evidence' })).toHaveAttribute('href', '/knowledge?tab=subir'); expect(screen.getByRole('button')).toBeEnabled(); expect(m.poll).not.toHaveBeenCalled(); expect(m.refresh).not.toHaveBeenCalled(); expect(m.scroll).not.toHaveBeenCalled();
    });
    it('reports failure and stops polling without refreshing or silently restarting', async () => {
        m.latest.mockResolvedValue(job('queued')); m.poll.mockResolvedValue(job('failed', { error_class: 'provider_unavailable' })); await mount(); expect(screen.getByText(/provider_unavailable/)).toBeInTheDocument(); await advance(10000); expect(m.poll).toHaveBeenCalledOnce(); expect(m.start).not.toHaveBeenCalled(); expect(m.refresh).not.toHaveBeenCalled();
    });
    it('does not relabel an old successful job as fresh when submission fails', async () => {
        m.latest.mockResolvedValue(job('succeeded', { result: { version: 8 } }));
        m.start.mockRejectedValue(new Error('submission offline'));
        await mount();
        await act(async () => { fireEvent.click(screen.getByRole('button')); });
        expect(m.start).toHaveBeenCalledOnce();
        expect(screen.queryByRole('link', { name: /View thesis/i })).not.toBeInTheDocument();
        expect(m.refresh).not.toHaveBeenCalled();
        expect(m.scroll).not.toHaveBeenCalled();
    });
    it('keeps the old success quiet while a new submission is still pending', async () => {
        let resolve!: (value: unknown) => void;
        m.latest.mockResolvedValue(job('succeeded', { result: { version: 8 } }));
        m.start.mockImplementation(() => new Promise(r => { resolve = r; }));
        await mount();
        await act(async () => { fireEvent.click(screen.getByRole('button')); });
        expect(screen.queryByRole('link', { name: /View thesis/i })).not.toBeInTheDocument();
        await act(async () => { resolve(job('succeeded', { id: 72, result: { version: 9 } })); });
        expect(screen.getByRole('link', { name: 'View thesis v9' })).toBeInTheDocument();
    });
    it('announces a genuinely new job recovered after an uncertain submission', async () => {
        m.latest.mockResolvedValueOnce(job('succeeded', { result: { version: 8 } }))
            .mockResolvedValue(job('running', { id: 72 }));
        m.start.mockRejectedValue(new Error('response lost'));
        m.poll.mockResolvedValue(job('succeeded', { id: 72, result: { version: 9 } }));
        await mount();
        await act(async () => { fireEvent.click(screen.getByRole('button')); });
        expect(m.start).toHaveBeenCalledOnce();
        expect(screen.getByRole('link', { name: 'View thesis v9' })).toBeInTheDocument();
        expect(m.refresh).not.toHaveBeenCalled();
    });
    it('recovers a start whose response was lost rather than submitting another job', async () => {
        m.start.mockRejectedValue(new Error('lost response')); m.latest.mockResolvedValueOnce(null).mockResolvedValue(job('running')); await mount(); await act(async () => { fireEvent.click(screen.getByRole('button')); }); expect(m.start).toHaveBeenCalledOnce(); expect(m.latest.mock.calls.length).toBeGreaterThanOrEqual(2); expect(m.poll).toHaveBeenCalledWith(71); expect(screen.getByRole('button')).toBeDisabled();
    });
    it('poll failure does not cancel server work and unmount stops later polls', async () => {
        m.latest.mockResolvedValue(job('queued')); m.poll.mockRejectedValue(new Error('poll offline')); const ui = await mount(); expect(m.poll).toHaveBeenCalledOnce(); await advance(3000); expect(m.poll).toHaveBeenCalledTimes(2); ui.unmount(); await advance(6000); expect(m.poll).toHaveBeenCalledTimes(2); expect(m.start).not.toHaveBeenCalled();
    });
    it('after 600 unsuccessful polls reports unknown state rather than faking endless progress', async () => {
        m.latest.mockResolvedValue(job('queued')); m.poll.mockRejectedValue(new Error('offline')); await mount(); for(let i=0;i<599;i++) await advance(3000); expect(m.poll).toHaveBeenCalledTimes(600); expect(screen.getByText(/unknown/i)).toBeInTheDocument(); await advance(30000); expect(m.poll).toHaveBeenCalledTimes(600); expect(m.start).not.toHaveBeenCalled();
    });
    it('ignores a focus recovery started before a new job was submitted', async () => {
        let resolveOld!: (value: unknown) => void;
        m.latest.mockResolvedValueOnce(job('succeeded', { result: { version: 8 } }))
            .mockImplementationOnce(() => new Promise(r => { resolveOld = r; }));
        m.start.mockResolvedValue(job('queued', { id: 72 }));
        m.poll.mockResolvedValue(job('running', { id: 72 }));
        await mount();
        window.dispatchEvent(new Event('focus'));
        await act(async () => { fireEvent.click(screen.getByRole('button')); });
        expect(m.poll).toHaveBeenCalledWith(72);
        await act(async () => { resolveOld(job('succeeded', { result: { version: 8 } })); });
        expect(screen.getByRole('button')).toBeDisabled();
        await advance(3000);
        expect(m.poll).toHaveBeenLastCalledWith(72);
        expect(m.poll).toHaveBeenCalledTimes(2);
        expect(m.start).toHaveBeenCalledOnce();
    });
    it('keeps the latest focus recovery when an older request resolves last', async () => {
        let resolveOld!: (value: unknown) => void;
        m.latest.mockResolvedValueOnce(null)
            .mockImplementationOnce(() => new Promise(r => { resolveOld = r; }))
            .mockResolvedValue(job('running', { id: 72 }));
        m.poll.mockResolvedValue(job('running', { id: 72 }));
        await mount();
        window.dispatchEvent(new Event('focus'));
        await act(async () => { window.dispatchEvent(new Event('focus')); });
        expect(m.poll).toHaveBeenCalledWith(72);
        await act(async () => { resolveOld(null); });
        expect(screen.getByRole('button')).toBeDisabled();
        await advance(3000);
        expect(m.poll).toHaveBeenCalledTimes(2);
        expect(m.start).not.toHaveBeenCalled();
    });
    it('does not let a pending focus snapshot undo a terminal polling result', async () => {
        let resolveRecovery!: (value: unknown) => void;
        let resolvePoll!: (value: unknown) => void;
        m.latest.mockResolvedValueOnce(job('running'))
            .mockImplementationOnce(() => new Promise(r => { resolveRecovery = r; }));
        m.poll.mockImplementationOnce(() => new Promise(r => { resolvePoll = r; }));
        await mount();
        window.dispatchEvent(new Event('focus'));
        await act(async () => { resolvePoll(job('succeeded', { result: { version: 8 } })); });
        expect(screen.getByRole('button')).toBeEnabled();
        await act(async () => { resolveRecovery(job('running')); });
        expect(screen.getByRole('button')).toBeEnabled();
        await advance(3000);
        expect(m.poll).toHaveBeenCalledOnce();
        expect(m.start).not.toHaveBeenCalled();
    });
    it('rechecks the server on focus and visibility but detaches listeners on unmount', async () => {
        const ui = await mount(); await act(async () => { window.dispatchEvent(new Event('focus')); }); expect(m.latest).toHaveBeenCalledTimes(2); Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'hidden' }); await act(async () => { document.dispatchEvent(new Event('visibilitychange')); }); expect(m.latest).toHaveBeenCalledTimes(2); Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' }); await act(async () => { document.dispatchEvent(new Event('visibilitychange')); }); expect(m.latest).toHaveBeenCalledTimes(3); ui.unmount(); window.dispatchEvent(new Event('focus')); expect(m.latest).toHaveBeenCalledTimes(3);
    });
});
