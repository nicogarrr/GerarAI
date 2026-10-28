import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { formatMoney } from '@/lib/format';
import type { DemoStateView, SubmitFill, SubmitResult } from '@/components/paper-trading/submit';

const mocks = vi.hoisted(() => ({
    refresh: vi.fn(),
    searchStocksWithStatus: vi.fn(),
}));
vi.mock('next/navigation', () => ({ useRouter: () => ({ refresh: mocks.refresh }) }));
vi.mock('@/lib/actions/finnhub.actions', () => ({
    searchStocksWithStatus: (q: string) => mocks.searchStocksWithStatus(q),
}));

import { OrderTicket } from '@/components/paper-trading/OrderTicket';

function stateView(): DemoStateView {
    return { cashEUR: 100_000, cashUSD: 0, realizedEUR: 0, realizedUSD: 0, positions: [], violations: [], notices: [] };
}
const filled = (): SubmitResult => ({ ok: true, outcome: 'filled', reason: null, state: stateView() });
// formatMoney mete U+00A0 antes del símbolo; toHaveTextContent solo normaliza el DOM.
const norm = (s: string) => s.replace(/\u00a0/g, ' ');

function localInputValue(date: Date): string {
    return new Date(date.getTime() - date.getTimezoneOffset() * 60_000).toISOString().slice(0, 16);
}
function inDays(days: number): Date {
    return new Date(Date.now() + days * 86_400_000);
}
function isoDate(date: Date): string {
    return date.toISOString().slice(0, 10);
}
async function flush() {
    await act(async () => {});
}

function setup(submitFill: SubmitFill = vi.fn<SubmitFill>().mockResolvedValue(filled())) {
    render(<OrderTicket submitFill={submitFill} />);
    const form = screen.getByRole('form', { name: 'Registrar operación simulada' });
    return { submitFill, form };
}

type Basics = { symbol?: string; name?: string; quantity?: string; price?: string };
function fillBasics(patch: Basics = {}) {
    const { symbol = 'ASTS', name = 'AST SpaceMobile', quantity = '10', price = '40,50' } = patch;
    fireEvent.change(screen.getByLabelText('Símbolo'), { target: { value: symbol } });
    fireEvent.change(screen.getByLabelText('Nombre'), { target: { value: name } });
    fireEvent.change(screen.getByLabelText('Cantidad'), { target: { value: quantity } });
    fireEvent.change(screen.getByLabelText('Precio por acción'), { target: { value: price } });
}
function fillOptionBasics(patch: Basics & { strike?: string; expiry?: string } = {}) {
    const { symbol = 'AAPL', name = 'Apple Inc', quantity = '2', price = '1,5', strike = '200', expiry = isoDate(inDays(30)) } = patch;
    fireEvent.change(screen.getByLabelText('Subyacente'), { target: { value: symbol } });
    fireEvent.change(screen.getByLabelText('Nombre'), { target: { value: name } });
    fireEvent.change(screen.getByLabelText('Cantidad'), { target: { value: quantity } });
    fireEvent.change(screen.getByLabelText('Prima por acción'), { target: { value: price } });
    fireEvent.change(screen.getByLabelText('Strike'), { target: { value: strike } });
    fireEvent.change(screen.getByLabelText('Vencimiento'), { target: { value: expiry } });
}

async function submitForm(form: HTMLElement) {
    fireEvent.submit(form);
    await flush();
}

describe('OrderTicket (ticket manual de la cuenta demo)', () => {
    beforeEach(() => {
        mocks.refresh.mockClear();
        mocks.searchStocksWithStatus.mockReset();
    });

    it('explica que el precio lo introduce el usuario y que la comisión es 0 simulada', () => {
        setup();
        expect(screen.getByText(/no es una ejecución de mercado/)).toBeInTheDocument();
        expect(screen.getByText(/Sin comisión en la demo \(0 simulado\)/)).toBeInTheDocument();
    });

    it('una acción válida se envía con símbolo en mayúsculas, fee 0 simulado y refresh al confirmar', async () => {
        const submitFill = vi.fn<SubmitFill>().mockResolvedValue(filled());
        const { form } = setup(submitFill);
        fillBasics({ symbol: 'asts' });
        await submitForm(form);
        expect(submitFill).toHaveBeenCalledTimes(1);
        const payload = submitFill.mock.calls[0][0];
        expect(payload).toMatchObject({
            instrument: { kind: 'accion', symbol: 'ASTS', name: 'AST SpaceMobile' },
            side: 'buy', openClose: 'open', quantity: 10, price: 40.5, currency: 'EUR', fee: 0,
        });
        expect(typeof payload.clientOrderId).toBe('string');
        expect(payload.clientOrderId.length).toBeGreaterThan(0);
        expect(Number.isFinite(payload.executedAt)).toBe(true);
        expect(screen.getByRole('status')).toHaveTextContent('Operación registrada en la cuenta demo.');
        expect((screen.getByLabelText('Cantidad') as HTMLInputElement).value).toBe('');
        expect((screen.getByLabelText('Precio por acción') as HTMLInputElement).value).toBe('');
        expect(mocks.refresh).toHaveBeenCalled();
    });

    const validationCases: [string, Basics, string][] = [
        ['sin símbolo', { symbol: '' }, 'Indica el símbolo.'],
        ['sin nombre', { name: '' }, 'Indica el nombre (o elige la empresa en el buscador).'],
        ['cantidad no numérica', { quantity: 'abc' }, 'La cantidad no es un número válido'],
        ['cantidad con miles y decimales (ambigua)', { quantity: '1.234,56' }, 'La cantidad no es un número válido'],
        ['cantidad no entera', { quantity: '10,5' }, 'La cantidad debe ser un entero mayor que cero.'],
        ['precio no numérico', { price: 'abc' }, 'El precio no es un número válido'],
        ['precio cero', { price: '0' }, 'El precio debe ser mayor que cero.'],
    ];
    it.each(validationCases)('valida en local sin llamar al servidor: %s', async (_name, patch, fragment) => {
        const submitFill = vi.fn<SubmitFill>();
        const { form } = setup(submitFill);
        fillBasics(patch);
        await submitForm(form);
        expect(screen.getByRole('alert')).toHaveTextContent(fragment);
        expect(submitFill).not.toHaveBeenCalled();
    });

    it('rechaza una fecha de ejecución futura', async () => {
        const submitFill = vi.fn<SubmitFill>();
        const { form } = setup(submitFill);
        fillBasics();
        fireEvent.change(screen.getByLabelText('Fecha de ejecución'), { target: { value: localInputValue(inDays(2)) } });
        await submitForm(form);
        expect(screen.getByRole('alert')).toHaveTextContent('La fecha de ejecución no puede ser futura.');
        expect(submitFill).not.toHaveBeenCalled();
    });

    it('el error de validación desaparece en cuanto se corrige el campo', async () => {
        const { form } = setup();
        fillBasics({ price: '0' });
        await submitForm(form);
        expect(screen.getByRole('alert')).toHaveTextContent('El precio debe ser mayor que cero.');
        fireEvent.change(screen.getByLabelText('Precio por acción'), { target: { value: '41' } });
        expect(screen.queryByRole('alert')).toBeNull();
    });

    it('el resumen muestra el coste antes de registrar y distingue compra de venta', () => {
        setup();
        fillBasics({ quantity: '10', price: '40,50' });
        const summary = () => screen.getByLabelText('Resumen de la operación antes de registrar');
        expect(summary()).toHaveTextContent(norm(`Compra · 10 acciones × ${formatMoney(40.5, 'EUR')}`));
        expect(summary()).toHaveTextContent(norm(`Coste total estimado: ${formatMoney(405, 'EUR')}`));
        fireEvent.click(screen.getByRole('button', { name: 'Venta' }));
        expect(summary()).toHaveTextContent(norm(`Ingreso neto estimado: ${formatMoney(405, 'EUR')}`));
        expect(screen.getByRole('button', { name: 'Registrar venta simulada' })).toBeInTheDocument();
    });

    it('al pasar a opción pide strike y vencimiento y aplica el multiplicador 100 en el resumen', () => {
        setup();
        fireEvent.click(screen.getByRole('button', { name: 'Opción (call/put)' }));
        expect(screen.getByLabelText('Strike')).toBeInTheDocument();
        expect(screen.getByLabelText('Vencimiento')).toBeInTheDocument();
        fillOptionBasics();
        const summary = screen.getByLabelText('Resumen de la operación antes de registrar');
        expect(summary).toHaveTextContent('× 100 (multiplicador)');
        expect(summary).toHaveTextContent(norm(`Coste total estimado: ${formatMoney(300, 'EUR')}`));
        expect(summary).toHaveTextContent('contratos');
    });

    const optionValidationCases: [string, Parameters<typeof fillOptionBasics>[0], string][] = [
        ['strike no numérico', { strike: 'abc' }, 'El strike no es un número válido'],
        ['strike cero', { strike: '0' }, 'El strike debe ser mayor que cero.'],
        ['vencimiento que no es fecha real', { expiry: '2026-02-30' }, 'Indica el vencimiento (fecha del contrato, yyyy-mm-dd real).'],
        ['ejecución posterior al vencimiento', { expiry: isoDate(inDays(-10)) }, 'posterior al vencimiento del contrato'],
    ];
    it.each(optionValidationCases)('valida opciones en local: %s', async (_name, patch, fragment) => {
        const submitFill = vi.fn<SubmitFill>();
        const { form } = setup(submitFill);
        fireEvent.click(screen.getByRole('button', { name: 'Opción (call/put)' }));
        fillOptionBasics(patch);
        await submitForm(form);
        expect(screen.getByRole('alert')).toHaveTextContent(fragment);
        expect(submitFill).not.toHaveBeenCalled();
    });

    it('una opción válida se envía con la identidad completa del contrato', async () => {
        const submitFill = vi.fn<SubmitFill>().mockResolvedValue(filled());
        const { form } = setup(submitFill);
        fireEvent.click(screen.getByRole('button', { name: 'Opción (call/put)' }));
        const expiry = isoDate(inDays(30));
        fillOptionBasics({ expiry });
        fireEvent.click(screen.getByRole('button', { name: 'Put' }));
        fireEvent.click(screen.getByRole('button', { name: 'USD' }));
        await submitForm(form);
        expect(submitFill).toHaveBeenCalledTimes(1);
        expect(submitFill.mock.calls[0][0]).toMatchObject({
            instrument: {
                kind: 'opcion',
                name: 'Apple Inc',
                contract: { underlying: 'AAPL', callPut: 'put', strike: 200, expiry, multiplier: 100, deliverable: 'acciones', adjusted: false },
            },
            side: 'buy', openClose: 'open', quantity: 2, price: 1.5, currency: 'USD', fee: 0,
        });
    });

    it('un rechazo confirmado se muestra y el siguiente intento lleva identificador nuevo', async () => {
        const submitFill = vi.fn<SubmitFill>().mockResolvedValue({ ok: true, outcome: 'rejected', reason: 'fondos insuficientes', state: stateView() });
        const { form } = setup(submitFill);
        fillBasics();
        await submitForm(form);
        expect(screen.getByRole('alert')).toHaveTextContent('Orden rechazada: fondos insuficientes.');
        await submitForm(form);
        expect(submitFill.mock.calls[0][0].clientOrderId).not.toBe(submitFill.mock.calls[1][0].clientOrderId);
    });

    it('un duplicado de fill no se duplica y conserva el identificador (reintento seguro)', async () => {
        const submitFill = vi.fn<SubmitFill>().mockResolvedValue({ ok: true, outcome: 'duplicate', reason: null, state: stateView() });
        const { form } = setup(submitFill);
        fillBasics();
        await submitForm(form);
        expect(screen.getByText('Ya estaba registrada (mismo identificador de orden): no se duplicó.')).toBeInTheDocument();
        await submitForm(form);
        expect(submitFill.mock.calls[0][0].clientOrderId).toBe(submitFill.mock.calls[1][0].clientOrderId);
    });

    it('un duplicado de rechazo se explica con el motivo y el reenvío cuenta como operación nueva', async () => {
        const submitFill = vi.fn<SubmitFill>().mockResolvedValue({ ok: true, outcome: 'duplicate', reason: 'fondos insuficientes', state: stateView() });
        const { form } = setup(submitFill);
        fillBasics();
        await submitForm(form);
        expect(screen.getByText(/Ya consta como rechazada con ese identificador: fondos insuficientes/)).toBeInTheDocument();
        await submitForm(form);
        expect(submitFill.mock.calls[0][0].clientOrderId).not.toBe(submitFill.mock.calls[1][0].clientOrderId);
    });

    it('un fallo de red conserva el clientOrderId: el reintento no puede crear una segunda orden', async () => {
        const submitFill = vi.fn<SubmitFill>().mockResolvedValue({ ok: false, error: 'sin conexión con el servidor' });
        const { form } = setup(submitFill);
        fillBasics();
        await submitForm(form);
        expect(screen.getByRole('alert')).toHaveTextContent('sin conexión con el servidor');
        await submitForm(form);
        expect(submitFill).toHaveBeenCalledTimes(2);
        expect(submitFill.mock.calls[0][0].clientOrderId).toBe(submitFill.mock.calls[1][0].clientOrderId);
    });

    it('tras un fill confirmado el siguiente envío lleva identificador nuevo', async () => {
        const submitFill = vi.fn<SubmitFill>().mockResolvedValue(filled());
        const { form } = setup(submitFill);
        fillBasics();
        await submitForm(form);
        fillBasics();
        await submitForm(form);
        expect(submitFill.mock.calls[0][0].clientOrderId).not.toBe(submitFill.mock.calls[1][0].clientOrderId);
    });

    it('mientras registra, el botón queda deshabilitado y avisa', async () => {
        let release: (result: SubmitResult) => void = () => {};
        const submitFill = vi.fn<SubmitFill>().mockImplementation(
            () => new Promise<SubmitResult>((resolve) => { release = resolve; }),
        );
        const { form } = setup(submitFill);
        fillBasics();
        fireEvent.submit(form);
        expect(screen.getByRole('button', { name: 'Registrando…' })).toBeDisabled();
        release(filled());
        await flush();
        expect(screen.getByRole('button', { name: 'Registrar compra simulada' })).toBeEnabled();
    });

    it('con el registro desconectado el botón queda deshabilitado', () => {
        render(<OrderTicket submitFill={vi.fn<SubmitFill>()} disabled />);
        expect(screen.getByRole('button', { name: 'Registrar compra simulada' })).toBeDisabled();
    });

    describe('buscador guiado', () => {
        beforeEach(() => vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] }));
        afterEach(() => vi.useRealTimers());

        it('elegir una empresa rellena símbolo y nombre; editar el símbolo después limpia el nombre', async () => {
            // jsdom no tiene layout: todos los rect son 0 y inputAboveViewport
            // (0 <= 0) cerraría la lista al abrirla. Geometría mínima para que
            // el desplegable pueda abrirse (la geometría real se prueba en e2e).
            vi.spyOn(Element.prototype, 'getBoundingClientRect').mockReturnValue({
                bottom: 100, top: 50, left: 0, right: 300, width: 300, height: 40, x: 0, y: 50, toJSON: () => ({}),
            } as DOMRect);
            mocks.searchStocksWithStatus.mockResolvedValue({
                status: 'ok',
                stocks: [{ symbol: 'ASTS', name: 'AST SpaceMobile', exchange: 'XNAS', type: 'Common Stock', isInWatchlist: false }],
            });
            setup();
            const input = screen.getByLabelText('Buscar acción por nombre o ticker');
            act(() => (input as HTMLInputElement).focus());
            fireEvent.change(input, { target: { value: 'AST' } });
            await act(async () => { await vi.advanceTimersByTimeAsync(300); });
            await act(async () => { await vi.advanceTimersByTimeAsync(0); });
            fireEvent.click(screen.getByRole('option', { name: /ASTS/ }));
            expect((screen.getByLabelText('Símbolo') as HTMLInputElement).value).toBe('ASTS');
            expect((screen.getByLabelText('Nombre') as HTMLInputElement).value).toBe('AST SpaceMobile');
            fireEvent.change(screen.getByLabelText('Símbolo'), { target: { value: 'ASTX' } });
            expect((screen.getByLabelText('Nombre') as HTMLInputElement).value).toBe('');
        });
    });
});
