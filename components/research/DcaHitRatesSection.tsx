import DcaHitRatesCard from '@/components/watchlist/DcaHitRatesCard';
import { getDcaHitRates } from '@/lib/actions/dca-signals.actions';

/** Ficha de research: histórico de señales DCA si el ticker está en watchlist o cartera. */
export async function DcaHitRatesSection({ ticker }: { ticker: string }) {
    const data = await getDcaHitRates(ticker);
    if (!data) return null; // no seguido o servicio caído: la ficha no cambia
    return (
        <section aria-label="Histórico de señales DCA" className="rounded-lg border border-gray-800 bg-gray-900/40 p-3">
            <DcaHitRatesCard data={data} />
        </section>
    );
}
