import type { Metadata } from 'next';
import { revalidatePath } from 'next/cache';

import { ManualDemoPanel } from '@/components/paper-trading/ManualDemoPanel';
import { PageHeader } from '@/components/ui/page-header';
import {
    convertManualDemoCurrency,
    getManualDemoAccount,
    getManualDemoValuation,
    placeManualOrder,
} from '@/lib/actions/manual-demo.actions';
import { getManualDemoHistory } from '@/lib/actions/manual-demo-history.actions';
import type { RefreshResult } from '@/components/paper-trading/ManualDemoPanel';
import type { DemoValuation } from '@/lib/market/demo-valuation';
import type { DemoStateView, FillSubmit, FxSubmit, HistoryPageResult, HistoryRow, SubmitResult } from '@/components/paper-trading/submit';

export const dynamic = 'force-dynamic';
export const revalidate = 0;

export const metadata: Metadata = {
    title: 'Cuenta demo',
    description:
        'Cuenta de práctica con saldo ficticio y operaciones manuales: registras compras y ventas con el precio que introduces tú.',
};

type DemoData = {
    account: DemoStateView | null;
    ledger: HistoryRow[];
    /** Primera página del historial: ¿hay más y con qué cursor pedirla? */
    historyHasMore: boolean;
    historyNextBefore: string | null;
    loadError: string | null;
    valuation?: DemoValuation | null;
    valuationAsOf?: number | null;
};

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
                optionExpiry: null,
                optionBadge: null,
            },
            {
                // Opción vencida de mentira (solo fixture dev, fuera de
                // producción): ejerce el badge de vencimiento en la tabla.
                instrumentKey: 'O:ASTS:2026-09-18:call:30:100',
                name: 'ASTS 2026-09-18 30 Call',
                kind: 'opcion',
                currency: 'USD',
                quantity: 1,
                avgCost: 1.5,
                realizedPnl: 0,
                optionExpiry: '2026-09-18',
                optionBadge: 'vencida',
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
    historyHasMore: false,
    historyNextBefore: null,
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
    const [accountResult, historyResult, valuationResult] = await Promise.all([
        getManualDemoAccount(),
        getManualDemoHistory(),
        getManualDemoValuation(),
    ]);
    if (!accountResult.ok) return { account: null, ledger: [], historyHasMore: false, historyNextBefore: null, loadError: accountResult.message };
    return {
        account: accountResult.state,
        valuation: valuationResult.ok ? valuationResult.valuation : null,
        valuationAsOf: valuationResult.ok ? valuationResult.asOf : null,
        ledger: historyResult.ok ? historyResult.orders : [],
        historyHasMore: historyResult.ok ? historyResult.hasMore : false,
        historyNextBefore: historyResult.ok ? historyResult.nextBefore : null,
        loadError: historyResult.ok ? null : historyResult.message,
    };
}

export default async function PaperTradingPage() {
    const { account, ledger, historyHasMore, historyNextBefore, loadError, valuation, valuationAsOf } = await loadDemoData();
    // Misma condicion que loadDemoData: fixtures dev sin Mongo. El comentario
    // de DEV_DATA prometia etiqueta en pantalla y no existia; sin ella la QA
    // visual leia saldos ficticios como si fueran una cuenta real.
    const usingFixtures = process.env.NODE_ENV !== 'production' && !process.env.MONGODB_URI;

    // Cableado real: la acción valida TODO en servidor dentro de la
    // transacción (saldo, posición, idempotencia); el cliente solo manda el
    // formulario. El fallo de la acción llega como message -> error.
    async function submitFill(input: FillSubmit): Promise<SubmitResult> {
        'use server';
        const result = await placeManualOrder(input);
        if (!result.ok) return { ok: false, error: result.message };
        // Un RECHAZO también persiste fila en el historial (append-only):
        // sin revalidar, el ledger (prop del server component) no la muestra
        // hasta recargar a mano (bug QA live 21-oct-2026: venta rechazada
        // ausente del Historial hasta F5). El fill ya refresca desde el
        // ticket (router.refresh); el rechazo no tenía ninguna vía.
        if (result.outcome === 'rejected') revalidatePath('/paper-trading');
        return { ok: true, outcome: result.outcome, reason: result.reason, state: result.state };
    }

    async function submitFx(input: FxSubmit): Promise<SubmitResult> {
        'use server';
        const result = await convertManualDemoCurrency(input);
        if (!result.ok) return { ok: false, error: result.message };
        // Misma vía que submitFill: una conversión rechazada también persiste
        // fila y debe aparecer en el Historial sin recarga manual.
        if (result.outcome === 'rejected') revalidatePath('/paper-trading');
        return { ok: true, outcome: result.outcome, reason: result.reason, state: result.state };
    }

    async function refreshValuation(): Promise<RefreshResult> {
        'use server';
        const result = await getManualDemoValuation();
        if (!result.ok) return { ok: false, error: result.message };
        return { ok: true, valuation: result.valuation, asOf: result.asOf, listingUnavailable: result.listingUnavailable, quoteFetchFailed: result.quoteFetchFailed, retryAfterSeconds: result.retryAfterSeconds };
    }

    // Página siguiente del historial: cursor estable (createdAt, _id), sin
    // offset — las filas nuevas entran por arriba y no desplazan el
    // recorrido. La autorización (userId de sesión) la aplica la acción en
    // CADA página; el cursor solo marca posición dentro del propio historial.
    async function loadMoreHistory(before: string): Promise<HistoryPageResult> {
        'use server';
        const result = await getManualDemoHistory({ before });
        if (!result.ok) return { ok: false, message: result.message };
        return { ok: true, orders: result.orders, hasMore: result.hasMore, nextBefore: result.nextBefore };
    }

    return (
        <main id="content" tabIndex={-1} className="mx-auto w-full max-w-3xl px-4 py-6">
            <PageHeader
                title="Cuenta demo"
                description="Práctica con dinero ficticio: 100.000 € iniciales, operaciones manuales y contabilidad FIFO."
            />
            {loadError ? (
                <p role="alert" className="mt-4 rounded-lg border border-amber-900/60 bg-amber-950/40 px-3 py-2 text-sm text-amber-200">
                    No se pudo cargar la cuenta demo: {loadError}
                </p>
            ) : null}
            {usingFixtures ? (
                <p role="note" className="mt-4 rounded-lg border border-sky-900/60 bg-sky-950/40 px-3 py-2 text-xs text-sky-200">
                    Datos de ejemplo para QA visual: sin MONGODB_URI la cuenta no está conectada y registrar operaciones fallará.
                </p>
            ) : null}
            <ManualDemoPanel
                account={account}
                ledger={ledger}
                historyHasMore={historyHasMore}
                historyNextBefore={historyNextBefore}
                loadMoreHistory={loadMoreHistory}
                submitFill={submitFill}
                submitFx={submitFx}
                valuation={valuation}
                valuationAsOf={valuationAsOf}
                refreshValuation={refreshValuation}
            />
        </main>
    );
}
