import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { NewsSecondOrder } from '@/components/research/NewsSecondOrder';
const fetchMock = vi.fn();
const reply = (data: unknown, ok = true) => ({ ok, json: async () => data });
const empty = { status: 'sin_datos', mode: 'determinista', candidates: [] };
const toggle = (details: HTMLDetailsElement, open: boolean) => { details.open = open; fireEvent(details, new Event('toggle')); };
const mount = (subjectTicker?: string) => {
    const view = render(<NewsSecondOrder eventId={42} summary="Contexto y efectos" subjectTicker={subjectTicker}><p>Contexto original</p></NewsSecondOrder>);
    return view.container.querySelector('details')!;
};
beforeEach(() => { fetchMock.mockReset(); vi.stubGlobal('fetch', fetchMock); });
afterEach(() => vi.unstubAllGlobals());

describe('News second order lazy loading with mocked HTTP', () => {
    it('loads only when opened, blocks concurrent requests and reuses a successful result', async () => {
        let finish!: (value: ReturnType<typeof reply>) => void;
        fetchMock.mockReturnValue(new Promise(resolve => { finish = resolve; }));
        const details = mount('TEST');
        expect(fetchMock).not.toHaveBeenCalled();
        expect(screen.getByText('Contexto original')).toBeInTheDocument();
        toggle(details, true); expect(screen.getByRole('status')).toHaveTextContent('Calculando');
        toggle(details, false); toggle(details, true); expect(fetchMock).toHaveBeenCalledOnce();
        await act(async () => finish(reply(empty)));
        expect(screen.getByText(/excluye a propósito a la propia TEST/)).toBeVisible();
        toggle(details, false); toggle(details, true); expect(fetchMock).toHaveBeenCalledOnce();
        expect(fetchMock.mock.calls[0][0]).toBe('/api/news/42/second-order');
    });
    it('does not imply a primary ticker when no subject was supplied', async () => {
        fetchMock.mockResolvedValue(reply(empty)); const details = mount(); toggle(details, true);
        expect(await screen.findByText('Sin empresas del universo expuestas a esta noticia.')).toBeVisible();
    });
    it.each(['http', 'schema', 'rejected'])('reports %s failure and retries on reopen', async mode => {
        if (mode === 'rejected') fetchMock.mockRejectedValueOnce(new Error('offline'));
        else fetchMock.mockResolvedValueOnce(mode === 'http' ? reply({}, false) : reply({ candidates: null }));
        fetchMock.mockResolvedValueOnce(reply(empty)); const details = mount(); toggle(details, true);
        expect(await screen.findByText(/No disponible ahora/)).toBeVisible();
        toggle(details, false); toggle(details, true);
        expect(await screen.findByText('Sin empresas del universo expuestas a esta noticia.')).toBeVisible();
        expect(fetchMock).toHaveBeenCalledTimes(2);
    });
    it.each(['llm', 'determinista'])('groups unverified %s hypotheses and caps visible candidates', async mode => {
        const candidate = (ticker: string, direction: string, full = false) => ({ ticker, direction,
            company_name: full ? 'Synthetic company' : null, exposure: { field: 'sector', value: 'Local exposure' },
            causal_chain: full ? [{ cause: 'Causa local', effect: 'Efecto local' }] : [],
        });
        fetchMock.mockResolvedValue(reply({ status: 'hipótesis_no_verificadas', mode, candidates: [
            ...Array.from({ length: 10 }, (_, i) => candidate(`UP${i}`, 'beneficiada', i === 0)),
            candidate('DOWN', 'perjudicada'), candidate('UNKNOWN', 'incierta'),
        ] }));
        const details = mount(); toggle(details, true);
        expect(await screen.findByText(`Hipótesis no verificadas · ${mode === 'llm' ? 'modelo' : 'reglas'}`)).toBeVisible();
        expect(screen.getByRole('heading', { name: 'Beneficiadas (10)' })).toBeVisible();
        expect(screen.getByRole('heading', { name: 'Perjudicadas (1)' })).toBeVisible();
        expect(screen.getByRole('heading', { name: 'Dirección incierta (1)' })).toBeVisible();
        expect(screen.getAllByRole('link')).toHaveLength(10);
        expect(screen.queryByRole('link', { name: 'UP8' })).not.toBeInTheDocument();
        expect(screen.getByRole('link', { name: 'UP0' })).toHaveAttribute('href', '/research/UP0');
        expect(screen.getByText('y 2 más')).toBeVisible();
        expect(screen.getByText('Causa local → Efecto local')).toBeVisible();
        expect(screen.getByText(/Synthetic company/)).toBeVisible();
    });
});
