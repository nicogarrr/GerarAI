import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const m = vi.hoisted(() => ({
    // Objeto estable: el efecto de polling lleva `router` en sus dependencias.
    router: { refresh: vi.fn(), push: vi.fn() },
    searchParams: { get: vi.fn(() => null) },
    start: vi.fn(),
    latest: vi.fn(),
    status: vi.fn(),
    availabilityRefresh: vi.fn(),
}));

vi.mock('next/navigation', () => ({
    useRouter: () => m.router,
    useSearchParams: () => m.searchParams,
}));
// La puerta de disponibilidad de IA (main) deshabilita el botón si no se
// puede generar: sin este mock el click no llega nunca a startThesisJob.
vi.mock('@/components/ai/AiAvailabilityNotice', () => ({
    useAiAvailability: () => ({
        status: { feature: 'thesis', state: 'unverified', can_start: true, reason: 'not_probed', retry_after_seconds: null },
        failed: false,
        checking: false,
        canStart: true,
        refresh: m.availabilityRefresh,
    }),
    AiAvailabilityNotice: () => null,
}));
vi.mock('@/lib/actions/thesis-jobs.actions', () => ({
    startThesisJob: m.start,
    getLatestThesisJob: m.latest,
    getThesisJobStatus: m.status,
}));

import ThesisGenerateButton from '@/components/research/ThesisGenerateButton';
import type { ThesisJobStatus } from '@/lib/actions/thesis-jobs.actions';

const realCrypto = globalThis.crypto;

function runningJob(): ThesisJobStatus {
    return {
        id: 42,
        ticker: 'TEST',
        status: 'running',
        attempt: 1,
        created_at: null,
        current_phase: null,
        error_class: null,
        error_message: null,
        finished_at: null,
        force: true,
        phases: [],
        result: null,
        started_at: null,
        total_phases: 0,
        workflow_name: 'thesis',
    };
}

beforeEach(() => {
    vi.resetAllMocks();
    m.availabilityRefresh.mockResolvedValue(true);
    m.latest.mockResolvedValue(null);
    m.start.mockResolvedValue(runningJob());
    m.status.mockResolvedValue(runningJob());
});

afterEach(() => {
    vi.unstubAllGlobals();
});

describe('ThesisGenerateButton: feedback honesto', () => {
    it('envía con un request_id de fallback si crypto.randomUUID no existe', async () => {
        // Contexto no seguro: crypto existe pero no expone randomUUID. Antes el
        // TypeError se caía al catch y se decía "envío no confirmado" sin enviar.
        vi.stubGlobal('crypto', {
            getRandomValues: realCrypto.getRandomValues.bind(realCrypto),
        });

        render(<ThesisGenerateButton ticker="TEST" />);
        fireEvent.click(await screen.findByRole('button', { name: 'Generar tesis' }));

        await waitFor(() => expect(m.start).toHaveBeenCalledOnce());
        const requestId: unknown = m.start.mock.calls[0][2];
        expect(typeof requestId).toBe('string');
        expect(requestId).toMatch(/^thesis-/);
        expect(screen.queryByText(/No se pudo confirmar el envío/)).not.toBeInTheDocument();
    }, 20000);

    it('avisa del fallo de red en el polling y permite consultar de nuevo', async () => {
        m.latest.mockResolvedValue(runningJob());
        m.status.mockRejectedValueOnce(new Error('offline'));

        render(<ThesisGenerateButton ticker="TEST" />);

        expect(await screen.findByRole('alert')).toHaveTextContent('No se pudo consultar el estado');
        expect(screen.queryByText(/Estado desconocido/)).not.toBeInTheDocument();
        expect(m.router.refresh).not.toHaveBeenCalled();

        fireEvent.click(screen.getByRole('button', { name: 'Consultar ahora' }));

        await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument());
        expect(m.status).toHaveBeenCalledTimes(2);
        expect(m.status).toHaveBeenCalledWith(42);
        expect(m.router.refresh).not.toHaveBeenCalled();
    }, 20000);
});
