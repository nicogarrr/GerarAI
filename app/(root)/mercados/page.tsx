import type { Metadata } from 'next';

import { TradingViewMarkets } from '@/components/markets/TradingViewMarkets';

export const metadata: Metadata = {
    title: 'Cotizaciones',
    description: 'Índices, acciones españolas, materias primas y divisas con el widget oficial de TradingView.',
};

export const dynamic = 'force-dynamic';

export default function MercadosPage() {
    return (
        <div className="container mx-auto max-w-3xl px-4 py-6">
            <h1 className="text-2xl font-bold text-gray-100">Mercados</h1>
            <p className="mt-1 text-sm text-gray-400">
                Índices, acciones españolas, materias primas y divisas. Los datos los sirve TradingView
                dentro de su propio widget.
            </p>
            <TradingViewMarkets />
        </div>
    );
}
