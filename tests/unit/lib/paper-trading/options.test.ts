// @vitest-environment node
import { describe, expect, it } from 'vitest';
import {
    buildOptionFill, expirationState, expiryBadge, expiryOutcome, intrinsicValue,
    isRealDate, newYorkDate, optionCashDelta, premiumTotal, validateOptionContract,
    type OptionOrderInput,
} from '@/lib/paper-trading/options';
import type { OptionContract } from '@/lib/paper-trading/types';

const contract: OptionContract = {
    underlying: 'AAPL', callPut: 'call', strike: 200, expiry: '2026-12-18',
    multiplier: 100, deliverable: 'acciones', adjusted: false,
};

// 2026-06-15 12:00 UTC: en Nueva York es 15 de junio (EDT, UTC-4).
const JUN15_UC = Date.UTC(2026, 5, 15, 12);

describe('newYorkDate', () => {
    it('usa la fecha civil de Nueva York, no la UTC: 01:00 UTC de verano sigue siendo ayer allí', () => {
        // 2026-06-15 01:00 UTC = 2026-06-14 21:00 EDT.
        expect(newYorkDate(Date.UTC(2026, 5, 15, 1))).toBe('2026-06-14');
    });
    it('devuelve formato yyyy-mm-dd', () => {
        expect(newYorkDate(JUN15_UC)).toBe('2026-06-15');
    });
});

describe('isRealDate', () => {
    it.each(['2026-06-15', '2024-02-29'])('acepta fecha real %s', (iso) => {
        expect(isRealDate(iso)).toBe(true);
    });
    it.each([
        ['mes 13', '2026-13-01'],
        ['día 45', '2026-01-45'],
        ['30 de febrero', '2026-02-30'],
        ['29 de febrero en año no bisiesto', '2026-02-29'],
        ['formato corto', '2026-6-5'],
        ['texto', 'no-date-xx'],
    ])('rechaza %s (%s)', (_e, iso) => {
        expect(isRealDate(iso)).toBe(false);
    });
});

describe('validateOptionContract', () => {
    it('acepta un contrato estándar válido', () => {
        expect(validateOptionContract(contract)).toEqual({ ok: true, value: contract });
    });
    it('rechaza contrato ausente', () => {
        const r = validateOptionContract(null as unknown as OptionContract);
        expect(r).toMatchObject({ ok: false, reason: 'Contrato de opción ausente.' });
    });
    it.each([
        ['subyacente vacío', { underlying: '' }, 'Subyacente inválido.'],
        ['subyacente que empieza por dígito', { underlying: '1AAPL' }, 'Subyacente inválido.'],
        ['tipo straddle', { callPut: 'straddle' as never }, 'Tipo debe ser call o put.'],
        ['strike 0', { strike: 0 }, 'Strike debe ser un número mayor que 0.'],
        ['strike NaN', { strike: NaN }, 'Strike debe ser un número mayor que 0.'],
        ['vencimiento irreal', { expiry: '2026-13-40' }, 'Vencimiento inválido (se espera yyyy-mm-dd real).'],
        ['entrega en cash', { deliverable: 'cash' as never }, 'Solo se admite entrega de acciones en fase 1.'],
        ['multiplicador mini', { multiplier: 10 }, 'Solo se admiten contratos estándar con multiplicador 100.'],
    ])('rechaza %s', (_e, patch, reason) => {
        expect(validateOptionContract({ ...contract, ...patch })).toEqual({ ok: false, reason });
    });
    it('rechaza contratos ajustados explicando el motivo', () => {
        const r = validateOptionContract({ ...contract, adjusted: true });
        expect(r.ok).toBe(false);
        if (!r.ok) expect(r.reason).toContain('ajustado');
    });
});

describe('expiryBadge / expirationState', () => {
    it('el día del vencimiento es vence-hoy, no vencida', () => {
        expect(expiryBadge('2026-06-15', JUN15_UC)).toBe('vence-hoy');
        expect(expirationState({ ...contract, expiry: '2026-06-15' }, JUN15_UC)).toEqual({ status: 'vigente', daysToExpiry: 0 });
    });
    it('antes del vencimiento está vigente con los días que faltan', () => {
        expect(expiryBadge('2026-06-20', JUN15_UC)).toBe('vigente');
        expect(expirationState({ ...contract, expiry: '2026-06-20' }, JUN15_UC).daysToExpiry).toBe(5);
    });
    it('después del vencimiento está vencida con días negativos', () => {
        expect(expiryBadge('2026-06-14', JUN15_UC)).toBe('vencida');
        expect(expirationState({ ...contract, expiry: '2026-06-14' }, JUN15_UC)).toEqual({ status: 'vencido', daysToExpiry: -1 });
    });
});

describe('premiumTotal / optionCashDelta', () => {
    it('prima total = prima por acción x contratos x 100', () => {
        expect(premiumTotal(2.5, 3)).toBe(750);
    });
    it('redondea primas con 4 decimales sin deriva de floats', () => {
        expect(premiumTotal(0.1234, 1)).toBe(12.34);
        expect(premiumTotal(1.005, 2)).toBe(201);
    });
    it('comprar resta prima + comisión; vender suma prima - comisión', () => {
        const base = { price: 2, quantity: 1, fee: 1.5, instrument: { kind: 'opcion' as const, contract, name: '' } };
        expect(optionCashDelta({ ...base, side: 'buy' })).toBe(-201.5);
        expect(optionCashDelta({ ...base, side: 'sell' })).toBe(198.5);
    });
});

describe('buildOptionFill', () => {
    const input: OptionOrderInput = {
        contract, side: 'buy', openClose: 'open', contracts: 1, premium: 2,
        currency: 'USD', fee: 0, executedAt: JUN15_UC, clientOrderId: 'o-1',
        heldContracts: 0, availableCash: 1000,
    };

    it('construye el fill de compra para abrir con el nombre legible del contrato', () => {
        const r = buildOptionFill(input);
        expect(r.ok).toBe(true);
        if (r.ok) {
            expect(r.value.instrument.kind).toBe('opcion');
            expect(r.value.instrument.name).toBe('AAPL 2026-12-18 200 Call');
            expect(r.value).toMatchObject({ side: 'buy', openClose: 'open', quantity: 1, price: 2, source: 'manual-simulado' });
        }
    });

    it('nombra los puts como Put', () => {
        const r = buildOptionFill({ ...input, contract: { ...contract, callPut: 'put' } });
        expect(r.ok && r.value.instrument.name).toBe('AAPL 2026-12-18 200 Put');
    });

    it('admite vender para cerrar dentro de lo abierto', () => {
        const r = buildOptionFill({ ...input, side: 'sell', openClose: 'close', contracts: 1, heldContracts: 2 });
        expect(r.ok).toBe(true);
    });

    it.each([
        ['vender para abrir (corto)', { side: 'sell' as const, openClose: 'open' as const }, 'Fase 1 solo admite comprar para abrir y vender para cerrar'],
        ['comprar para cerrar', { side: 'buy' as const, openClose: 'close' as const }, 'Fase 1 solo admite comprar para abrir y vender para cerrar'],
        ['contratos no enteros', { contracts: 1.5 }, 'Los contratos deben ser un entero mayor que 0.'],
        ['contratos 0', { contracts: 0 }, 'Los contratos deben ser un entero mayor que 0.'],
        ['prima 0', { premium: 0 }, 'La prima debe ser mayor que 0.'],
        ['prima con 5 decimales', { premium: 1.23456 }, 'máximo 4 decimales'],
        ['divisa no soportada', { currency: 'GBP' as never }, 'Divisa no soportada.'],
        ['comisión negativa', { fee: -1 }, 'La comisión no puede ser negativa.'],
        ['executedAt inválido', { executedAt: 0 }, 'Fecha de ejecución inválida.'],
        ['sin clientOrderId', { clientOrderId: '' }, 'Falta clientOrderId.'],
    ])('rechaza %s', (_e, patch, fragmento) => {
        const r = buildOptionFill({ ...input, ...patch });
        expect(r.ok).toBe(false);
        if (!r.ok) expect(r.reason).toContain(fragmento);
    });

    it('rechaza operar un contrato ya vencido en la fecha de ejecución', () => {
        const r = buildOptionFill({ ...input, executedAt: Date.UTC(2027, 0, 10, 12) });
        expect(r.ok).toBe(false);
        if (!r.ok) expect(r.reason).toContain('ya venció');
    });

    it('rechaza cerrar más contratos de los abiertos', () => {
        const r = buildOptionFill({ ...input, side: 'sell', openClose: 'close', contracts: 3, heldContracts: 2 });
        expect(r.ok).toBe(false);
        if (!r.ok) expect(r.reason).toBe('No se pueden cerrar 3 contratos: solo hay 2 abiertos.');
    });

    it('rechaza una compra sin saldo suficiente (sin sobregiro)', () => {
        const r = buildOptionFill({ ...input, contracts: 10, premium: 2, availableCash: 1500 });
        expect(r.ok).toBe(false);
        if (!r.ok) expect(r.reason).toContain('Saldo USD insuficiente: la compra cuesta 2.000,00 y hay 1.500,00');
    });

    it('rechaza un cierre cuya comisión no cabe en el cash tras abonar la prima', () => {
        const r = buildOptionFill({ ...input, side: 'sell', openClose: 'close', contracts: 1, heldContracts: 1, premium: 2, fee: 300, availableCash: 50 });
        expect(r.ok).toBe(false);
        if (!r.ok) expect(r.reason).toContain('supera el efectivo disponible tras el cierre');
    });

    it('propaga el rechazo de un contrato inválido', () => {
        const r = buildOptionFill({ ...input, contract: { ...contract, multiplier: 10 } });
        expect(r.ok).toBe(false);
        if (!r.ok) expect(r.reason).toContain('multiplicador 100');
    });
});

describe('intrinsicValue / expiryOutcome', () => {
    it('call: max(0, precio - strike); put: max(0, strike - precio)', () => {
        expect(intrinsicValue(contract, 250)).toBe(50);
        expect(intrinsicValue(contract, 150)).toBe(0);
        expect(intrinsicValue({ ...contract, callPut: 'put' }, 150)).toBe(50);
        expect(intrinsicValue({ ...contract, callPut: 'put' }, 250)).toBe(0);
    });

    it('un contrato vigente no tiene desenlace', () => {
        expect(expiryOutcome(contract, JUN15_UC, 250)).toEqual({ status: 'vigente' });
    });

    it('vencido sin cierre fechado: pendiente, NUNCA se asume ITM u OTM', () => {
        const r = expiryOutcome(contract, Date.UTC(2027, 0, 10, 12), null);
        expect(r).toMatchObject({ status: 'pendiente-liquidacion', intrinsicPerShare: null });
        if (r.status === 'pendiente-liquidacion') expect(r.reason).toContain('no se asume');
    });

    it('vencido con cierre sin valor intrínseco: sin-valor', () => {
        expect(expiryOutcome(contract, Date.UTC(2027, 0, 10, 12), 150)).toEqual({ status: 'sin-valor', intrinsicPerShare: 0 });
    });

    it('vencido ITM: pendiente de liquidación con el intrínseco calculado', () => {
        const r = expiryOutcome(contract, Date.UTC(2027, 0, 10, 12), 250);
        expect(r).toMatchObject({ status: 'pendiente-liquidacion', intrinsicPerShare: 50 });
    });

    it.each([[0], [-5], [NaN]])('un cierre inválido (%s) se trata como sin dato', (close) => {
        const r = expiryOutcome(contract, Date.UTC(2027, 0, 10, 12), close);
        expect(r).toMatchObject({ status: 'pendiente-liquidacion', intrinsicPerShare: null });
    });
});
