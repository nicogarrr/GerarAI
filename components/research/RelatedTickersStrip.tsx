import Link from 'next/link';
import { relatedTickerView, type RelatedTicker } from '@/lib/news-related-tickers';

const TONE: Record<string, string> = {
  up: 'text-emerald-300',
  down: 'text-red-300',
  flat: 'text-gray-300',
  none: 'text-gray-500',
};

/** Tira «tickers relacionados» de una noticia: ultimo cierre y variacion del dia. */
export function RelatedTickersStrip({ items }: { items?: RelatedTicker[] | null }) {
  if (!items || items.length === 0) return null;
  return (
    <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs" aria-label="Tickers relacionados" data-testid="related-tickers">
      {items.map((item) => {
        const view = relatedTickerView(item);
        return (
          <li key={item.ticker} title={view.title} className="flex items-center gap-1.5">
            {view.isEtf ? (
              <span className="font-medium text-sky-300">{view.ticker}</span>
            ) : (
              <Link prefetch={false} href={view.href} className="inline-flex min-h-[44px] min-w-[44px] items-center font-medium text-gray-200 hover:text-teal-200 sm:min-h-0 sm:min-w-0">{view.ticker}</Link>
            )}
            <span className="text-gray-400">{view.priceText}</span>
            <span className={TONE[view.tone]}>{view.changeText}</span>
            {view.dateText ? <span className="text-gray-500">cierre {view.dateText}</span> : null}
          </li>
        );
      })}
    </ul>
  );
}
