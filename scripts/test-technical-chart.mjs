/** Disposable Next route for isolated browser regression, never deployed. */
import { mkdirSync, writeFileSync, rmSync, existsSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
const directory = 'app/chart-preview';
if (existsSync(directory)) throw new Error('Refusing to overwrite existing route');
mkdirSync(directory);
const yahooRaw = { chart: { result: [{ timestamp: Array.from({length: 40}, (_,i)=>1790000000+i*86400), indicators: { quote: [{ close: Array.from({length:40}, (_,i)=>100+i), open: Array(40).fill(null), high: Array(40).fill(null), low: Array(40).fill(null), volume: Array(40).fill(null) }] } }] } };
const adapter = spawnSync(process.env.PYTHON_BIN || 'python3', ['scripts/fixtures/yahoo-close-only-adapter.py'], {input:JSON.stringify(yahooRaw),encoding:'utf8'});
if (adapter.status !== 0) { rmSync(directory,{recursive:true}); throw new Error(adapter.stderr); }
writeFileSync(`${directory}/yahoo.json`, adapter.stdout);

writeFileSync(`${directory}/page.tsx`, `
import { CompanyHeaderQuote } from '@/components/research/CompanyHeaderQuote';
import { e2eMarketFixture } from '@/lib/e2e-market-fixture';
import { normalizeChartCandles } from '@/lib/market/normalize-chart';
import yahoo from './yahoo.json';
export default async function Preview({ searchParams }: { searchParams: Promise<{ mode?: string }> }) {
 const {mode} = await searchParams;
 const snapshot = e2eMarketFixture('MSFT');
 snapshot.historySource = mode === 'yahoo' ? 'Yahoo adaptador real (fixture)' : 'Fixture local';
 if (mode === 'unavailable') { snapshot.quote.price = null; snapshot.quote.change = null; snapshot.quote.changePercent = null; }
 snapshot.history = mode === 'yahoo' ? normalizeChartCandles(yahoo, {from:0,to:2000000000,resolution:'D'}) : mode === 'empty' || mode === 'unavailable' ? [] : mode === 'close' ? snapshot.history : Array.from({ length: 260 }, (_, i) => { const close = 325 + Math.sin(i / 8) * 14 + Math.cos(i / 3) * 5 + i * 0.04; return { date: new Date(Date.UTC(2026, 0, i + 1)).toISOString().slice(0,10), open: close-1, high: close+3, low: close-4, close, volume: 1000000+i*100 }; });
 return <main className="mx-auto max-w-[1500px] p-4 sm:p-6"><h1 className="mb-4 text-2xl text-gray-100">MSFT</h1><CompanyHeaderQuote snapshot={snapshot}/></main>;
}`);
try {
 const result = spawnSync('npx', ['playwright', 'test', '--config', 'e2e/fixtures/technical-chart.config.ts'], { stdio: 'inherit', env: { ...process.env, E2E_CHART_RUN: '1' } });
 process.exitCode = result.status ?? 1;
} finally { rmSync(directory, {recursive:true}); rmSync('.next-chart/dev/types', {recursive:true, force:true}); }
