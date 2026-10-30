/** Disposable isolated visual quote test. No live user data or auth secrets. */
import { mkdirSync, writeFileSync, rmSync, existsSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
const directory = 'app/extended-quote-preview';
if (existsSync(directory)) throw new Error('Refusing to overwrite existing route');
mkdirSync(directory);
writeFileSync(`${directory}/page.tsx`, `
import { CompanyHeaderQuote } from '@/components/research/CompanyHeaderQuote';
import { e2eMarketFixture } from '@/lib/e2e-market-fixture';
export default async function Preview({ searchParams }: { searchParams: Promise<{ missingIdentity?: string }> }) {
 const snapshot = e2eMarketFixture('MSFT');
 snapshot.history = [];
 if ((await searchParams).missingIdentity === '1') { snapshot.exchange = null; snapshot.currency = null; }
 return <main className="mx-auto max-w-[1300px] p-4 sm:p-6"><h1 className="mb-4 text-2xl text-gray-100">Microsoft · MSFT</h1><CompanyHeaderQuote snapshot={snapshot}/></main>;
}`);
try {
    const result = spawnSync('npx', ['playwright', 'test', '--config', 'e2e/fixtures/extended-quote.config.ts', ...process.argv.slice(2)], { stdio: 'inherit', env: { ...process.env, E2E_EXTENDED_QUOTE_RUN: '1' } });
    process.exitCode = result.status ?? 1;
} finally { rmSync(directory, { recursive: true }); rmSync('.next-extended', { recursive: true, force: true }); }
