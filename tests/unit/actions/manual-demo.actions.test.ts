import { beforeEach, describe, expect, it, vi } from 'vitest';

const {
    requireAuthenticatedUser, connectToDatabase,
    accountFindOne, accountCreate, accountFindOneAndUpdate,
    tradeFind, tradeFindOne, tradeCreate,
    computeManualDemoAccount, docsToLedger, cacheGetQuote,
} = vi.hoisted(() => ({
    requireAuthenticatedUser: vi.fn<(...args: any[]) => any>(),
    connectToDatabase: vi.fn<(...args: any[]) => any>(),
    accountFindOne: vi.fn<(...args: any[]) => any>(),
    accountCreate: vi.fn<(...args: any[]) => any>(async () => [{}]),
    accountFindOneAndUpdate: vi.fn<(...args: any[]) => any>(),
    tradeFind: vi.fn<(...args: any[]) => any>(),
    tradeFindOne: vi.fn<(...args: any[]) => any>(),
    tradeCreate: vi.fn<(...args: any[]) => any>(async () => [{}]),
    computeManualDemoAccount: vi.fn<(...args: any[]) => any>(),
    docsToLedger: vi.fn<(...args: any[]) => any>(() => ({ entries: [], violations: [] })),
    cacheGetQuote: vi.fn<(...args: any[]) => any>(),
}));

vi.mock('@/lib/auth/require-user', () => ({ requireAuthenticatedUser }));
vi.mock('@/database/mongoose', () => ({ connectToDatabase }));
vi.mock('@/database/models/manual-demo.model', () => ({
    MANUAL_DEMO_STARTING_CASH_EUR: 100000,
    ManualDemoAccount: { findOne: accountFindOne, create: accountCreate, findOneAndUpdate: accountFindOneAndUpdate },
    ManualDemoTrade: { find: tradeFind, findOne: tradeFindOne, create: tradeCreate },
}));
vi.mock('@/lib/paper-trading/accounting', () => ({ computeManualDemoAccount }));
vi.mock('@/lib/paper-trading/ledger-adapter', () => ({ docsToLedger }));
vi.mock('@/lib/market/quote-cache', () => ({
    createQuoteCache: () => ({ getQuote: cacheGetQuote }),
    combineAbortSignals: (s: AbortSignal) => s,
}));
vi.mock('@/lib/market/quote-freshness', () => ({ sanitizeFinnhubQuote: (q: unknown) => q }));

import { instrumentKey } from '@/lib/paper-trading/types';

const chainOf = (result: unknown) => {
    const q = {
        sort: () => q,
        session: () => q,
        then: (resolve: (v: unknown) => unknown, reject?: (e: unknown) => unknown) => Promise.resolve(result).then(resolve, reject),
    };
    return q;
};

let session: { withTransaction: (fn: () => Promise<void>) => Promise<void>; endSession: () => Promise<void> };

const NOW = 1_777_000_000_000; // ms epoch plausible
const order = (over: object = {}) => ({
    clientOrderId: 'orden-de-prueba-1',
    side: 'buy',
    quantity: 10,
    price: 100,
    currency: 'EUR',
    fee: 0,
    executedAt: NOW,
    instrument: { kind: 'accion', symbol: 'aapl', name: 'Apple' },
    ...over,
});
const fxOrder = (over: object = {}) => ({
    clientOrderId: 'fx-de-prueba-0001',
    from: 'EUR', to: 'USD', amount: 100, rate: 1.1, executedAt: NOW, ...over,
});

const stateWith = (cashEUR = 100000, cashUSD = 0, positions: object[] = []) => ({
    cashByCurrency: { EUR: cashEUR, USD: cashUSD },
    realizedPnlByCurrency: { EUR: 0, USD: 0 },
    positions,
    violations: [] as string[],
});

let state = stateWith();

const load = () => import('@/lib/actions/manual-demo.actions');

beforeEach(() => {
    vi.resetModules();
    vi.resetAllMocks();
    vi.spyOn(console, 'error').mockImplementation(() => {});
    vi.spyOn(Date, 'now').mockReturnValue(NOW + 60_000);
    state = stateWith();
    computeManualDemoAccount.mockImplementation(() => state);
    docsToLedger.mockImplementation(() => ({ entries: [], violations: [] }));
    requireAuthenticatedUser.mockResolvedValue({ id: 'user-1' });
    session = { withTransaction: async (fn) => { await fn(); }, endSession: async () => {} };
    connectToDatabase.mockResolvedValue({ startSession: async () => session });
    tradeFind.mockImplementation(() => chainOf([]));
    tradeFindOne.mockImplementation(() => chainOf(null));
    tradeCreate.mockResolvedValue([{}] as never);
    accountFindOne.mockImplementation(() => chainOf({ userId: 'user-1', version: 1, cashEUR: 100000, cashUSD: 0 }));
    accountCreate.mockResolvedValue([{}] as never);
    accountFindOneAndUpdate.mockResolvedValue({ userId: 'user-1', version: 2 });
    delete process.env.FINNHUB_API_KEY;
});

describe('auth primero', () => {
    it('sin sesión -> fallo legible, nunca toca la base de datos', async () => {
        requireAuthenticatedUser.mockRejectedValue(Object.assign(new Error('no auth'), { name: 'AuthenticationError' }));
        const m = await load();
        expect(await m.getManualDemoAccount()).toEqual({ ok: false, message: 'Inicia sesión para usar la cuenta demo.' });
        expect(await m.placeManualOrder(order())).toMatchObject({ ok: false });
        expect(await m.convertManualDemoCurrency(fxOrder())).toMatchObject({ ok: false });
        expect(await m.getManualDemoOrders()).toMatchObject({ ok: false });
        expect(connectToDatabase).not.toHaveBeenCalled();
    });

    it('un error que no es de auth propaga', async () => {
        requireAuthenticatedUser.mockRejectedValue(new Error('caída rara'));
        const m = await load();
        await expect(m.getManualDemoAccount()).rejects.toThrow('caída rara');
    });
});

describe('validación de órdenes (antes de tocar el libro)', () => {
    it.each([
        ['clientOrderId corto', { clientOrderId: 'abc' }, 'clientOrderId'],
        ['side inválido', { side: 'hold' }, 'side'],
        ['cantidad fraccionada', { quantity: 1.5 }, 'quantity'],
        ['cantidad cero', { quantity: 0 }, 'quantity'],
        ['precio cero', { price: 0 }, 'price'],
        ['precio con 5 decimales', { price: 0.12345 }, 'price'],
        ['precio en notación exponencial', { price: 1e21 }, 'price'],
        ['divisa no soportada', { currency: 'GBP' }, 'currency'],
        ['comisión negativa', { fee: -1 }, 'fee'],
        ['comisión con 3 decimales', { fee: 1.005 }, 'fee'],
        ['executedAt en segundos, no ms', { executedAt: 1_700_000_000 }, 'executedAt'],
        ['executedAt futuro', { executedAt: NOW + 10 * 60_000 }, 'executedAt'],
        ['símbolo con caracteres no admitidos', { instrument: { kind: 'accion', symbol: 'AA PL' } }, 'symbol'],
        ['orden que no es objeto', null, 'order'],
    ])('%s -> fallo con campo, sin escribir', async (_name: string, patch: object | null, expectedField: string) => {
        const m = await load();
        const raw = patch === null ? null : order(patch);
        const result = await m.placeManualOrder(raw);
        expect(result).toMatchObject({ ok: false, field: expectedField });
        expect(tradeCreate).not.toHaveBeenCalled();
    });

    it('opción sin contrato completo o sin openClose -> fallo de validación', async () => {
        const m = await load();
        expect(await m.placeManualOrder(order({ instrument: { kind: 'opcion' } }))).toMatchObject({ ok: false, field: 'contract' });
        expect(await m.placeManualOrder(order({ instrument: { kind: 'opcion', contract: { underlying: 'AAPL' } } }))).toMatchObject({ ok: false, field: 'openClose' });
    });

    it('instrument.kind desconocido -> fallo', async () => {
        const m = await load();
        expect(await m.placeManualOrder(order({ instrument: { kind: 'futuro', symbol: 'X' } }))).toMatchObject({ ok: false, field: 'instrument' });
    });
});

describe('validación de conversiones fx', () => {
    it('EUR->EUR crearía dinero ficticio: rechazado', async () => {
        const m = await load();
        expect(await m.convertManualDemoCurrency(fxOrder({ to: 'EUR' }))).toMatchObject({ ok: false, field: 'to' });
        expect(tradeCreate).not.toHaveBeenCalled();
    });

    it('importe con 3 decimales o tipo con 7 -> fallo', async () => {
        const m = await load();
        expect(await m.convertManualDemoCurrency(fxOrder({ amount: 0.001 }))).toMatchObject({ ok: false, field: 'amount' });
        expect(await m.convertManualDemoCurrency(fxOrder({ rate: 1.2345678 }))).toMatchObject({ ok: false, field: 'rate' });
    });
});

describe('placeManualOrder: fills y rechazos con el libro', () => {
    it('compra con saldo -> fill con fillSource manual-simulado y fecha real', async () => {
        const m = await load();
        const result = await m.placeManualOrder(order());
        expect(result).toMatchObject({ ok: true, outcome: 'filled', reason: null });
        const doc = tradeCreate.mock.calls[0][0][0];
        expect(doc).toMatchObject({
            userId: 'user-1', kind: 'accion', symbol: 'AAPL', side: 'buy', openClose: 'open',
            status: 'filled', fillPrice: 100, fee: 0, currency: 'EUR',
            fillSource: 'manual-simulado', rejectReason: null, requestPayload: null,
        });
        expect(doc.executedAt).toEqual(new Date(NOW));
        expect(accountFindOneAndUpdate).toHaveBeenCalledWith(
            { userId: 'user-1', version: 1 },
            expect.objectContaining({ $inc: { version: 1 } }),
            expect.objectContaining({ returnDocument: 'after' }),
        );
    });

    it('saldo insuficiente -> rechazo grabado SIN precio/fecha y con snapshot comparable; la versión no se toca', async () => {
        state = stateWith(500); // compra cuesta 1000
        const m = await load();
        const result = await m.placeManualOrder(order());
        expect(result).toMatchObject({ ok: true, outcome: 'rejected' });
        expect((result as { reason: string }).reason).toContain('Saldo EUR insuficiente');
        // Importes del motivo en es-ES («1.000,00»), nunca toFixed en-US («1000.00»).
        expect((result as { reason: string }).reason).toContain('la compra cuesta 1.000,00 y hay 500,00');
        const doc = tradeCreate.mock.calls[0][0][0];
        expect(doc.status).toBe('rejected');
        expect(doc.fillPrice).toBeNull();
        expect(doc.executedAt).toBeNull();
        expect(doc.fee).toBe(0);
        expect(doc.requestPayload).toMatchObject({ v: 1, kind: 'accion', symbol: 'AAPL', price: 100, executedAtMs: NOW });
        expect(accountFindOneAndUpdate).not.toHaveBeenCalled();
    });

    it('venta de más de lo que hay -> rechazo con la posición real', async () => {
        state = stateWith(100000, 0, [
            { instrumentKey: 'A:AAPL', name: 'Apple', kind: 'accion', currency: 'EUR', quantity: 4, avgCost: 100, realizedPnl: 0 },
        ]);
        const m = await load();
        const result = await m.placeManualOrder(order({ side: 'sell' }));
        expect(result).toMatchObject({ ok: true, outcome: 'rejected' });
        expect((result as { reason: string }).reason).toContain('la posición en EUR es 4');
    });

    it('la comisión de la venta tampoco puede sobregirar la caja', async () => {
        state = stateWith(0, 0, [
            { instrumentKey: 'A:AAPL', name: 'Apple', kind: 'accion', currency: 'EUR', quantity: 10, avgCost: 100, realizedPnl: 0 },
        ]);
        const m = await load();
        // venta 10x100 = 1000 en caja; comisión 1001 no cabe
        const result = await m.placeManualOrder(order({ side: 'sell', fee: 1001 }));
        expect(result).toMatchObject({ ok: true, outcome: 'rejected' });
        expect((result as { reason: string }).reason).toContain('sobregiro');
    });

    it('opción: compra para abrir sin saldo USD -> rechazo del motor de opciones', async () => {
        const m = await load();
        const result = await m.placeManualOrder(order({
            currency: 'USD',
            openClose: 'open',
            price: 2,
            quantity: 1,
            instrument: { kind: 'opcion', contract: { underlying: 'AAPL', expiry: '2027-01-15', strike: 100, callPut: 'call', multiplier: 100, deliverable: 'acciones' } },
        }));
        expect(result).toMatchObject({ ok: true, outcome: 'rejected' });
        expect((result as { reason: string }).reason).toContain('Saldo USD insuficiente');
    });

    it('vender para abrir no existe en fase 1', async () => {
        const m = await load();
        const result = await m.placeManualOrder(order({
            side: 'sell', openClose: 'open', currency: 'USD', price: 2, quantity: 1,
            instrument: { kind: 'opcion', contract: { underlying: 'AAPL', expiry: '2027-01-15', strike: 100, callPut: 'call', multiplier: 100, deliverable: 'acciones' } },
        }));
        expect(result).toMatchObject({ ok: true, outcome: 'rejected' });
        expect((result as { reason: string }).reason).toContain('Fase 1');
    });
});

describe('idempotencia (userId, clientOrderId)', () => {
    const storedFill = {
        clientOrderId: 'orden-de-prueba-1', kind: 'accion', symbol: 'AAPL', name: 'Apple',
        contract: null, side: 'buy', openClose: 'open', quantity: 10, status: 'filled',
        fillPrice: 100, currency: 'EUR', fee: 0, executedAt: new Date(NOW),
        rejectReason: null, createdAt: new Date(NOW), requestPayload: null,
    };

    it('mismo clientOrderId y mismo payload -> duplicate, sin segunda fila', async () => {
        tradeFindOne.mockImplementation(() => chainOf(storedFill));
        const m = await load();
        const result = await m.placeManualOrder(order());
        expect(result).toMatchObject({ ok: true, outcome: 'duplicate', reason: null });
        expect(tradeCreate).not.toHaveBeenCalled();
    });

    it('mismo clientOrderId con OTRO precio -> conflicto explícito, no duplicado', async () => {
        tradeFindOne.mockImplementation(() => chainOf(storedFill));
        const m = await load();
        const result = await m.placeManualOrder(order({ price: 101 }));
        expect(result).toMatchObject({ ok: false, field: 'clientOrderId' });
        expect(tradeCreate).not.toHaveBeenCalled();
    });

    it('rechazo persistido con snapshot: reintento idéntico -> duplicate con el motivo grabado', async () => {
        const storedReject = {
            ...storedFill, status: 'rejected', fillPrice: null, fee: 0, executedAt: null,
            rejectReason: 'Saldo EUR insuficiente.',
            requestPayload: {
                v: 1, kind: 'accion', symbol: 'AAPL', contractKey: null, side: 'buy', openClose: 'open',
                quantity: 10, currency: 'EUR', price: 100, fee: 0, executedAtMs: NOW,
            },
        };
        tradeFindOne.mockImplementation(() => chainOf(storedReject));
        const m = await load();
        const result = await m.placeManualOrder(order());
        expect(result).toMatchObject({ ok: true, outcome: 'duplicate', reason: 'Saldo EUR insuficiente.' });
    });

    it('rechazo LEGACY sin snapshot: solo el subconjunto persistido prueba igualdad', async () => {
        const legacy = { ...storedFill, status: 'rejected', fillPrice: null, executedAt: null, rejectReason: 'antiguo', requestPayload: null };
        tradeFindOne.mockImplementation(() => chainOf(legacy));
        const m = await load();
        expect(await m.placeManualOrder(order())).toMatchObject({ ok: true, outcome: 'duplicate', reason: 'antiguo' });
        // payload distinto en el subconjunto persistido -> conflicto
        expect(await m.placeManualOrder(order({ quantity: 11 }))).toMatchObject({ ok: false, field: 'clientOrderId' });
    });

    it('fx duplicado y fx con payload distinto', async () => {
        const storedFx = {
            clientOrderId: 'fx-de-prueba-0001', kind: 'fx', symbol: 'EURUSD', fxFrom: 'EUR', fxTo: 'USD',
            side: 'buy', openClose: 'open', quantity: 100, status: 'filled', fillPrice: 1.1,
            currency: 'EUR', fee: 0, executedAt: new Date(NOW), rejectReason: null, createdAt: new Date(NOW), requestPayload: null,
        };
        tradeFindOne.mockImplementation(() => chainOf(storedFx));
        const m = await load();
        expect(await m.convertManualDemoCurrency(fxOrder())).toMatchObject({ ok: true, outcome: 'duplicate' });
        expect(await m.convertManualDemoCurrency(fxOrder({ rate: 1.2 }))).toMatchObject({ ok: false, field: 'clientOrderId' });
    });
});

describe('transacción: divergencia temporal y conflictos de versión', () => {
    it('si el rellenado descuadra el libro en su fecha, se aborta y el rechazo se graba aparte', async () => {
        computeManualDemoAccount
            .mockImplementationOnce(() => stateWith())
            .mockImplementationOnce(() => ({ ...stateWith(), violations: ['Venta antes que la compra en el replay'] }))
            .mockImplementation(() => stateWith());
        // duplicateResult no ve nada; recordRejection relee el rechazo persistido con su snapshot
        tradeFindOne.mockImplementationOnce(() => chainOf(null));
        tradeFindOne.mockImplementation(() => chainOf({
            clientOrderId: 'orden-de-prueba-1', kind: 'accion', symbol: 'AAPL', contract: null,
            side: 'buy', openClose: 'open', quantity: 10, status: 'rejected', fillPrice: null,
            currency: 'EUR', fee: 0, executedAt: null, rejectReason: 'La operación no cuadra en su fecha de ejecución',
            createdAt: new Date(NOW),
            requestPayload: {
                v: 1, kind: 'accion', symbol: 'AAPL', contractKey: null, side: 'buy', openClose: 'open',
                quantity: 10, currency: 'EUR', price: 100, fee: 0, executedAtMs: NOW,
            },
        }));
        const m = await load();
        const result = await m.placeManualOrder(order());
        expect(result).toMatchObject({ ok: true, outcome: 'rejected' });
        expect((result as { reason: string }).reason).toContain('no cuadra en su fecha');
        // la caché de saldos NO se actualizó (no hubo fill confirmado)
        expect(accountFindOneAndUpdate).not.toHaveBeenCalled();
    });

    it('conflicto de versión: reintenta y confirma; 3 conflictos -> fallo legible', async () => {
        accountFindOneAndUpdate.mockResolvedValueOnce(null);
        const m = await load();
        expect(await m.placeManualOrder(order())).toMatchObject({ ok: true, outcome: 'filled' });

        accountFindOneAndUpdate.mockResolvedValue(null);
        const result = await m.placeManualOrder(order({ clientOrderId: 'otra-orden-00002' }));
        expect(result).toMatchObject({ ok: false, message: expect.stringContaining('otra orden a la vez') });
    });

    it('despliegue sin transacciones -> fallo declarado, NUNCA escritura sin aislamiento', async () => {
        session.withTransaction = async () => { throw new Error('Transaction numbers are only allowed on a replica set member or mongos'); };
        const m = await load();
        const result = await m.placeManualOrder(order());
        expect(result).toMatchObject({ ok: false, message: expect.stringContaining('sin transacciones') });
    });

    it('carrera con clave duplicada al insertar el fill -> se devuelve lo persistido', async () => {
        tradeCreate.mockRejectedValue({ code: 11000 });
        tradeFindOne.mockImplementation(() => chainOf({
            clientOrderId: 'orden-de-prueba-1', kind: 'accion', symbol: 'AAPL', contract: null,
            side: 'buy', openClose: 'open', quantity: 10, status: 'filled', fillPrice: 100,
            currency: 'EUR', fee: 0, executedAt: new Date(NOW), rejectReason: null,
            createdAt: new Date(NOW), requestPayload: null,
        }));
        const m = await load();
        expect(await m.placeManualOrder(order())).toMatchObject({ ok: true, outcome: 'duplicate' });
    });
});

describe('convertManualDemoCurrency', () => {
    it('EUR->USD con saldo -> fill etiquetado como simulado', async () => {
        const m = await load();
        const result = await m.convertManualDemoCurrency(fxOrder());
        expect(result).toMatchObject({ ok: true, outcome: 'filled' });
        const doc = tradeCreate.mock.calls[0][0][0];
        expect(doc).toMatchObject({
            kind: 'fx', symbol: 'EURUSD', fxFrom: 'EUR', fxTo: 'USD', quantity: 100,
            fillPrice: 1.1, currency: 'EUR', fillSource: 'manual-simulado', status: 'filled',
        });
    });

    it('sin saldo en la divisa origen -> rechazo con el saldo real', async () => {
        state = stateWith(50);
        const m = await load();
        const result = await m.convertManualDemoCurrency(fxOrder());
        expect(result).toMatchObject({ ok: true, outcome: 'rejected' });
        expect((result as { reason: string }).reason).toContain('Saldo EUR insuficiente');
    });
});

describe('getManualDemoAccount', () => {
    it('devuelve el estado con los avisos de demo y la caja inicial', async () => {
        const m = await load();
        const result = await m.getManualDemoAccount();
        expect(result).toMatchObject({ ok: true, state: { cashEUR: 100000, cashUSD: 0 } });
        const notices = (result as { state: { notices: string[] } }).state.notices;
        expect(notices.join(' ')).toContain('dinero es ficticio');
        expect(notices.join(' ')).toContain('manual simulado');
    });

    it('caché de saldos descuadrada -> se declara en violations y se repara desde el libro', async () => {
        accountFindOne.mockImplementation(() => chainOf({ userId: 'user-1', version: 3, cashEUR: 99999, cashUSD: 0 }));
        const m = await load();
        const result = await m.getManualDemoAccount();
        const violations = (result as { state: { violations: string[] } }).state.violations;
        expect(violations[0]).toContain('Caché de saldos descuadrada');
        expect(accountFindOneAndUpdate).toHaveBeenCalledWith(
            { userId: 'user-1', version: 3 },
            { $set: { cashEUR: 100000, cashUSD: 0 }, $inc: { version: 1 } },
            { returnDocument: 'after' },
        );
    });

    it('posición de opción lleva vencimiento y badge calculados en servidor', async () => {
        const key = instrumentKey({ kind: 'opcion', contract: { underlying: 'AAPL', expiry: '2027-01-15', strike: 100, callPut: 'call', multiplier: 100, deliverable: 'acciones', adjusted: false }, name: '' });
        state = stateWith(100000, 0, [
            { instrumentKey: key, name: 'AAPL call', kind: 'opcion', currency: 'USD', quantity: 1, avgCost: 2, realizedPnl: 0 },
        ]);
        const m = await load();
        const result = await m.getManualDemoAccount();
        const pos = (result as { state: { positions: Array<{ optionExpiry: string | null; optionBadge: string | null }> } }).state.positions[0];
        expect(pos.optionExpiry).toBe('2027-01-15');
        expect(pos.optionBadge).toBe('vigente');
    });

    it('primera visita: crea la cuenta; carrera de creación (11000) no es error', async () => {
        accountFindOne
            .mockImplementationOnce(() => chainOf(null)) // ensureAccount: no existe
            .mockImplementation(() => chainOf({ userId: 'user-1', version: 1, cashEUR: 100000, cashUSD: 0 }));
        accountCreate.mockRejectedValueOnce({ code: 11000 });
        const m = await load();
        expect(await m.getManualDemoAccount()).toMatchObject({ ok: true });
    });

    it('error inesperado -> fallo genérico sin filtrar detalles internos', async () => {
        tradeFind.mockImplementation(() => { throw new Error('mongo caído'); });
        const m = await load();
        expect(await m.getManualDemoAccount()).toEqual({ ok: false, message: 'No se pudo completar la operación. Inténtalo de nuevo en unos minutos.' });
    });
});

describe('getManualDemoOrders', () => {
    it('mapea fills y rechazos con fechas en ms y simulated: true', async () => {
        tradeFind.mockImplementation(() => chainOf([
            { clientOrderId: 'a-00000001', kind: 'accion', symbol: 'AAPL', name: 'Apple', side: 'buy', openClose: 'open', quantity: 1, status: 'filled', fillPrice: 100, currency: 'EUR', fee: 0, executedAt: new Date(NOW), rejectReason: null, createdAt: new Date(NOW + 1000) },
            { clientOrderId: 'a-00000002', kind: 'accion', symbol: 'MSFT', name: 'Microsoft', side: 'buy', openClose: 'open', quantity: 1, status: 'rejected', fillPrice: null, currency: 'EUR', fee: 0, executedAt: null, rejectReason: 'sin saldo', createdAt: new Date(NOW + 2000) },
        ]));
        const m = await load();
        const result = await m.getManualDemoOrders();
        expect(result).toMatchObject({ ok: true });
        const orders = (result as { orders: Array<Record<string, unknown>> }).orders;
        expect(orders[0]).toMatchObject({ status: 'filled', fillPrice: 100, executedAt: NOW, createdAt: NOW + 1000, simulated: true });
        expect(orders[1]).toMatchObject({ status: 'rejected', fillPrice: null, executedAt: null, rejectReason: 'sin saldo' });
    });
});

describe('getManualDemoValuation: cotización real o N/D', () => {
    const applePosition = {
        instrumentKey: 'A:AAPL', name: 'Apple', kind: 'accion', currency: 'USD', quantity: 2, avgCost: 100, realizedPnl: 0,
    };

    it('sin posiciones -> sin consultar nada', async () => {
        const m = await load();
        const result = await m.getManualDemoValuation();
        expect(result).toMatchObject({ ok: true, listingUnavailable: false, quoteFetchFailed: false, retryAfterSeconds: null });
        expect(cacheGetQuote).not.toHaveBeenCalled();
    });

    it('sin FINNHUB_API_KEY -> listingUnavailable, filas sin valorar, NINGUNA llamada de cotización', async () => {
        state = stateWith(100000, 0, [applePosition]);
        const m = await load();
        const result = await m.getManualDemoValuation();
        expect(result).toMatchObject({ ok: true, listingUnavailable: true, quoteFetchFailed: false });
        expect(cacheGetQuote).not.toHaveBeenCalled();
        expect((result as { valuation: { coverage: { valued: number } } }).valuation.coverage.valued).toBe(0);
    });

    it('con listado y cotización fresca -> valorada; asOf es la cotización más vieja servida', async () => {
        state = stateWith(100000, 0, [applePosition]);
        process.env.FINNHUB_API_KEY = 'key';
        vi.stubGlobal('fetch', vi.fn<(...args: any[]) => any>(async () => ({ ok: true, json: async () => [{ symbol: 'AAPL', currency: 'USD' }] } as Response)));
        cacheGetQuote.mockResolvedValue({ quote: { c: 150, t: 1700000000, kind: 'live', source: 'Finnhub' }, fetchFailed: false, retryAfterSeconds: null, fetchedAt: 111, saturated: false });
        const m = await load();
        const result = await m.getManualDemoValuation();
        expect(result).toMatchObject({ ok: true, listingUnavailable: false, quoteFetchFailed: false, asOf: 111 });
        const valuation = (result as { valuation: { coverage: { valued: number; total: number }; rows: Array<{ status: string; marketValue: number | null }> } }).valuation;
        expect(valuation.coverage).toEqual({ valued: 1, total: 1 });
        expect(valuation.rows[0]).toMatchObject({ status: 'valorada', marketValue: 300 });
        vi.unstubAllGlobals();
    });

    it('todas las cotizaciones fallan -> quoteFetchFailed con el Retry-After del proveedor', async () => {
        state = stateWith(100000, 0, [applePosition]);
        process.env.FINNHUB_API_KEY = 'key';
        vi.stubGlobal('fetch', vi.fn<(...args: any[]) => any>(async () => ({ ok: true, json: async () => [{ symbol: 'AAPL', currency: 'USD' }] } as Response)));
        cacheGetQuote.mockResolvedValue({ quote: null, fetchFailed: true, retryAfterSeconds: 30, fetchedAt: null, saturated: false });
        const m = await load();
        const result = await m.getManualDemoValuation();
        expect(result).toMatchObject({ ok: true, quoteFetchFailed: true, retryAfterSeconds: 30 });
        vi.unstubAllGlobals();
    });
});
