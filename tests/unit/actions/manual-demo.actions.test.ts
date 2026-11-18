import { beforeEach, describe, expect, it, vi } from 'vitest';

const {
    requireAuthenticatedUser, connectToDatabase,
    accountFindOne, accountCreate, accountFindOneAndUpdate,
    tradeFind, tradeFindOne, tradeCreate,
    computeManualDemoAccount, docsToLedger, cacheGetQuote, cacheGetChain,
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
    cacheGetChain: vi.fn<(...args: any[]) => any>(),
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
vi.mock('@/lib/market/cboe-options', async (importActual) => ({
    ...(await importActual<typeof import('@/lib/market/cboe-options')>()),
    createCboeChainCache: () => ({ getChain: cacheGetChain }),
}));
vi.mock('@/lib/market/quote-freshness', async (importActual) => ({
    ...(await importActual<typeof import('@/lib/market/quote-freshness')>()),
    sanitizeFinnhubQuote: (q: unknown) => q,
}));

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

const NOW = 1_795_500_000_000; // ms epoch plausible (2026-11-24: posterior a las primas CBOE de los fixtures, 17-nov-2026, o el control de fecha futura las rechazaría)
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
    delete process.env.FMP_BACKEND_URL;
    delete process.env.RESEARCH_AUTH_SECRET;
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

    it('opción en USD -> valorada con la prima REAL de CBOE (x100), sin tocar Finnhub', async () => {
        state = stateWith(100000, 500, [
            { instrumentKey: 'O:ASTS:2027-01-15:call:30:100', name: 'ASTS Call', kind: 'opcion', currency: 'USD', quantity: 2, avgCost: 1.5, realizedPnl: 0 },
        ]);
        cacheGetChain.mockResolvedValue({
            chain: new Map([['ASTS|2027-01-15|call|30000', { lastTradePrice: 2.3, lastTradeTime: '2026-11-17T15:47:43' }]]),
            fetchFailed: false,
            retryAfterSeconds: null,
            fetchedAt: 222,
            saturated: false,
        });
        const m = await load();
        const result = await m.getManualDemoValuation();
        expect(result).toMatchObject({ ok: true, asOf: 222 });
        const valuation = (result as { valuation: { coverage: { valued: number; total: number }; rows: Array<Record<string, unknown>> } }).valuation;
        expect(valuation.rows[0]).toMatchObject({ status: 'valorada', marketValue: 460, unrealizedPnl: 160, currencyBasis: 'cboe' });
        expect(valuation.coverage).toEqual({ valued: 1, total: 1 });
        // El subyacente no es la prima: ninguna consulta de cotización de acciones.
        expect(cacheGetQuote).not.toHaveBeenCalled();
        expect(cacheGetChain).toHaveBeenCalledWith('ASTS');
    });

    it('opción PUT en USD -> valorada con la prima DEL PUT, nunca con la del call del mismo strike', async () => {
        state = stateWith(100000, 500, [
            { instrumentKey: 'O:ASTS:2027-01-15:put:25:100', name: 'ASTS Put', kind: 'opcion', currency: 'USD', quantity: 2, avgCost: 1, realizedPnl: 0 },
        ]);
        cacheGetChain.mockResolvedValue({
            chain: new Map([
                ['ASTS|2027-01-15|call|25000', { lastTradePrice: 9.99, lastTradeTime: '2026-11-17T15:47:43' }],
                ['ASTS|2027-01-15|put|25000', { lastTradePrice: 1.1, lastTradeTime: '2026-11-17T15:47:43' }],
            ]),
            fetchFailed: false,
            retryAfterSeconds: null,
            fetchedAt: 222,
            saturated: false,
        });
        const m = await load();
        const result = await m.getManualDemoValuation();
        const valuation = (result as { valuation: { rows: Array<Record<string, unknown>> } }).valuation;
        // 2 contratos x 1,10 x 100 = 220 (put); con la prima del call serían 1998.
        expect(valuation.rows[0]).toMatchObject({ status: 'valorada', price: 1.1, marketValue: 220, unrealizedPnl: 20 });
        expect(cacheGetQuote).not.toHaveBeenCalled();
        expect(cacheGetChain).toHaveBeenCalledWith('ASTS');
    });

    it('más de 10 subyacentes de opción: solo se consultan 10 y el 11.º sale no-consultada con el límite', async () => {
        const underlyings = Array.from({ length: 11 }, (_, i) => `U${String(i + 1).padStart(2, '0')}`);
        state = stateWith(100000, 500, underlyings.map((u) => ({
            instrumentKey: `O:${u}:2027-01-15:call:30:100`, name: `${u} Call`, kind: 'opcion', currency: 'USD', quantity: 1, avgCost: 1, realizedPnl: 0,
        })));
        cacheGetChain.mockImplementation(async (u: string) => ({
            chain: new Map([[`${u}|2027-01-15|call|30000`, { lastTradePrice: 2, lastTradeTime: '2026-11-17T15:47:43' }]]),
            fetchFailed: false,
            retryAfterSeconds: null,
            fetchedAt: 222,
            saturated: false,
        }));
        const m = await load();
        const result = await m.getManualDemoValuation();
        const valuation = (result as { valuation: { coverage: { valued: number; total: number }; rows: Array<Record<string, unknown>> } }).valuation;
        expect(valuation.coverage).toEqual({ valued: 10, total: 11 });
        expect(cacheGetChain).toHaveBeenCalledTimes(10);
        expect(cacheGetChain).not.toHaveBeenCalledWith('U11');
        const notQueriedRow = valuation.rows.find((r) => r.instrumentKey === 'O:U11:2027-01-15:call:30:100');
        expect(notQueriedRow).toMatchObject({ status: 'no-consultada', marketValue: null });
        expect(String(notQueriedRow?.note)).toMatch(/límite de 10/);
    });

    it('opción en EUR -> N/D por divisa y su subyacente NO se consulta a la fuente de primas', async () => {
        state = stateWith(100000, 500, [
            { instrumentKey: 'O:EURCO:2027-01-15:call:30:100', name: 'EURCO Call', kind: 'opcion', currency: 'EUR', quantity: 1, avgCost: 1, realizedPnl: 0 },
            { instrumentKey: 'O:ASTS:2027-01-15:call:30:100', name: 'ASTS Call', kind: 'opcion', currency: 'USD', quantity: 1, avgCost: 1, realizedPnl: 0 },
        ]);
        cacheGetChain.mockImplementation(async (u: string) => ({
            chain: new Map([[`${u}|2027-01-15|call|30000`, { lastTradePrice: 2, lastTradeTime: '2026-11-17T15:47:43' }]]),
            fetchFailed: false,
            retryAfterSeconds: null,
            fetchedAt: 222,
            saturated: false,
        }));
        const m = await load();
        const result = await m.getManualDemoValuation();
        const valuation = (result as { valuation: { rows: Array<Record<string, unknown>> } }).valuation;
        const eurRow = valuation.rows.find((r) => r.instrumentKey === 'O:EURCO:2027-01-15:call:30:100');
        const usdRow = valuation.rows.find((r) => r.instrumentKey === 'O:ASTS:2027-01-15:call:30:100');
        expect(eurRow).toMatchObject({ status: 'divisa-no-coincide', marketValue: null });
        expect(usdRow).toMatchObject({ status: 'valorada', marketValue: 200 });
        expect(cacheGetChain).toHaveBeenCalledTimes(1);
        expect(cacheGetChain).toHaveBeenCalledWith('ASTS');
        expect(cacheGetChain).not.toHaveBeenCalledWith('EURCO');
    });

    it('opción con la fuente de primas caída -> N/D y quoteFetchFailed con su Retry-After', async () => {
        state = stateWith(100000, 500, [
            { instrumentKey: 'O:ASTS:2027-01-15:call:30:100', name: 'ASTS Call', kind: 'opcion', currency: 'USD', quantity: 2, avgCost: 1.5, realizedPnl: 0 },
        ]);
        cacheGetChain.mockResolvedValue({ chain: null, fetchFailed: true, retryAfterSeconds: 45, fetchedAt: null, saturated: false });
        const m = await load();
        const result = await m.getManualDemoValuation();
        expect(result).toMatchObject({ ok: true, quoteFetchFailed: true, retryAfterSeconds: 45 });
        const valuation = (result as { valuation: { rows: Array<Record<string, unknown>> } }).valuation;
        expect(valuation.rows[0]).toMatchObject({ status: 'sin-cotizacion', marketValue: null });
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

    const bbvaPosition = {
        instrumentKey: 'A:BBVA.MC', name: 'BBVA', kind: 'accion', currency: 'EUR', quantity: 100, avgCost: 9, realizedPnl: 0,
    };
    const usOnlyListing = () => vi.stubGlobal('fetch', vi.fn(async (..._args: Parameters<typeof fetch>): Promise<Response> => ({ ok: true, json: async () => [{ symbol: 'AAPL', currency: 'USD' }] } as Response)));

    it('fuera del listado US con divisa declarada por el backend -> valorada con base backend-yahoo', async () => {
        state = stateWith(100000, 0, [bbvaPosition]);
        process.env.FINNHUB_API_KEY = 'key';
        usOnlyListing();
        cacheGetQuote.mockResolvedValue({ quote: { c: 10.5, pc: 10.4, t: null, kind: 'close', source: 'Yahoo Finance', currency: 'EUR', closeDate: '2026-11-06' }, fetchFailed: false, retryAfterSeconds: null, fetchedAt: 111, saturated: false });
        const m = await load();
        const result = await m.getManualDemoValuation();
        expect(result).toMatchObject({ ok: true, listingUnavailable: false, quoteFetchFailed: false, asOf: 111 });
        const valuation = (result as { valuation: { coverage: { valued: number; total: number }; rows: Array<Record<string, unknown>> } }).valuation;
        expect(valuation.coverage).toEqual({ valued: 1, total: 1 });
        expect(valuation.rows[0]).toMatchObject({ status: 'valorada', marketValue: 1050, currencyBasis: 'backend-yahoo' });
        vi.unstubAllGlobals();
    });

    it('fuera del listado US SIN divisa declarada por el backend -> N/D con aviso, nunca se infiere', async () => {
        state = stateWith(100000, 0, [bbvaPosition]);
        process.env.FINNHUB_API_KEY = 'key';
        usOnlyListing();
        cacheGetQuote.mockResolvedValue({ quote: { c: 10.5, pc: 10.4, t: null, kind: 'close', source: 'Yahoo Finance', closeDate: '2026-11-06' }, fetchFailed: false, retryAfterSeconds: null, fetchedAt: 111, saturated: false });
        const m = await load();
        const result = await m.getManualDemoValuation();
        expect(result).toMatchObject({ ok: true, listingUnavailable: false, quoteFetchFailed: false });
        const valuation = (result as { valuation: { coverage: { valued: number; total: number }; rows: Array<Record<string, unknown>> } }).valuation;
        expect(valuation.coverage).toEqual({ valued: 0, total: 1 });
        expect(valuation.rows[0]).toMatchObject({ status: 'divisa-no-coincide', marketValue: null });
        expect(String(valuation.rows[0].note)).toContain('Divisa no declarada por la fuente de cotización');
        vi.unstubAllGlobals();
    });

    // Ramas del callback REAL backendYahooQuote: el cache mock invoca el
    // fetcher de verdad y fetch se rutea entre el listado Finnhub y la
    // /api/market/quote/ del backend propio.
    const realBackendCallback = () => {
        cacheGetQuote.mockImplementation(async (symbol: string, fetcher: (s: string) => Promise<{ quote: unknown; fetchFailed: boolean; retryAfterSeconds: number | null }>) => {
            const attempt = await fetcher(symbol);
            return { quote: attempt.quote, fetchFailed: attempt.fetchFailed, retryAfterSeconds: attempt.retryAfterSeconds, fetchedAt: attempt.quote ? 111 : null, saturated: false };
        });
    };
    const backendFetch = (responder: () => Promise<Response>) => vi.stubGlobal('fetch', vi.fn(async (...args: Parameters<typeof fetch>): Promise<Response> => {
        if (String(args[0]).includes('/api/market/quote/')) return responder();
        return { ok: true, json: async () => [{ symbol: 'AAPL', currency: 'USD' }] } as Response;
    }));
    const backendEnv = () => {
        process.env.FINNHUB_API_KEY = 'key';
        process.env.FMP_BACKEND_URL = 'https://backend.test';
        process.env.RESEARCH_AUTH_SECRET = 's'.repeat(32);
    };

    it('callback real del backend con divisa EUR declarada -> valorada 1050 (backend-yahoo)', async () => {
        state = stateWith(100000, 0, [bbvaPosition]);
        backendEnv();
        backendFetch(async () => ({ ok: true, json: async () => ({ c: 10.5, pc: 10.4, currency: 'EUR', cd: '2026-11-06' }) } as Response));
        realBackendCallback();
        const m = await load();
        const result = await m.getManualDemoValuation();
        expect(result).toMatchObject({ ok: true, listingUnavailable: false, quoteFetchFailed: false, asOf: 111 });
        const valuation = (result as { valuation: { coverage: { valued: number; total: number }; rows: Array<Record<string, unknown>> } }).valuation;
        expect(valuation.coverage).toEqual({ valued: 1, total: 1 });
        expect(valuation.rows[0]).toMatchObject({ status: 'valorada', marketValue: 1050, currencyBasis: 'backend-yahoo' });
        vi.unstubAllGlobals();
    });

    it('callback real del backend SIN divisa -> N/D, nunca inferida', async () => {
        state = stateWith(100000, 0, [bbvaPosition]);
        backendEnv();
        backendFetch(async () => ({ ok: true, json: async () => ({ c: 10.5, pc: 10.4, cd: '2026-11-06' }) } as Response));
        realBackendCallback();
        const m = await load();
        const result = await m.getManualDemoValuation();
        expect(result).toMatchObject({ ok: true, quoteFetchFailed: false });
        const valuation = (result as { valuation: { coverage: { valued: number; total: number }; rows: Array<Record<string, unknown>> } }).valuation;
        expect(valuation.coverage).toEqual({ valued: 0, total: 1 });
        expect(valuation.rows[0]).toMatchObject({ status: 'divisa-no-coincide', marketValue: null });
        vi.unstubAllGlobals();
    });

    it.each([
        ['503 del backend', async () => ({ ok: false, status: 503 } as Response)],
        ['fallo de red al backend', async () => { throw new TypeError('fetch failed'); }],
    ])('callback real: %s -> sin cotización y quoteFetchFailed', async (_nombre, responder) => {
        state = stateWith(100000, 0, [bbvaPosition]);
        backendEnv();
        backendFetch(responder);
        realBackendCallback();
        const m = await load();
        const result = await m.getManualDemoValuation();
        expect(result).toMatchObject({ ok: true, listingUnavailable: false, quoteFetchFailed: true, retryAfterSeconds: null });
        const valuation = (result as { valuation: { coverage: { valued: number; total: number }; rows: Array<Record<string, unknown>> } }).valuation;
        expect(valuation.coverage).toEqual({ valued: 0, total: 1 });
        expect(valuation.rows[0]).toMatchObject({ status: 'sin-cotizacion', marketValue: null });
        vi.unstubAllGlobals();
    });

    it('callback real sin FMP_BACKEND_URL -> sin llamada, sin cotización y quoteFetchFailed', async () => {
        state = stateWith(100000, 0, [bbvaPosition]);
        process.env.FINNHUB_API_KEY = 'key';
        const fetchMock = vi.fn(async (..._args: Parameters<typeof fetch>): Promise<Response> => ({ ok: true, json: async () => [{ symbol: 'AAPL', currency: 'USD' }] } as Response));
        vi.stubGlobal('fetch', fetchMock);
        realBackendCallback();
        const m = await load();
        const result = await m.getManualDemoValuation();
        expect(result).toMatchObject({ ok: true, listingUnavailable: false, quoteFetchFailed: true, retryAfterSeconds: null });
        expect(fetchMock.mock.calls.filter((c) => String(c[0]).includes('/api/market/quote/'))).toEqual([]);
        const valuation = (result as { valuation: { coverage: { valued: number; total: number }; rows: Array<Record<string, unknown>> } }).valuation;
        expect(valuation.coverage).toEqual({ valued: 0, total: 1 });
        expect(valuation.rows[0]).toMatchObject({ status: 'sin-cotizacion', marketValue: null });
        vi.unstubAllGlobals();
    });
});

/* ------------------------------------------------------------------ */
/* Cobertura de ramas (auditor 18-nov-2026): bordes de parseo,         */
/* comparación fina de payloads persistidos, carreras en la grabación  */
/* del rechazo, errores de infraestructura y callbacks reales de las   */
/* fuentes de cotización.                                              */
/* ------------------------------------------------------------------ */

describe('validación de órdenes: bordes que faltaban', () => {
    it.each([
        ['clientOrderId no es cadena', { clientOrderId: 42 }, 'clientOrderId'],
        ['executedAt no es número', { executedAt: 'ayer' }, 'executedAt'],
        ['executedAt no entero', { executedAt: NOW + 0.5 }, 'executedAt'],
        ['precio minúsculo en notación exponencial', { price: 0.0000001 }, 'price'],
        ['precio por encima del tope', { price: 10_000_001 }, 'price'],
        ['precio NaN', { price: Number.NaN }, 'price'],
        ['cantidad por encima del tope', { quantity: 1_000_001 }, 'quantity'],
        ['cantidad no numérica', { quantity: '10' }, 'quantity'],
        ['comisión por encima del tope', { fee: 10_000_001 }, 'fee'],
        ['comisión NaN', { fee: Number.NaN }, 'fee'],
        ['instrumento nulo', { instrument: null }, 'instrument'],
        ['símbolo no es cadena', { instrument: { kind: 'accion', symbol: 42 } }, 'symbol'],
    ])('%s -> fallo con campo, sin escribir', async (_name: string, patch: object, expectedField: string) => {
        const m = await load();
        const result = await m.placeManualOrder(order(patch));
        expect(result).toMatchObject({ ok: false, field: expectedField });
        expect(tradeCreate).not.toHaveBeenCalled();
    });

    it('comisión ausente vale 0; nombre no cadena cae al símbolo', async () => {
        const m = await load();
        expect(await m.placeManualOrder(order({ fee: undefined }))).toMatchObject({ ok: true, outcome: 'filled' });
        expect(
            await m.placeManualOrder(order({ clientOrderId: 'orden-de-prueba-2', instrument: { kind: 'accion', symbol: 'AAPL', name: 42 } })),
        ).toMatchObject({ ok: true, outcome: 'filled' });
    });
});

describe('validación fx: bordes que faltaban', () => {
    it('conversión que no es objeto -> campo fx', async () => {
        const m = await load();
        expect(await m.convertManualDemoCurrency(null)).toMatchObject({ ok: false, field: 'fx' });
        expect(tradeCreate).not.toHaveBeenCalled();
    });

    it.each([
        ['clientOrderId no es cadena', { clientOrderId: 42 }, 'clientOrderId'],
        ['origen no soportada', { from: 'GBP' }, 'from'],
        ['destino no soportada', { to: 'JPY' }, 'to'],
        ['importe no numérico', { amount: '100' }, 'amount'],
        ['importe cero', { amount: 0 }, 'amount'],
        ['importe por encima del tope', { amount: 100_000_001 }, 'amount'],
        ['importe NaN', { amount: Number.NaN }, 'amount'],
        ['tipo no numérico', { rate: 'x' }, 'rate'],
        ['tipo cero', { rate: 0 }, 'rate'],
        ['tipo por encima del tope', { rate: 1001 }, 'rate'],
        ['fecha no numérica', { executedAt: 'ayer' }, 'executedAt'],
    ])('%s -> fallo con campo, sin escribir', async (_name: string, patch: object, expectedField: string) => {
        const m = await load();
        const result = await m.convertManualDemoCurrency(fxOrder(patch));
        expect(result).toMatchObject({ ok: false, field: expectedField });
        expect(tradeCreate).not.toHaveBeenCalled();
    });
});

describe('idempotencia: comparación fina del payload persistido (acciones)', () => {
    const storedFill = {
        clientOrderId: 'orden-de-prueba-1', kind: 'accion', symbol: 'AAPL', name: 'Apple',
        contract: null, side: 'buy', openClose: 'open', quantity: 10, status: 'filled',
        fillPrice: 100, currency: 'EUR', fee: 0, executedAt: new Date(NOW),
        rejectReason: null, createdAt: new Date(NOW), requestPayload: null,
    };

    it.each([
        ['tipo distinto (fx)', { kind: 'fx' }],
        ['lado distinto', { side: 'sell', openClose: 'close' }],
        ['openClose distinto', { openClose: 'close' }],
        ['cantidad distinta', { quantity: 11 }],
        ['divisa distinta', { currency: 'USD' }],
        ['símbolo distinto', { symbol: 'MSFT' }],
        ['precio de fill distinto', { fillPrice: 99 }],
        ['comisión distinta', { fee: 1 }],
        ['fecha de ejecución distinta', { executedAt: new Date(NOW + 60_000) }],
        ['fill sin fecha persistida', { executedAt: null }],
    ])('fill persistido con %s -> conflicto, no duplicado', async (_name: string, delta: object) => {
        tradeFindOne.mockImplementation(() => chainOf({ ...storedFill, ...delta }));
        const m = await load();
        expect(await m.placeManualOrder(order())).toMatchObject({ ok: false, field: 'clientOrderId' });
        expect(tradeCreate).not.toHaveBeenCalled();
    });

    const optionContract = { underlying: 'AAPL', expiry: '2027-01-15', strike: 100, callPut: 'call' as const, multiplier: 100, deliverable: 'acciones' };
    const optionOrder = () => order({ currency: 'USD', openClose: 'open', price: 2, quantity: 1, instrument: { kind: 'opcion', contract: optionContract } });
    const storedOptionFill = {
        clientOrderId: 'orden-de-prueba-1', kind: 'opcion', symbol: null, name: 'AAPL Call',
        contract: optionContract, side: 'buy', openClose: 'open', quantity: 1, status: 'filled',
        fillPrice: 2, currency: 'USD', fee: 0, executedAt: new Date(NOW),
        rejectReason: null, createdAt: new Date(NOW), requestPayload: null,
    };

    it('opción: mismo contrato -> duplicate; contrato ausente o distinto -> conflicto', async () => {
        tradeFindOne.mockImplementation(() => chainOf(storedOptionFill));
        const m = await load();
        expect(await m.placeManualOrder(optionOrder())).toMatchObject({ ok: true, outcome: 'duplicate' });
        // Sin contrato persistido no se puede reconstruir la clave: conflicto honesto.
        tradeFindOne.mockImplementation(() => chainOf({ ...storedOptionFill, contract: null }));
        expect(await m.placeManualOrder(optionOrder())).toMatchObject({ ok: false, field: 'clientOrderId' });
        // Otro contrato = otra operación con la misma clave de idempotencia.
        tradeFindOne.mockImplementation(() => chainOf({ ...storedOptionFill, contract: { ...optionContract, strike: 105 } }));
        expect(await m.placeManualOrder(optionOrder())).toMatchObject({ ok: false, field: 'clientOrderId' });
    });

    const baseSnap = {
        v: 1, kind: 'accion', symbol: 'AAPL', contractKey: null, side: 'buy', openClose: 'open',
        quantity: 10, currency: 'EUR', price: 100, fee: 0, executedAtMs: NOW,
    };
    const rejectedWith = (requestPayload: unknown) => ({
        ...storedFill, status: 'rejected', fillPrice: null, executedAt: null, rejectReason: 'r', requestPayload,
    });

    it.each([
        ['tipo', { kind: 'opcion', symbol: null, contractKey: 'AAPL|2027-01-15|call|100000' }],
        ['símbolo', { symbol: 'MSFT' }],
        ['clave de contrato', { contractKey: 'AAPL|2027-01-15|call|100000' }],
        ['lado', { side: 'sell' }],
        ['openClose', { openClose: 'close' }],
        ['cantidad', { quantity: 11 }],
        ['divisa', { currency: 'USD' }],
        ['precio', { price: 99 }],
        ['comisión', { fee: 2 }],
        ['fecha', { executedAtMs: NOW + 1 }],
    ])('rechazo con snapshot que difiere en %s -> conflicto', async (_name: string, delta: object) => {
        tradeFindOne.mockImplementation(() => chainOf(rejectedWith({ ...baseSnap, ...delta })));
        const m = await load();
        expect(await m.placeManualOrder(order())).toMatchObject({ ok: false, field: 'clientOrderId' });
    });

    it.each([
        ['un array', [] as unknown],
        ['versión desconocida', { v: 2 }],
        ['tipo ajeno', { v: 1, kind: 'fx' }],
        ['lado imposible', { v: 1, kind: 'accion', side: 'hold' }],
        ['openClose imposible', { v: 1, kind: 'accion', side: 'buy', openClose: 'x' }],
        ['divisa ajena', { v: 1, kind: 'accion', side: 'buy', openClose: 'open', currency: 'GBP' }],
        ['símbolo no cadena', { v: 1, kind: 'accion', side: 'buy', openClose: 'open', currency: 'EUR', symbol: 42 }],
        ['contrato no cadena', { v: 1, kind: 'opcion', side: 'buy', openClose: 'open', currency: 'EUR', contractKey: 42 }],
        ['cantidad no numérica', { v: 1, kind: 'accion', side: 'buy', openClose: 'open', currency: 'EUR', quantity: '10', price: 100, fee: 0, executedAtMs: NOW }],
        ['precio no finito', { v: 1, kind: 'accion', side: 'buy', openClose: 'open', currency: 'EUR', quantity: 10, price: Number.NaN, fee: 0, executedAtMs: NOW }],
    ])('rechazo con snapshot inválido (%s) -> igualdad legacy por el subconjunto persistido', async (_name: string, payload: unknown) => {
        tradeFindOne.mockImplementation(() => chainOf(rejectedWith(payload)));
        const m = await load();
        expect(await m.placeManualOrder(order())).toMatchObject({ ok: true, outcome: 'duplicate', reason: 'r' });
    });
});

describe('idempotencia fx: comparación fina del payload persistido', () => {
    const storedFx = {
        clientOrderId: 'fx-de-prueba-0001', kind: 'fx', symbol: 'EURUSD', fxFrom: 'EUR', fxTo: 'USD',
        side: 'buy', openClose: 'open', quantity: 100, status: 'filled', fillPrice: 1.1,
        currency: 'EUR', fee: 0, executedAt: new Date(NOW), rejectReason: null, createdAt: new Date(NOW), requestPayload: null,
    };

    it.each([
        ['tipo no fx', { kind: 'accion' }],
        ['origen distinta', { fxFrom: 'USD' }],
        ['destino distinta', { fxTo: 'EUR' }],
        ['importe distinto', { quantity: 50 }],
        ['tipo de cambio distinto', { fillPrice: 1.2 }],
        ['fecha distinta', { executedAt: new Date(NOW + 60_000) }],
        ['fill sin fecha persistida', { executedAt: null }],
    ])('fx persistido con %s -> conflicto, no duplicado', async (_name: string, delta: object) => {
        tradeFindOne.mockImplementation(() => chainOf({ ...storedFx, ...delta }));
        const m = await load();
        expect(await m.convertManualDemoCurrency(fxOrder())).toMatchObject({ ok: false, field: 'clientOrderId' });
        expect(tradeCreate).not.toHaveBeenCalled();
    });

    const baseFxSnap = { v: 1, kind: 'fx', from: 'EUR', to: 'USD', amount: 100, rate: 1.1, executedAtMs: NOW };
    const rejectedFxWith = (requestPayload: unknown) => ({
        ...storedFx, status: 'rejected', fillPrice: null, executedAt: null, rejectReason: 'r', requestPayload,
    });

    it('rechazo fx con snapshot idéntico -> duplicate con el motivo grabado', async () => {
        tradeFindOne.mockImplementation(() => chainOf(rejectedFxWith(baseFxSnap)));
        const m = await load();
        expect(await m.convertManualDemoCurrency(fxOrder())).toMatchObject({ ok: true, outcome: 'duplicate', reason: 'r' });
    });

    it.each([
        ['origen', { from: 'USD' }],
        ['destino', { to: 'EUR' }],
        ['importe', { amount: 50 }],
        ['tipo de cambio', { rate: 1.2 }],
        ['fecha', { executedAtMs: NOW + 1 }],
    ])('rechazo fx con snapshot que difiere en %s -> conflicto', async (_name: string, delta: object) => {
        tradeFindOne.mockImplementation(() => chainOf(rejectedFxWith({ ...baseFxSnap, ...delta })));
        const m = await load();
        expect(await m.convertManualDemoCurrency(fxOrder())).toMatchObject({ ok: false, field: 'clientOrderId' });
    });

    it.each([
        ['versión desconocida', { v: 2, kind: 'fx' }],
        ['tipo ajeno', { v: 1, kind: 'accion' }],
        ['origen ajena', { v: 1, kind: 'fx', from: 'GBP', to: 'USD' }],
        ['destino ajeno', { v: 1, kind: 'fx', from: 'EUR', to: 'JPY' }],
        ['importe no numérico', { v: 1, kind: 'fx', from: 'EUR', to: 'USD', amount: '100', rate: 1.1, executedAtMs: NOW }],
        ['tipo no finito', { v: 1, kind: 'fx', from: 'EUR', to: 'USD', amount: 100, rate: Number.NaN, executedAtMs: NOW }],
        ['no es objeto', 'texto' as unknown],
    ])('rechazo fx con snapshot inválido (%s) -> igualdad legacy', async (_name: string, payload: unknown) => {
        tradeFindOne.mockImplementation(() => chainOf(rejectedFxWith(payload)));
        const m = await load();
        expect(await m.convertManualDemoCurrency(fxOrder())).toMatchObject({ ok: true, outcome: 'duplicate', reason: 'r' });
    });
});

describe('transacción: la grabación del rechazo resiste carreras', () => {
    const divergence = () => {
        computeManualDemoAccount
            .mockImplementationOnce(() => stateWith())
            .mockImplementationOnce(() => ({ ...stateWith(), violations: ['descuadre replay'] }))
            .mockImplementation(() => stateWith());
    };
    const storedDoc = (status: string, over: object = {}) => ({
        clientOrderId: 'orden-de-prueba-1', kind: 'accion', symbol: 'AAPL', contract: null,
        side: 'buy', openClose: 'open', quantity: 10, status, fillPrice: status === 'filled' ? 100 : null,
        currency: 'EUR', fee: 0, executedAt: status === 'filled' ? new Date(NOW) : null,
        rejectReason: null, createdAt: new Date(NOW), requestPayload: null, ...over,
    });

    it('el rechazo ya estaba grabado sin motivo persistido -> se devuelve el motivo de ESTE intento', async () => {
        divergence();
        tradeFindOne.mockImplementationOnce(() => chainOf(null));
        tradeFindOne.mockImplementation(() => chainOf(storedDoc('rejected')));
        const m = await load();
        const result = await m.placeManualOrder(order());
        expect(result).toMatchObject({ ok: true, outcome: 'rejected' });
        expect((result as { reason: string }).reason).toContain('no cuadra en su fecha');
    });

    it('el ganador de la carrera fue el fill -> duplicate', async () => {
        divergence();
        tradeFindOne.mockImplementationOnce(() => chainOf(null));
        tradeFindOne.mockImplementation(() => chainOf(storedDoc('filled')));
        const m = await load();
        expect(await m.placeManualOrder(order())).toMatchObject({ ok: true, outcome: 'duplicate' });
    });

    it('la carrera persistió OTRA operación -> conflicto explícito, no reinterpretación', async () => {
        divergence();
        tradeFindOne.mockImplementationOnce(() => chainOf(null));
        tradeFindOne.mockImplementation(() => chainOf(storedDoc('filled', { fillPrice: 55 })));
        const m = await load();
        expect(await m.placeManualOrder(order())).toMatchObject({ ok: false, field: 'clientOrderId' });
    });

    it('grabar el rechazo falla con error NO duplicado -> propaga y se declara genérico', async () => {
        divergence();
        tradeFindOne.mockImplementation(() => chainOf(null));
        tradeCreate.mockResolvedValueOnce([{}] as never); // el fill
        tradeCreate.mockRejectedValueOnce(new Error('índice caído')); // el rechazo
        const m = await load();
        expect(await m.placeManualOrder(order())).toMatchObject({ ok: false, message: expect.stringContaining('No se pudo completar') });
    });

    it('sin fila persistida tras la carrera -> rechazo con el motivo de este intento', async () => {
        divergence();
        tradeFindOne.mockImplementation(() => chainOf(null));
        const m = await load();
        const result = await m.placeManualOrder(order());
        expect(result).toMatchObject({ ok: true, outcome: 'rejected' });
        expect((result as { reason: string }).reason).toContain('no cuadra en su fecha');
    });
});

describe('convertManualDemoCurrency: carrera de clave duplicada y errores', () => {
    const storedFx = {
        clientOrderId: 'fx-de-prueba-0001', kind: 'fx', symbol: 'EURUSD', fxFrom: 'EUR', fxTo: 'USD',
        side: 'buy', openClose: 'open', quantity: 100, status: 'filled', fillPrice: 1.1,
        currency: 'EUR', fee: 0, executedAt: new Date(NOW), rejectReason: null, createdAt: new Date(NOW), requestPayload: null,
    };

    it('11000 al insertar y el ganador es idéntico -> duplicate', async () => {
        tradeCreate.mockRejectedValue({ code: 11000 });
        tradeFindOne.mockImplementationOnce(() => chainOf(null)); // pre-chequeo: nada
        tradeFindOne.mockImplementation(() => chainOf(storedFx)); // tras la carrera: lo persistido
        const m = await load();
        expect(await m.convertManualDemoCurrency(fxOrder())).toMatchObject({ ok: true, outcome: 'duplicate' });
    });

    it('11000 al insertar y no aparece lo persistido -> fallo genérico', async () => {
        tradeCreate.mockRejectedValue({ code: 11000 });
        const m = await load();
        expect(await m.convertManualDemoCurrency(fxOrder())).toMatchObject({ ok: false, message: expect.stringContaining('No se pudo completar') });
    });

    it('divergencia y la carrera persistió OTRA operación -> conflicto explícito', async () => {
        computeManualDemoAccount
            .mockImplementationOnce(() => stateWith())
            .mockImplementationOnce(() => ({ ...stateWith(), violations: ['descuadre replay'] }))
            .mockImplementation(() => stateWith());
        tradeFindOne.mockImplementationOnce(() => chainOf(null));
        tradeFindOne.mockImplementation(() => chainOf({ ...storedFx, fillPrice: 9.99 }));
        const m = await load();
        expect(await m.convertManualDemoCurrency(fxOrder())).toMatchObject({ ok: false, field: 'clientOrderId' });
    });

    it('versión en conflicto en la conversión -> fallo legible', async () => {
        accountFindOneAndUpdate.mockResolvedValue(null);
        const m = await load();
        expect(await m.convertManualDemoCurrency(fxOrder())).toMatchObject({ ok: false, message: expect.stringContaining('otra operación a la vez') });
    });
});

describe('errores de infraestructura: declarados, nunca filtrados', () => {
    it('sin conexión a Mongo en runtime -> fallo genérico', async () => {
        connectToDatabase.mockResolvedValue(null);
        const m = await load();
        expect(await m.placeManualOrder(order())).toMatchObject({ ok: false, message: expect.stringContaining('No se pudo completar') });
    });

    it('cuenta ausente dentro de la transacción -> fallo genérico', async () => {
        accountFindOne.mockImplementation(() => chainOf(null));
        const m = await load();
        expect(await m.placeManualOrder(order())).toMatchObject({ ok: false, message: expect.stringContaining('No se pudo completar') });
    });

    it('un rechazo que no es Error se envuelve con String(), sin romper', async () => {
        tradeCreate.mockRejectedValue('cadena de error cruda');
        const m = await load();
        expect(await m.convertManualDemoCurrency(fxOrder())).toMatchObject({ ok: false, message: expect.stringContaining('No se pudo completar') });
    });
});

describe('getManualDemoOrders: filas con fechas no-Date', () => {
    it('executedAt/createdAt que no son Date salen null/0, nunca rompen la fila', async () => {
        tradeFind.mockImplementation(() => chainOf([{
            clientOrderId: 'orden-x', kind: 'fx', symbol: 'EURUSD', side: 'buy', openClose: 'open',
            quantity: 100, status: 'rejected', fillPrice: null, currency: 'EUR', fee: 0,
            executedAt: 12345, rejectReason: 'r', createdAt: 'ayer',
        }]));
        const m = await load();
        const result = await m.getManualDemoOrders();
        expect(result).toMatchObject({ ok: true });
        const row = (result as { orders: Array<Record<string, unknown>> }).orders[0];
        expect(row).toMatchObject({ executedAt: null, createdAt: 0 });
    });
});

describe('callback real de Finnhub (finnhubOnlyQuote) y listado US caído', () => {
    const applePosition = {
        instrumentKey: 'A:AAPL', name: 'Apple', kind: 'accion', currency: 'USD', quantity: 2, avgCost: 100, realizedPnl: 0,
    };
    const bbvaPosition = {
        instrumentKey: 'A:BBVA.MC', name: 'BBVA', kind: 'accion', currency: 'EUR', quantity: 100, avgCost: 9, realizedPnl: 0,
    };
    // El cache mock invoca el fetcher de verdad (finnhubOnlyQuote), como hace
    // el callback real del backend en los tests de arriba.
    const realQuoteCallback = (withSignal = false) => {
        cacheGetQuote.mockImplementation(async (symbol: string, fetcher: (s: string, signal?: AbortSignal) => Promise<{ quote: unknown; fetchFailed: boolean; retryAfterSeconds: number | null }>) => {
            const attempt = await fetcher(symbol, withSignal ? new AbortController().signal : undefined);
            return { quote: attempt.quote, fetchFailed: attempt.fetchFailed, retryAfterSeconds: attempt.retryAfterSeconds, fetchedAt: attempt.quote ? 111 : null, saturated: false };
        });
    };
    const finnhubFetch = (quoteResponder: () => Promise<Response>) => {
        const fetchMock = vi.fn(async (...args: Parameters<typeof fetch>): Promise<Response> => {
            if (String(args[0]).includes('stock/symbol')) return { ok: true, json: async () => [{ symbol: 'AAPL', currency: 'USD' }] } as Response;
            return quoteResponder();
        });
        vi.stubGlobal('fetch', fetchMock);
        return fetchMock;
    };
    const firstRow = async () => {
        const m = await load();
        const result = await m.getManualDemoValuation();
        const valuation = (result as { valuation: { rows: Array<Record<string, unknown>> } }).valuation;
        return { result, row: valuation.rows[0] };
    };

    it('cotización OK con señal -> valorada; fetch a la URL pública con token', async () => {
        state = stateWith(100000, 0, [applePosition]);
        process.env.FINNHUB_API_KEY = 'key';
        const fetchMock = finnhubFetch(async () => ({ ok: true, json: async () => ({ c: 150, pc: 149, t: 1700000000, kind: 'live', source: 'Finnhub' }) } as Response));
        realQuoteCallback(true);
        const { result, row } = await firstRow();
        expect(result).toMatchObject({ ok: true, quoteFetchFailed: false });
        expect(row).toMatchObject({ status: 'valorada', marketValue: 300 });
        const quoteCall = fetchMock.mock.calls.find((c) => String(c[0]).includes('/quote?'));
        expect(String(quoteCall?.[0])).toBe('https://finnhub.io/api/v1/quote?symbol=AAPL&token=key');
        vi.unstubAllGlobals();
    });

    it('429 con Retry-After: 30 -> la espera se propaga a la valoración', async () => {
        state = stateWith(100000, 0, [applePosition]);
        process.env.FINNHUB_API_KEY = 'key';
        finnhubFetch(async () => ({ ok: false, headers: { get: (k: string) => (k === 'retry-after' ? '30' : null) } } as unknown as Response));
        realQuoteCallback();
        const { result, row } = await firstRow();
        expect(result).toMatchObject({ ok: true, quoteFetchFailed: true, retryAfterSeconds: 30 });
        expect(row).toMatchObject({ status: 'sin-cotizacion', marketValue: null });
        vi.unstubAllGlobals();
    });

    it('503 sin cabecera Retry-After -> fallo sin espera propagada', async () => {
        state = stateWith(100000, 0, [applePosition]);
        process.env.FINNHUB_API_KEY = 'key';
        finnhubFetch(async () => ({ ok: false, headers: { get: () => null } } as unknown as Response));
        realQuoteCallback();
        const { result, row } = await firstRow();
        expect(result).toMatchObject({ ok: true, quoteFetchFailed: true, retryAfterSeconds: null });
        expect(row).toMatchObject({ status: 'sin-cotizacion', marketValue: null });
        vi.unstubAllGlobals();
    });

    it('error de red -> fallo transitorio, nunca excepción', async () => {
        state = stateWith(100000, 0, [applePosition]);
        process.env.FINNHUB_API_KEY = 'key';
        finnhubFetch(async () => { throw new TypeError('fetch failed'); });
        realQuoteCallback();
        const { result, row } = await firstRow();
        expect(result).toMatchObject({ ok: true, quoteFetchFailed: true });
        expect(row).toMatchObject({ status: 'sin-cotizacion', marketValue: null });
        vi.unstubAllGlobals();
    });

    it('listado US HTTP 503 -> listingUnavailable y filas N/D', async () => {
        state = stateWith(100000, 0, [bbvaPosition]);
        process.env.FINNHUB_API_KEY = 'key';
        vi.stubGlobal('fetch', vi.fn(async (): Promise<Response> => ({ ok: false } as Response)));
        const { result, row } = await firstRow();
        expect(result).toMatchObject({ ok: true, listingUnavailable: true, quoteFetchFailed: false });
        expect(row).toMatchObject({ marketValue: null });
        vi.unstubAllGlobals();
    });

    it('listado US vacío -> listingUnavailable (no se valora con divisa desconocida)', async () => {
        state = stateWith(100000, 0, [bbvaPosition]);
        process.env.FINNHUB_API_KEY = 'key';
        vi.stubGlobal('fetch', vi.fn(async (): Promise<Response> => ({ ok: true, json: async () => [] } as Response)));
        const { result, row } = await firstRow();
        expect(result).toMatchObject({ ok: true, listingUnavailable: true });
        expect(row).toMatchObject({ marketValue: null });
        vi.unstubAllGlobals();
    });

    it('listado US: error de red -> listingUnavailable', async () => {
        state = stateWith(100000, 0, [bbvaPosition]);
        process.env.FINNHUB_API_KEY = 'key';
        vi.stubGlobal('fetch', vi.fn(async (): Promise<Response> => { throw new TypeError('fetch failed'); }));
        const { result, row } = await firstRow();
        expect(result).toMatchObject({ ok: true, listingUnavailable: true });
        expect(row).toMatchObject({ marketValue: null });
        vi.unstubAllGlobals();
    });
});

describe('getManualDemoValuation: bordes de agregación', () => {
    const applePosition = {
        instrumentKey: 'A:AAPL', name: 'Apple', kind: 'accion', currency: 'USD', quantity: 2, avgCost: 100, realizedPnl: 0,
    };
    const bbvaPosition = {
        instrumentKey: 'A:BBVA.MC', name: 'BBVA', kind: 'accion', currency: 'EUR', quantity: 100, avgCost: 9, realizedPnl: 0,
    };
    const optionPosition = (key: string) => ({
        instrumentKey: key, name: key, kind: 'opcion', currency: 'USD', quantity: 1, avgCost: 1, realizedPnl: 0,
    });
    const usListing = () => vi.stubGlobal('fetch', vi.fn(async (): Promise<Response> => ({ ok: true, json: async () => [{ symbol: 'AAPL', currency: 'USD' }] } as Response)));

    it('cotización sin fetchedAt -> asOf cae al reloj actual, nunca a una hora inventada', async () => {
        state = stateWith(100000, 0, [applePosition]);
        process.env.FINNHUB_API_KEY = 'key';
        usListing();
        cacheGetQuote.mockResolvedValue({ quote: { c: 150, t: 1700000000, kind: 'live', source: 'Finnhub' }, fetchFailed: false, retryAfterSeconds: null, fetchedAt: null, saturated: false });
        const m = await load();
        const result = await m.getManualDemoValuation();
        expect(result).toMatchObject({ ok: true, asOf: NOW + 60_000 });
        vi.unstubAllGlobals();
    });

    it('la promesa de cotización rechazada se pliega a fallo de la fila, nunca rompe la valoración', async () => {
        state = stateWith(100000, 0, [applePosition]);
        process.env.FINNHUB_API_KEY = 'key';
        usListing();
        cacheGetQuote.mockRejectedValue(new Error('boom'));
        const m = await load();
        const result = await m.getManualDemoValuation();
        expect(result).toMatchObject({ ok: true, quoteFetchFailed: true, retryAfterSeconds: null });
        vi.unstubAllGlobals();
    });

    it('backend: la promesa de cotización rechazada también se pliega', async () => {
        state = stateWith(100000, 0, [bbvaPosition]);
        process.env.FINNHUB_API_KEY = 'key';
        process.env.FMP_BACKEND_URL = 'https://backend.test';
        process.env.RESEARCH_AUTH_SECRET = 's'.repeat(32);
        usListing();
        cacheGetQuote.mockRejectedValue(new Error('boom'));
        const m = await load();
        const result = await m.getManualDemoValuation();
        expect(result).toMatchObject({ ok: true, quoteFetchFailed: true, retryAfterSeconds: null });
        vi.unstubAllGlobals();
    });

    it('backend con señal: combineAbortSignals llega al fetch', async () => {
        state = stateWith(100000, 0, [bbvaPosition]);
        process.env.FINNHUB_API_KEY = 'key';
        process.env.FMP_BACKEND_URL = 'https://backend.test';
        process.env.RESEARCH_AUTH_SECRET = 's'.repeat(32);
        vi.stubGlobal('fetch', vi.fn(async (...args: Parameters<typeof fetch>): Promise<Response> => {
            if (String(args[0]).includes('/api/market/quote/')) return { ok: true, json: async () => ({ c: 10.5, pc: 10.4, currency: 'EUR', cd: '2026-11-06' }) } as Response;
            return { ok: true, json: async () => [{ symbol: 'AAPL', currency: 'USD' }] } as Response;
        }));
        cacheGetQuote.mockImplementation(async (symbol: string, fetcher: (s: string, signal?: AbortSignal) => Promise<{ quote: unknown; fetchFailed: boolean; retryAfterSeconds: number | null }>) => {
            const attempt = await fetcher(symbol, new AbortController().signal);
            return { quote: attempt.quote, fetchFailed: attempt.fetchFailed, retryAfterSeconds: attempt.retryAfterSeconds, fetchedAt: attempt.quote ? 111 : null, saturated: false };
        });
        const m = await load();
        const result = await m.getManualDemoValuation();
        const valuation = (result as { valuation: { rows: Array<Record<string, unknown>> } }).valuation;
        expect(valuation.rows[0]).toMatchObject({ status: 'valorada', marketValue: 1050 });
        vi.unstubAllGlobals();
    });

    it('opción con instrumentKey irreconocible -> N/D sin consultar la cadena', async () => {
        state = stateWith(100000, 500, [optionPosition('clave-rota')]);
        const m = await load();
        const result = await m.getManualDemoValuation();
        expect(cacheGetChain).not.toHaveBeenCalled();
        const valuation = (result as { valuation: { rows: Array<Record<string, unknown>> } }).valuation;
        expect(valuation.rows[0]).toMatchObject({ marketValue: null });
    });

    it('cadena presente pero sin el contrato -> N/D, nunca la prima de otro contrato', async () => {
        state = stateWith(100000, 500, [optionPosition('O:ASTS:2027-01-15:call:30:100')]);
        cacheGetChain.mockResolvedValue({ chain: new Map(), fetchFailed: false, retryAfterSeconds: null, fetchedAt: null, saturated: false });
        const m = await load();
        const result = await m.getManualDemoValuation();
        expect(result).toMatchObject({ ok: true, asOf: NOW + 60_000 });
        const valuation = (result as { valuation: { rows: Array<Record<string, unknown>> } }).valuation;
        expect(valuation.rows[0]).toMatchObject({ marketValue: null });
    });

    it('fuente de primas caída sin Retry-After -> quoteFetchFailed sin espera propagada', async () => {
        state = stateWith(100000, 500, [optionPosition('O:ASTS:2027-01-15:call:30:100')]);
        cacheGetChain.mockResolvedValue({ chain: null, fetchFailed: true, retryAfterSeconds: null, fetchedAt: null, saturated: false });
        const m = await load();
        const result = await m.getManualDemoValuation();
        expect(result).toMatchObject({ ok: true, quoteFetchFailed: true, retryAfterSeconds: null });
    });

    it('la promesa de la cadena rechazada se pliega a fallo de la fila', async () => {
        state = stateWith(100000, 500, [optionPosition('O:ASTS:2027-01-15:call:30:100')]);
        cacheGetChain.mockRejectedValue(new Error('boom'));
        const m = await load();
        const result = await m.getManualDemoValuation();
        expect(result).toMatchObject({ ok: true, quoteFetchFailed: true });
        const valuation = (result as { valuation: { rows: Array<Record<string, unknown>> } }).valuation;
        expect(valuation.rows[0]).toMatchObject({ marketValue: null });
    });
});
