import type { Metadata } from 'next';

import { ManualDemoPanel } from '@/components/paper-trading/ManualDemoPanel';
import {
    convertManualDemoCurrency,
    getManualDemoAccount,
    getManualDemoOrders,
    placeManualOrder,
} from '@/lib/actions/manual-demo.actions';
import type { DemoStateView, FillSubmit, FxSubmit, HistoryRow, SubmitResult } from '@/components/paper-trading/submit';

export const dynamic = 'force-dynamic';
export const revalidate = 0;

export const metadata: Metadata = {
    title: 'Cuenta demo',
    description:
        'Cuenta de práctica con saldo ficticio y operaciones manuales: registras compras y ventas con el precio que introduces tú.',
};

type DemoData = { account: DemoStateView | null; ledger: HistoryRow[]; loadError: string | null };

/**
 * Datos de ejemplo SOLO para desarrollo local (qa visual de la pantalla).
 * En producción NUNCA se muestran como operaciones del usuario: sin el
 * servidor conectado la página muestra la cuenta vacía y el formulario
 * desactivado.
 */
const DEV_DATA: DemoData = {
    account: {
        cashEUR: 98_500,
        cashUSD: 2_240,
        realizedEUR: 250,
        realizedUSD: 0,
        positions: [
            {
                instrumentKey: 'A:ASTS',
                name: 'AST SpaceMobile',
                kind: 'accion',
                currency: 'USD',
                quantity: 5,
                avgCost: 50,
                realizedPnl: 250,
            },
        ],
        violations: [],
        notices: [],
    },
    ledger: [
        {
            clientOrderId: 'dev-fixture-2',
            kind: 'accion',
            symbol: 'ASTS',
            name: 'AST SpaceMobile',
            side: 'sell',
            openClose: 'close',
            quantity: 5,
            status: 'filled',
            fillPrice: 60,
            currency: 'USD',
            fee: 0,
            executedAt: Date.now() - 86_400_000,
            rejectReason: null,
            createdAt: Date.now() - 86_400_000,
            simulated: true,
        },
        {
            clientOrderId: 'dev-fixture-1',
            kind: 'accion',
            symbol: 'ASTS',
            name: 'AST SpaceMobile',
            side: 'buy',
            openClose: 'open',
            quantity: 10,
            status: 'filled',
            fillPrice: 40,
            currency: 'USD',
            fee: 0,
            executedAt: Date.now() - 86_400_000 * 2,
            rejectReason: null,
            createdAt: Date.now() - 86_400_000 * 2,
            simulated: true,
        },
        {
            clientOrderId: 'dev-fixture-3',
            kind: 'fx',
            symbol: 'EURUSD',
            name: 'Conversión manual EUR→USD',
            side: 'buy',
            openClose: 'open',
            quantity: 2_000,
            status: 'filled',
            fillPrice: 1.12,
            currency: 'EUR',
            fee: 0,
            executedAt: Date.now() - 86_400_000 * 3,
            rejectReason: null,
            createdAt: Date.now() - 86_400_000 * 3,
            simulated: true,
        },
        {
            clientOrderId: 'dev-fixture-4',
            kind: 'accion',
            symbol: 'NVDA',
            name: 'NVIDIA',
            side: 'buy',
            openClose: 'open',
            quantity: 100,
            status: 'rejected',
            fillPrice: null,
            currency: 'USD',
            fee: 0,
            executedAt: null,
            rejectReason: 'Saldo USD insuficiente para esa compra',
            createdAt: Date.now() - 3_600_000,
            simulated: true,
        },
    ],
    loadError: null,
};

/**
 * Cableado real: las server actions de lib/actions/manual-demo.actions.ts
 * (cuenta propia de la sesión, libro FIFO en Mongo). Los fixtures de arriba
 * SOLO se usan en desarrollo sin base de datos configurada, y van
 * etiquetados en la propia pantalla; nunca aparecen como operaciones del
 * usuario en producción. Si la acción falla, se muestra el error, no un
 * estado neutro que lo oculte.
 */
async function loadDemoData(): Promise<DemoData> {
    if (process.env.NODE_ENV !== 'production' && !process.env.MONGODB_URI) return { ...DEV_DATA, loadError: null };
    const [accountResult, ordersResult] = await Promise.all([getManualDemoAccount(), getManualDemoOrders()]);
    if (!accountResult.ok) return { account: null, ledger: [], loadError: accountResult.message };
    return {
        account: accountResult.state,
        ledger: ordersResult.ok ? ordersResult.orders : [],
        loadError: ordersResult.ok ? null : ordersResult.message,
    };
}

export default async function PaperTradingPage() {
    const { account, ledger, loadError } = await loadDemoData();

    // Cableado real: la acción valida TODO en servidor dentro de la
    // transacción (saldo, posición, idempotencia); el cliente solo manda el
    // formulario. El fallo de la acción llega como message -> error.
    async function submitFill(input: FillSubmit): Promise<SubmitResult> {
        'use server';
        const result = await placeManualOrder(input);
        if (!result.ok) return { ok: false, error: result.message };
        return { ok: true, outcome: result.outcome, reason: result.reason, state: result.state };
    }

    async function submitFx(input: FxSubmit): Promise<SubmitResult> {
        'use server';
        const result = await convertManualDemoCurrency(input);
        if (!result.ok) return { ok: false, error: result.message };
        return { ok: true, outcome: result.outcome, reason: result.reason, state: result.state };
    }

    return (
        <div className="mx-auto w-full max-w-3xl px-4 py-6">
            <h1 className="text-2xl font-semibold break-words text-gray-100">Cuenta demo</h1>
            <p className="mt-1 text-sm text-gray-400">
                Práctica con dinero ficticio: 100.000 € iniciales, operaciones manuales y contabilidad FIFO.
            </p>
            {loadError ? (
                <p role="alert" className="mt-4 rounded-lg border border-amber-900/60 bg-amber-950/40 px-3 py-2 text-sm text-amber-200">
                    No se pudo cargar la cuenta demo: {loadError}
                </p>
            ) : null}
            <ManualDemoPanel account={account} ledger={ledger} submitFill={submitFill} submitFx={submitFx} />
        </div>
    );
}
