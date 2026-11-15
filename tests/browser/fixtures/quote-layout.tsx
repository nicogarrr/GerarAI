import { createRoot } from 'react-dom/client';
import { CompanyHeaderQuote } from '@/components/research/CompanyHeaderQuote';
import type { CompanyMarketSnapshot } from '@/lib/actions/market-workspace.actions';
import '../../../app/globals.css';

declare global {
    interface Window { resolveQuote: (value: unknown) => void }
}
// Test-only delayed response. No real network/vendor/model calls.
window.fetch = () => new Promise(resolve => {
    window.resolveQuote = value => resolve(new Response(JSON.stringify(value), {
        headers: { 'Content-Type': 'application/json' },
    }));
});
const compact = new URLSearchParams(location.search).get('compact') !== '0';
const snapshot = { ticker: 'MSFT', currency: 'USD', exchange: 'NASDAQ', history: [] } as unknown as CompanyMarketSnapshot;
createRoot(document.getElementById('root')!).render(
    <main style={{ padding: '20px 16px', maxWidth: 900, margin: '0 auto' }}>
        <h1 className="mb-6 text-xl font-semibold">Microsoft · MSFT</h1>
        <CompanyHeaderQuote snapshot={snapshot} compact={compact} />
        <a href="#report" data-testid="report-link" className="mt-10 inline-flex min-h-11 items-center text-sm text-teal-300">Informe tipo analista →</a>
    </main>,
);
