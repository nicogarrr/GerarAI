import type { Metadata } from 'next';
import { getLiveMarkets } from '@/lib/actions/live-quotes.actions';
import { LiveMarketsPanel } from '@/components/markets/LiveMarketsPanel';

export const dynamic = 'force-dynamic';
export const revalidate = 0;

export const metadata: Metadata = {
    title: 'Mercados',
    description:
        'Índices, futuros, acciones del IBEX 35, materias primas y divisas con la hora real de cada cotización y su fuente.',
};

export default async function MercadosPage() {
    // Si Yahoo falla ahora, el panel arranca vacio y reintenta solo al minuto:
    // el error inicial nunca deja la pagina en blanco.
    const initial = await getLiveMarkets().catch(() => null);
    return (
        <div className="mx-auto w-full max-w-3xl px-4 py-6">
            <h1 className="text-2xl font-semibold break-words text-gray-100">Mercados</h1>
            <p className="mt-1 text-sm text-gray-400">
                Índices, futuros, acciones, materias primas y divisas, actualizado cada minuto.
            </p>
            <LiveMarketsPanel initial={initial} />
        </div>
    );
}
