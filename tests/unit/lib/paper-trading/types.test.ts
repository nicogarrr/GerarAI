// @vitest-environment node
import { describe, expect, it } from 'vitest';
import { instrumentKey, parseOptionKey, toFill, type Instrument, type OptionContract } from '@/lib/paper-trading/types';

const accion: Instrument = { kind: 'accion', symbol: 'san', name: 'Banco Santander' };
const contract: OptionContract = {
    underlying: 'aapl', callPut: 'call', strike: 200, expiry: '2026-12-18',
    multiplier: 100, deliverable: 'acciones', adjusted: false,
};
const opcion: Instrument = { kind: 'opcion', contract, name: 'AAPL call' };

const baseFill = {
    instrument: accion, side: 'buy' as const, openClose: 'open' as const,
    quantity: 10, price: 4, currency: 'EUR' as const, fee: 0,
    executedAt: 1_700_000_000_000, clientOrderId: 'ord-1',
};

describe('instrumentKey', () => {
    it('normaliza acciones a mayúsculas con prefijo A:', () => {
        expect(instrumentKey(accion)).toBe('A:SAN');
    });
    it('incluye el contrato completo en opciones (dos strikes distintos no colisionan)', () => {
        expect(instrumentKey(opcion)).toBe('O:AAPL:2026-12-18:call:200:100');
        const otro: Instrument = { kind: 'opcion', contract: { ...contract, strike: 210 }, name: '' };
        expect(instrumentKey(otro)).not.toBe(instrumentKey(opcion));
    });
});

describe('parseOptionKey', () => {
    it('recupera el contrato de una clave generada por instrumentKey', () => {
        expect(parseOptionKey(instrumentKey(opcion))).toEqual({
            underlying: 'AAPL', expiry: '2026-12-18', callPut: 'call', strike: 200, multiplier: 100,
        });
    });
    it.each([
        ['clave de acción', 'A:SAN'],
        ['prefijo sin partes', 'O:AAPL'],
        ['demasiadas partes', 'O:AAPL:2026-12-18:call:200:100:extra'],
        ['subyacente vacío', 'O::2026-12-18:call:200:100'],
        ['callPut inválido', 'O:AAPL:2026-12-18:straddle:200:100'],
        ['expiry sin formato fecha', 'O:AAPL:18-12-2026:call:200:100'],
        ['strike no positivo', 'O:AAPL:2026-12-18:call:0:100'],
        ['strike no numérico', 'O:AAPL:2026-12-18:call:abc:100'],
        ['multiplicador no estándar', 'O:AAPL:2026-12-18:call:200:10'],
    ])('devuelve null con %s', (_etiqueta, key) => {
        expect(parseOptionKey(key)).toBeNull();
    });
});

describe('toFill', () => {
    it('acepta un fill válido y fija source manual-simulado por defecto', () => {
        const fill = toFill(baseFill);
        expect(fill).not.toBeNull();
        expect(fill!.source).toBe('manual-simulado');
    });
    it('respeta un source explícito', () => {
        expect(toFill({ ...baseFill, source: 'manual-simulado' as const })!.source).toBe('manual-simulado');
    });
    it.each([
        ['precio 0', { price: 0 }],
        ['precio negativo', { price: -1 }],
        ['precio NaN', { price: NaN }],
        ['precio infinito', { price: Infinity }],
        ['cantidad no entera', { quantity: 1.5 }],
        ['cantidad 0', { quantity: 0 }],
        ['comisión negativa', { fee: -0.01 }],
        ['comisión NaN', { fee: NaN }],
        ['executedAt 0', { executedAt: 0 }],
        ['executedAt negativo', { executedAt: -5 }],
        ['sin clientOrderId', { clientOrderId: '' }],
    ])('rechaza %s', (_etiqueta, patch) => {
        expect(toFill({ ...baseFill, ...patch })).toBeNull();
    });
    it('rechaza una opción sin contrato (documento corrupto en runtime)', () => {
        const roto = { kind: 'opcion', contract: null, name: 'x' } as unknown as Instrument;
        expect(toFill({ ...baseFill, instrument: roto })).toBeNull();
    });
    it('rechaza contratos ajustados por corporativas (fase 1)', () => {
        const ajustada: Instrument = { kind: 'opcion', contract: { ...contract, adjusted: true }, name: '' };
        expect(toFill({ ...baseFill, instrument: ajustada })).toBeNull();
    });
    it('rechaza multiplicador no estándar y strike/expiry inválidos en opciones', () => {
        const mult: Instrument = { kind: 'opcion', contract: { ...contract, multiplier: 10 }, name: '' };
        expect(toFill({ ...baseFill, instrument: mult })).toBeNull();
        const strike: Instrument = { kind: 'opcion', contract: { ...contract, strike: 0 }, name: '' };
        expect(toFill({ ...baseFill, instrument: strike })).toBeNull();
        const expiry: Instrument = { kind: 'opcion', contract: { ...contract, expiry: '2026-2-8' }, name: '' };
        expect(toFill({ ...baseFill, instrument: expiry })).toBeNull();
    });
});
