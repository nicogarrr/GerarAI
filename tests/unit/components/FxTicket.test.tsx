import { act, fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { formatMoney } from '@/lib/format';
import type { DemoStateView, SubmitFx, SubmitResult } from '@/components/paper-trading/submit';

const mocks = vi.hoisted(() => ({ refresh: vi.fn() }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ refresh: mocks.refresh }) }));

import { FxTicket } from '@/components/paper-trading/FxTicket';

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
async function flush() {
    await act(async () => {});
}

function setup(submitFx: SubmitFx = vi.fn<SubmitFx>().mockResolvedValue(filled())) {
    render(<FxTicket submitFx={submitFx} />);
    const form = screen.getByRole('form', { name: 'Conversión de divisa simulada' });
    return { submitFx, form };
}

type Basics = { amount?: string; rate?: string };
function fillBasics(patch: Basics = {}) {
    const { amount = '1000', rate = '1,12' } = patch;
    fireEvent.change(screen.getByLabelText('Importe (EUR)'), { target: { value: amount } });
    fireEvent.change(screen.getByLabelText(/^Tipo: 1 EUR/), { target: { value: rate } });
}
async function submitForm(form: HTMLElement) {
    fireEvent.submit(form);
    await flush();
}

describe('FxTicket (conversión EUR ⇄ USD simulada)', () => {
    beforeEach(() => {
        mocks.refresh.mockClear();
    });

    it('muestra lo que recibirías con el tipo introducido antes de registrar', () => {
        setup();
        fillBasics({ amount: '1000', rate: '1,12' });
        const hint = screen.getByText(/Conversión simulada con el tipo que introduces/);
        expect(hint).toHaveTextContent(norm(`Recibirías ${formatMoney(1120, 'USD')}`));
    });

    it('explica que la demo no consulta el mercado', () => {
        setup();
        expect(screen.getByText(/la demo no consulta el mercado/)).toBeInTheDocument();
    });

    it('al cambiar el origen a USD se invierten etiquetas y divisa recibida', async () => {
        const submitFx = vi.fn<SubmitFx>().mockResolvedValue(filled());
        const { form } = setup(submitFx);
        fireEvent.click(screen.getByRole('button', { name: 'USD' }));
        expect(screen.getByLabelText('Importe (USD)')).toBeInTheDocument();
        fireEvent.change(screen.getByLabelText('Importe (USD)'), { target: { value: '100' } });
        fireEvent.change(screen.getByLabelText(/^Tipo: 1 USD/), { target: { value: '0,89' } });
        const hint = screen.getByText(/Conversión simulada con el tipo que introduces/);
        expect(hint).toHaveTextContent(norm(`Recibirías ${formatMoney(89, 'EUR')}`));
        await submitForm(form);
        expect(submitFx.mock.calls[0][0]).toMatchObject({ from: 'USD', to: 'EUR', amount: 100, rate: 0.89 });
    });

    it('un envío correcto registra la conversión con coma decimal, avisa y limpia los campos', async () => {
        const submitFx = vi.fn<SubmitFx>().mockResolvedValue(filled());
        const { form } = setup(submitFx);
        fillBasics();
        await submitForm(form);
        expect(submitFx).toHaveBeenCalledTimes(1);
        const payload = submitFx.mock.calls[0][0];
        expect(payload).toMatchObject({ from: 'EUR', to: 'USD', amount: 1000, rate: 1.12 });
        expect(typeof payload.clientOrderId).toBe('string');
        expect(Number.isFinite(payload.executedAt)).toBe(true);
        expect(screen.getByRole('status')).toHaveTextContent('Conversión registrada en la cuenta demo.');
        expect((screen.getByLabelText('Importe (EUR)') as HTMLInputElement).value).toBe('');
        expect((screen.getByLabelText(/^Tipo: 1 EUR/) as HTMLInputElement).value).toBe('');
        expect(mocks.refresh).toHaveBeenCalled();
    });

    const validationCases: [string, Basics, string][] = [
        ['importe no numérico', { amount: 'abc' }, 'El importe no es un número válido'],
        ['importe con miles y decimales (ambiguo)', { amount: '1.234,56' }, 'El importe no es un número válido'],
        ['importe cero', { amount: '0' }, 'Indica un importe mayor que cero.'],
        ['tipo no numérico', { rate: 'abc' }, 'El tipo de cambio no es un número válido'],
        ['tipo cero', { rate: '0' }, 'Indica el tipo de cambio (simulado) mayor que cero.'],
    ];
    it.each(validationCases)('valida en local sin llamar al servidor: %s', async (_name, patch, fragment) => {
        const submitFx = vi.fn<SubmitFx>();
        const { form } = setup(submitFx);
        fillBasics(patch);
        await submitForm(form);
        expect(screen.getByRole('alert')).toHaveTextContent(fragment);
        expect(submitFx).not.toHaveBeenCalled();
    });

    it('rechaza una fecha de conversión futura', async () => {
        const submitFx = vi.fn<SubmitFx>();
        const { form } = setup(submitFx);
        fillBasics();
        fireEvent.change(screen.getByLabelText('Fecha'), { target: { value: localInputValue(inDays(2)) } });
        await submitForm(form);
        expect(screen.getByRole('alert')).toHaveTextContent('La fecha de la conversión no puede ser futura.');
        expect(submitFx).not.toHaveBeenCalled();
    });

    it('sin fecha pide la fecha de la conversión', async () => {
        const submitFx = vi.fn<SubmitFx>();
        const { form } = setup(submitFx);
        fillBasics();
        fireEvent.change(screen.getByLabelText('Fecha'), { target: { value: '' } });
        await submitForm(form);
        expect(screen.getByRole('alert')).toHaveTextContent('Indica la fecha de la conversión.');
        expect(submitFx).not.toHaveBeenCalled();
    });

    it('un rechazo confirmado se muestra con su motivo', async () => {
        const submitFx = vi.fn<SubmitFx>().mockResolvedValue({ ok: true, outcome: 'rejected', reason: 'saldo EUR insuficiente', state: stateView() });
        const { form } = setup(submitFx);
        fillBasics();
        await submitForm(form);
        expect(screen.getByRole('alert')).toHaveTextContent('Conversión rechazada: saldo EUR insuficiente.');
    });

    it('un duplicado de fill no se duplica y conserva el identificador', async () => {
        const submitFx = vi.fn<SubmitFx>().mockResolvedValue({ ok: true, outcome: 'duplicate', reason: null, state: stateView() });
        const { form } = setup(submitFx);
        fillBasics();
        await submitForm(form);
        expect(screen.getByText('Ya estaba registrada (mismo identificador): no se duplicó.')).toBeInTheDocument();
        await submitForm(form);
        expect(submitFx.mock.calls[0][0].clientOrderId).toBe(submitFx.mock.calls[1][0].clientOrderId);
    });

    it('un duplicado de rechazo se explica y el reenvío cuenta como operación nueva', async () => {
        const submitFx = vi.fn<SubmitFx>().mockResolvedValue({ ok: true, outcome: 'duplicate', reason: 'saldo insuficiente', state: stateView() });
        const { form } = setup(submitFx);
        fillBasics();
        await submitForm(form);
        expect(screen.getByText(/Ya consta como rechazada con ese identificador: saldo insuficiente/)).toBeInTheDocument();
        await submitForm(form);
        expect(submitFx.mock.calls[0][0].clientOrderId).not.toBe(submitFx.mock.calls[1][0].clientOrderId);
    });

    it('un fallo de red conserva el clientOrderId para un reintento idempotente', async () => {
        const submitFx = vi.fn<SubmitFx>().mockResolvedValue({ ok: false, error: 'sin conexión con el servidor' });
        const { form } = setup(submitFx);
        fillBasics();
        await submitForm(form);
        expect(screen.getByRole('alert')).toHaveTextContent('sin conexión con el servidor');
        await submitForm(form);
        expect(submitFx).toHaveBeenCalledTimes(2);
        expect(submitFx.mock.calls[0][0].clientOrderId).toBe(submitFx.mock.calls[1][0].clientOrderId);
    });

    it('tras registrar, el siguiente envío lleva identificador nuevo', async () => {
        const submitFx = vi.fn<SubmitFx>().mockResolvedValue(filled());
        const { form } = setup(submitFx);
        fillBasics();
        await submitForm(form);
        fillBasics();
        await submitForm(form);
        expect(submitFx.mock.calls[0][0].clientOrderId).not.toBe(submitFx.mock.calls[1][0].clientOrderId);
    });

    it('con el registro desconectado el botón queda deshabilitado', () => {
        render(<FxTicket submitFx={vi.fn<SubmitFx>()} disabled />);
        expect(screen.getByRole('button', { name: 'Registrar conversión simulada' })).toBeDisabled();
    });
});
