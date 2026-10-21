import type { Metadata } from 'next';

import { ManualDemoPanel } from '@/components/paper-trading/ManualDemoPanel';
import type { DemoStateView, HistoryRow, SubmitResult } from '@/components/paper-trading/submit';

export const dynamic = 'force-dynamic';
export const revalidate = 0;

export const metadata: Metadata = {
    title: 'Cuenta demo',
    description:
        'Cuenta de práctica con saldo ficticio y operaciones manuales: registras compras y ventas con el precio que introduces tú.',
};

type DemoData = { account: DemoStateView | null; ledger: HistoryRow[] };

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
};

/**
 * PUNTO DE CABLEADO (pilot): sustituir por la acción real de
 * lib/actions/manual-demo.actions.ts cuando esté integrada. Hasta entonces:
 * desarrollo ve los fixtures de arriba; producción ve la cuenta sin
 * conectar (formulario desactivado, sin datos inventados).
 */
async function loadDemoData(): Promise<DemoData> {
    if (process.env.NODE_ENV !== 'production') return DEV_DATA;
    return { account: null, ledger: [] };
}

export default async function PaperTradingPage() {
    const { account, ledger } = await loadDemoData();

    // PUNTO DE CABLEADO (pilot): sustituir por registerManualDemoOrder /
    // registerManualDemoFx de lib/actions/manual-demo.actions.ts. El
    // resultado de la acción encaja directo en SubmitResult (ok+outcome+
    // reason+state, o fallo con message -> error).
    async function submitFillNotWired(): Promise<SubmitResult> {
        'use server';
        return { ok: false, error: 'El registro en servidor todavía no está conectado.' };
    }

    async function submitFxNotWired(): Promise<SubmitResult> {
        'use server';
        return { ok: false, error: 'El registro en servidor todavía no está conectado.' };
    }

    return (
        <div className="mx-auto w-full max-w-3xl px-4 py-6">
            <h1 className="text-2xl font-semibold break-words text-gray-100">Cuenta demo</h1>
            <p className="mt-1 text-sm text-gray-400">
                Práctica con dinero ficticio: 100.000 € iniciales, operaciones manuales y contabilidad FIFO.
            </p>
            <ManualDemoPanel account={account} ledger={ledger} submitFill={submitFillNotWired} submitFx={submitFxNotWired} />
        </div>
    );
}
