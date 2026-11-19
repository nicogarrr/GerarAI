import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { LocaleProvider } from '@/lib/i18n/client';
import { OrderTicket } from '@/components/paper-trading/OrderTicket';
import { FxTicket } from '@/components/paper-trading/FxTicket';
import type { DemoStateView, SubmitResult } from '@/components/paper-trading/submit';

const { refresh } = vi.hoisted(() => ({ refresh: vi.fn() }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ refresh }) }));
// Search boundary only: exercise ticket selection/edit callbacks without a network.
vi.mock('@/components/search/TickerSearchInput', () => ({ TickerSearchInput: (p: {
    id: string; value: string; ariaLabel: string; onValueChange: (v: string) => void;
    onSelect: (stock: { symbol: string; name: string }) => void;
}) => <><input id={p.id} aria-label={p.ariaLabel} value={p.value} onChange={e => p.onValueChange(e.target.value)} />
    <button type="button" onClick={() => p.onSelect({ symbol: 'MSFT', name: 'Microsoft' })}>Select Microsoft</button></> }));
const state: DemoStateView = { cashEUR: 1000, cashUSD: 200, realizedEUR: 0, realizedUSD: 0, positions: [], violations: [], notices: [] };
const result = (outcome: 'filled' | 'duplicate' | 'rejected', reason: string | null = null): SubmitResult => ({ ok: true, outcome, reason, state });
function setup(kind: 'stock' | 'fx', submit = vi.fn().mockResolvedValue(result('filled')), disabled = false) {
    const view = render(<LocaleProvider locale="en">{kind === 'stock' ? <OrderTicket submitFill={submit} disabled={disabled} /> : <FxTicket submitFx={submit} disabled={disabled} />}</LocaleProvider>);
    const form = view.container.querySelector('form')!;
    const field = (suffix: string, value: string) => fireEvent.change(form.querySelector(`[id$="-${suffix}"]`)!, { target: { value } });
    const fill = () => {
        if (kind === 'stock') {
            fireEvent.click(screen.getByRole('button', { name: 'Select Microsoft' }));
            field('quantity', '2'); field('price', '12,50');
        } else { field('amount', '100,50'); field('rate', '1.1'); }
        field('executed', '2026-01-01T10:00');
    };
    const send = async () => { await act(async () => { fireEvent.submit(form); }); };
    return { ...view, form, field, fill, send, submit };
}
beforeEach(() => { refresh.mockReset(); vi.useFakeTimers({ toFake: ['Date'] }); vi.setSystemTime(new Date('2026-11-15T12:00:00Z')); });
afterEach(() => { vi.useRealTimers(); });

describe('manual fill ticket', () => {
    it('search selection does not choose currency; editing a selected symbol clears its old company name', () => {
        const ui = setup('stock');
        fireEvent.click(screen.getByRole('button', { name: 'USD' }));
        fireEvent.click(screen.getByRole('button', { name: 'Select Microsoft' }));
        expect(ui.form.querySelector('[id$="-name"]')).toHaveValue('Microsoft');
        expect(screen.getByRole('button', { name: 'USD' })).toHaveAttribute('aria-pressed', 'true');
        ui.field('symbol', 'NVDA');
        expect(ui.form.querySelector('[id$="-name"]')).toHaveValue('');
        ui.field('name', 'Manual Nvidia'); ui.field('symbol', 'NVDA.A');
        expect(ui.form.querySelector('[id$="-name"]')).toHaveValue('Manual Nvidia');
    });
    it('submits a normalized stock payload with parsed decimals, zero demo fee and the chosen currency', async () => {
        const ui = setup('stock'); ui.fill();
        ui.field('symbol', ' msft '); ui.field('name', ' Microsoft Corp ');
        fireEvent.click(screen.getByRole('button', { name: 'USD' }));
        await ui.send();
        expect(ui.submit).toHaveBeenCalledWith(expect.objectContaining({ instrument: { kind: 'accion', symbol: 'MSFT', name: 'Microsoft Corp' }, side: 'buy', openClose: 'open', quantity: 2, price: 12.5, currency: 'USD', fee: 0, executedAt: Date.UTC(2026, 0, 1, 10) }));
        expect(refresh).toHaveBeenCalledOnce();
        expect(ui.form.querySelector('[id$="-quantity"]')).toHaveValue('');
        expect(ui.form.querySelector('[id$="-price"]')).toHaveValue('');
        expect(screen.getByRole('status')).not.toBeEmptyDOMElement();
    });
    it('options use sell-to-close, put, multiplier100 and an historical execution date, not today', async () => {
        const ui = setup('stock'); ui.fill();
        fireEvent.click(screen.getByRole('button', { name: /option/i }));
        fireEvent.click(screen.getByRole('button', { name: 'Put' }));
        fireEvent.click(screen.getByRole('button', { name: 'Sell' }));
        ui.field('strike', '100.50'); ui.field('expiry', '2026-01-02');
        await ui.send();
        expect(ui.submit).toHaveBeenCalledWith(expect.objectContaining({ side: 'sell', openClose: 'close', quantity: 2, instrument: { kind: 'opcion', name: 'Microsoft', contract: { underlying: 'MSFT', callPut: 'put', strike: 100.5, expiry: '2026-01-02', multiplier: 100, deliverable: 'acciones', adjusted: false } } }));
    });
    it.each([['symbol', '', /symbol/i], ['name', '', /name/i], ['quantity', '1,2,3', /quantity/i], ['quantity', '1.5', /integer|whole/i], ['quantity', '0', /integer|whole/i], ['price', 'abc', /price/i], ['price', '0', /positive|greater/i], ['executed', '', /date|execution/i], ['executed', '2099-01-01T00:00', /future/i]])('blocks invalid %s=%s before invoking the action', async (field, value, message) => {
        const ui = setup('stock'); ui.fill(); ui.field(field, value); await ui.send();
        expect(ui.submit).not.toHaveBeenCalled(); expect(screen.getByRole('alert')).toHaveTextContent(message);
        ui.field('quantity', '3'); expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    });
    it.each([['strike', 'abc', /strike/i], ['strike', '0', /strike/i], ['expiry', '', /expir/i], ['expiry', '2025-01-01', /expir/i]])('blocks invalid option %s', async (field, value, message) => {
        const ui = setup('stock'); ui.fill(); fireEvent.click(screen.getByRole('button', { name: /option/i }));
        ui.field('strike', '100'); ui.field('expiry', '2026-01-02'); ui.field(field, value); await ui.send();
        expect(ui.submit).not.toHaveBeenCalled(); expect(screen.getByRole('alert')).toHaveTextContent(message);
    });
});

describe('guided option chain picker (CBOE delayed chain)', () => {
    const chainOk = {
        ok: true as const,
        underlying: 'MSFT',
        fetchedAt: 1_763_000_000_000,
        expiries: [
            { expiry: '2026-12-18', strikes: [
                { strike: 400, call: { price: 12.3, time: '2026-11-17T15:47:12' }, put: null },
                { strike: 410, call: null, put: null },
            ] },
        ],
    };
    const renderOptionTicket = (fetchOptionChain: (u: string) => Promise<unknown>) => {
        const view = render(<LocaleProvider locale="en"><OrderTicket submitFill={vi.fn()} fetchOptionChain={fetchOptionChain as never} /></LocaleProvider>);
        fireEvent.click(screen.getByRole('button', { name: /option/i }));
        fireEvent.click(screen.getByRole('button', { name: 'Select Microsoft' }));
        return view;
    };
    it('loads the chain on demand and picking expiry+strike fills the manual fields', async () => {
        const fetchOptionChain = vi.fn().mockResolvedValue(chainOk);
        renderOptionTicket(fetchOptionChain);
        await act(async () => { fireEvent.click(screen.getByRole('button', { name: /show real chain/i })); });
        expect(fetchOptionChain).toHaveBeenCalledWith('MSFT');
        const expirySelect = await screen.findByLabelText(/expiry \(chain\)/i);
        fireEvent.change(expirySelect, { target: { value: '2026-12-18' } });
        fireEvent.change(screen.getByLabelText(/strike \(chain\)/i), { target: { value: '400' } });
        expect((screen.getByLabelText('Strike') as HTMLInputElement).value).toBe('400');
        expect((screen.getByLabelText(/expiry/i, { selector: 'input' }) as HTMLInputElement).value).toBe('2026-12-18');
        expect(screen.getByText(/last delayed trade: 12.3 USD/i)).toBeInTheDocument();
        // El precio de la orden NUNCA se autorrellena desde la cadena.
        expect((screen.getByLabelText(/premium per share/i) as HTMLInputElement).value).toBe('');
    });
    it('a contract without a recorded trade says so instead of inventing a premium', async () => {
        const fetchOptionChain = vi.fn().mockResolvedValue(chainOk);
        renderOptionTicket(fetchOptionChain);
        await act(async () => { fireEvent.click(screen.getByRole('button', { name: /show real chain/i })); });
        const expirySelect = await screen.findByLabelText(/expiry \(chain\)/i);
        fireEvent.change(expirySelect, { target: { value: '2026-12-18' } });
        fireEvent.change(screen.getByLabelText(/strike \(chain\)/i), { target: { value: '410' } });
        expect(screen.getByText(/no recorded trade in this chain/i)).toBeInTheDocument();
    });
    it('a source failure is labelled and the manual inputs stay available', async () => {
        const fetchOptionChain = vi.fn().mockResolvedValue({ ok: false, reason: 'sourceUnavailable' });
        renderOptionTicket(fetchOptionChain);
        await act(async () => { fireEvent.click(screen.getByRole('button', { name: /show real chain/i })); });
        expect(await screen.findByText(/not responding right now/i)).toBeInTheDocument();
        expect(screen.getByLabelText('Strike')).toBeInTheDocument();
        expect(screen.queryByLabelText(/strike \(chain\)/i)).not.toBeInTheDocument();
    });
    it('warns when the typed contract is not in the fetched chain sample, without blocking it', async () => {
        const fetchOptionChain = vi.fn().mockResolvedValue(chainOk);
        renderOptionTicket(fetchOptionChain);
        await act(async () => { fireEvent.click(screen.getByRole('button', { name: /show real chain/i })); });
        const expirySelect = await screen.findByLabelText(/expiry \(chain\)/i);
        fireEvent.change(expirySelect, { target: { value: '2026-12-18' } });
        // Strike escrito a mano que no esta en la muestra: aviso, no error.
        fireEvent.change(screen.getByLabelText('Strike'), { target: { value: '999' } });
        expect(screen.getByText(/not in the fetched sample/i)).toBeInTheDocument();
        // Vuelve a un strike listado: el aviso desaparece.
        fireEvent.change(screen.getByLabelText('Strike'), { target: { value: '400' } });
        expect(screen.queryByText(/not in the fetched sample/i)).not.toBeInTheDocument();
    });
    it('labels when the chain was fetched', async () => {
        const fetchOptionChain = vi.fn().mockResolvedValue(chainOk);
        renderOptionTicket(fetchOptionChain);
        await act(async () => { fireEvent.click(screen.getByRole('button', { name: /show real chain/i })); });
        expect(await screen.findByText(/chain fetched at/i)).toBeInTheDocument();
    });
    it('never judges a contract against another underlying chain: editing the symbol discards it', async () => {
        const fetchOptionChain = vi.fn().mockResolvedValue(chainOk);
        renderOptionTicket(fetchOptionChain);
        await act(async () => { fireEvent.click(screen.getByRole('button', { name: /show real chain/i })); });
        await screen.findByLabelText(/expiry \(chain\)/i);
        fireEvent.change(screen.getByLabelText(/symbol|ticker/i), { target: { value: 'AAPL' } });
        expect(screen.queryByLabelText(/expiry \(chain\)/i)).not.toBeInTheDocument();
    });
    it('discards a stale chain response that resolves after the symbol changed (no repaint over the new ticket)', async () => {
        let resolveChain!: (r: unknown) => void;
        const fetchOptionChain = vi.fn(() => new Promise((r) => { resolveChain = r; }));
        renderOptionTicket(fetchOptionChain);
        await act(async () => { fireEvent.click(screen.getByRole('button', { name: /show real chain/i })); });
        expect(fetchOptionChain).toHaveBeenCalledWith('MSFT');
        // Símbolo cambia a AAPL con la petición de MSFT aún pendiente.
        fireEvent.change(screen.getByLabelText(/symbol|ticker/i), { target: { value: 'AAPL' } });
        await act(async () => { resolveChain(chainOk); });
        // La respuesta tardía de MSFT no repinta expiry/strike sobre el ticket de AAPL...
        expect(screen.queryByLabelText(/expiry \(chain\)/i)).not.toBeInTheDocument();
        expect(screen.queryByLabelText(/strike \(chain\)/i)).not.toBeInTheDocument();
        // ...y el botón queda libre para pedir la cadena del nuevo símbolo.
        expect(screen.getByRole('button', { name: /show real chain/i })).toBeEnabled();
    });
    it('a stale chain failure after the symbol changed paints no error and frees the button', async () => {
        let rejectChain!: (e: unknown) => void;
        const fetchOptionChain = vi.fn(() => new Promise((_r, j) => { rejectChain = j; }));
        renderOptionTicket(fetchOptionChain);
        await act(async () => { fireEvent.click(screen.getByRole('button', { name: /show real chain/i })); });
        fireEvent.change(screen.getByLabelText(/symbol|ticker/i), { target: { value: 'AAPL' } });
        await act(async () => { rejectChain(new Error('late network failure')); });
        expect(screen.queryByText(/not responding right now/i)).not.toBeInTheDocument();
        expect(screen.queryByLabelText(/expiry \(chain\)/i)).not.toBeInTheDocument();
        expect(screen.getByRole('button', { name: /show real chain/i })).toBeEnabled();
    });
    it('a chain whose underlying does not match the symbol never renders its selects', async () => {
        const mismatched = { ...chainOk, underlying: 'AAPL' }; // respuesta de otro subyacente
        const fetchOptionChain = vi.fn().mockResolvedValue(mismatched);
        renderOptionTicket(fetchOptionChain);
        await act(async () => { fireEvent.click(screen.getByRole('button', { name: /show real chain/i })); });
        expect(screen.queryByLabelText(/expiry \(chain\)/i)).not.toBeInTheDocument();
        expect(screen.getByText(/not responding right now/i)).toBeInTheDocument();
    });
    it('a strike listed only as call is not offered nor validated as put (per-side presence)', async () => {
        const asymChain = {
            ...chainOk,
            expiries: [
                { expiry: '2026-12-18', strikes: [
                    { strike: 400, call: { price: 16.1, time: '2026-11-17T15:47:12' } }, // put AUSENTE: no listado
                ] },
            ],
        };
        const fetchOptionChain = vi.fn().mockResolvedValue(asymChain);
        renderOptionTicket(fetchOptionChain);
        await act(async () => { fireEvent.click(screen.getByRole('button', { name: /show real chain/i })); });
        const expirySelect = await screen.findByLabelText(/expiry \(chain\)/i);
        fireEvent.change(expirySelect, { target: { value: '2026-12-18' } });
        // Con Call el strike 400 se ofrece; al pasar a Put desaparece del select...
        const strikeSelect = screen.getByLabelText(/strike \(chain\)/i);
        expect(strikeSelect.querySelector('option[value="400"]')).not.toBeNull();
        fireEvent.click(screen.getByRole('button', { name: 'Put' }));
        expect(strikeSelect.querySelector('option[value="400"]')).toBeNull();
        // ...y si se escribe a mano, el aviso es "no listado", nunca "sin operacion".
        fireEvent.change(screen.getByLabelText('Strike'), { target: { value: '400' } });
        expect(screen.getByText(/not in the fetched sample/i)).toBeInTheDocument();
        expect(screen.queryByText(/no recorded trade in this chain/i)).not.toBeInTheDocument();
        // De vuelta a Call: listado de verdad y con su referencia.
        fireEvent.click(screen.getByRole('button', { name: 'Call' }));
        expect(screen.queryByText(/not in the fetched sample/i)).not.toBeInTheDocument();
        expect(screen.getByText(/last delayed trade: 16.1 USD/i)).toBeInTheDocument();
    });
    it('a rejected fetch (throw) degrades to the same honest note', async () => {
        const fetchOptionChain = vi.fn().mockRejectedValue(new Error('network'));
        renderOptionTicket(fetchOptionChain);
        await act(async () => { fireEvent.click(screen.getByRole('button', { name: /show real chain/i })); });
        expect(await screen.findByText(/not responding right now/i)).toBeInTheDocument();
    });
    it('without the chain action wired, the picker is not offered', () => {
        render(<LocaleProvider locale="en"><OrderTicket submitFill={vi.fn()} /></LocaleProvider>);
        fireEvent.click(screen.getByRole('button', { name: /option/i }));
        expect(screen.queryByRole('button', { name: /show real chain/i })).not.toBeInTheDocument();
    });
});

describe.each(['stock', 'fx'] as const)('%s feedback and idempotency', kind => {
    it.each([['filled', null, false], ['rejected', 'Insufficient cash', false], ['duplicate', 'Insufficient cash', false], ['duplicate', null, true]] as const)('%s reason=%s keeps id=%s for the next attempt', async (outcome, reason, keepsId) => {
        const submit = vi.fn().mockResolvedValue(result(outcome, reason)); const ui = setup(kind, submit); ui.fill(); await ui.send();
        const first = submit.mock.calls[0][0].clientOrderId;
        expect(screen.getByRole(outcome === 'rejected' ? 'alert' : 'status')).not.toBeEmptyDOMElement();
        ui.fill(); await ui.send(); const second = submit.mock.calls[1][0].clientOrderId;
        expect(second === first).toBe(keepsId);
        expect(refresh.mock.calls.length).toBe(outcome === 'filled' ? 2 : 0);
    });
    it('keeps the unknown-outcome id across an error, preserves fields and only clears the error at resubmit', async () => {
        const submit = vi.fn().mockResolvedValueOnce({ ok: false, error: 'Connection lost' }).mockResolvedValue(result('filled'));
        const ui = setup(kind, submit); ui.fill(); await ui.send();
        expect(screen.getByRole('alert')).toHaveTextContent('Connection lost'); ui.field(kind === 'stock' ? 'quantity' : 'amount', '3');
        expect(screen.getByRole('alert')).toHaveTextContent('Connection lost'); await ui.send();
        expect(submit.mock.calls[1][0].clientOrderId).toBe(submit.mock.calls[0][0].clientOrderId);
        expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    });
    it('disables submit while the action is pending and releases it after a resolved failure', async () => {
        let resolve!: (r: SubmitResult) => void; const submit = vi.fn(() => new Promise<SubmitResult>(r => { resolve = r; }));
        const ui = setup(kind, submit); ui.fill(); fireEvent.submit(ui.form);
        expect(ui.form.querySelector('button[type="submit"]')).toBeDisabled();
        await act(async () => { resolve({ ok: false, error: 'offline' }); });
        expect(ui.form.querySelector('button[type="submit"]')).toBeEnabled();
    });
    it('keeps an unwired ticket disabled', () => {
        const ui = setup(kind, undefined, true); expect(ui.form.querySelector('button[type="submit"]')).toBeDisabled();
    });
});

describe('manual FX conversion', () => {
    it('reverses currencies without guessing a rate and submits explicit amounts', async () => {
        const ui = setup('fx'); ui.fill(); fireEvent.click(screen.getByRole('button', { name: 'USD' })); await ui.send();
        expect(ui.submit).toHaveBeenCalledWith(expect.objectContaining({ from: 'USD', to: 'EUR', amount: 100.5, rate: 1.1, executedAt: Date.UTC(2026, 0, 1, 10) }));
        expect(ui.form.querySelector('[id$="-amount"]')).toHaveValue(''); expect(ui.form.querySelector('[id$="-rate"]')).toHaveValue('');
    });
    it.each([['amount', 'bad', /amount/i], ['amount', '0', /greater than zero/i], ['rate', 'bad', /rate/i], ['rate', '-1', /greater than zero/i], ['executed', '', /date/i], ['executed', '2099-01-01T00:00', /future/i]])('blocks invalid %s=%s', async (field, value, message) => {
        const ui = setup('fx'); ui.fill(); ui.field(field, value); await ui.send(); expect(ui.submit).not.toHaveBeenCalled(); expect(screen.getByRole('alert')).toHaveTextContent(message);
    });
});
