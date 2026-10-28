import type { Metadata } from 'next';
import { getLiveMarkets } from '@/lib/actions/live-quotes.actions';
import { LiveMarketsPanel } from '@/components/markets/LiveMarketsPanel';
import { PageHeader } from '@/components/ui/page-header';

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
        <main id="content" tabIndex={-1} className="mx-auto w-full max-w-3xl">
            <PageHeader
                title="Mercados"
                description="Índices, futuros, acciones, materias primas y divisas, actualizado cada minuto."
            />
            <LiveMarketsPanel initial={initial} />
        </main>
    );
}
