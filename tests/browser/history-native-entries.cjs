// Run: node tests/browser/history-native-entries.cjs
// Isolated same-document browser regression, no app server or credentials.
const { chromium } = require('playwright');
const ts = require('typescript');
const fs = require('node:fs');
const assert = require('node:assert/strict');
const http = require('node:http');
const source = ['lib/nav/in-app-history.ts', 'lib/nav/browser-history.ts'].map(file =>
    ts.transpileModule(fs.readFileSync(file, 'utf8').replace(/^import .*;\n/gm, '').replace(/export /g, ''),
        { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.None } }).outputText
).join('\n');
(async () => {
    const server = http.createServer((_, res) => res.end('<html><body>History test</body></html>')).listen(0, '127.0.0.1');
    await new Promise(resolve => server.once('listening', resolve));
    const browser = await chromium.launch({ headless: true });
    try {
        const page = await browser.newPage();
        await page.goto(`http://127.0.0.1:${server.address().port}`);
        await page.addScriptTag({ content: `${source}\nwindow.tracker = { mount: () => trackBrowserHistory(window), stack: () => inAppHistoryStore.getSnapshot(), steps: () => historyBackSteps(inAppHistoryStore.getSnapshot()) };` });
        await page.evaluate(() => {
            history.replaceState(null, '', '/pretracker');
            history.pushState(null, '', '/watchlist');
            window.cleanup = window.tracker.mount();
            history.pushState(null, '', '/research/MSFT');
            history.go(-2);
        });
        await page.waitForURL('**/pretracker');
        assert.deepEqual(await page.evaluate(() => ({ stack: window.tracker.stack(), steps: window.tracker.steps() })), { stack: ['/pretracker'], steps: 0 });
        console.log('PASS unknown unstamped POP before mount: no invented origin');
        await page.evaluate(() => {
            window.cleanup();
            history.replaceState(null, '', '/watchlist');
            window.cleanup = window.tracker.mount();
            history.pushState(null, '', '/research/MSFT');
        });
        for (const hash of ['#analistas', '#historial-analistas', '#analistas']) {
            await page.evaluate(hash => { location.hash = hash; }, hash);
            await page.waitForFunction(hash => window.tracker.stack().at(-1).endsWith(hash), hash);
        }
        assert.equal(await page.evaluate(() => window.tracker.steps()), 4);
        await page.evaluate(() => history.go(-window.tracker.steps()));
        await page.waitForURL('**/watchlist');
        assert.deepEqual(await page.evaluate(() => window.tracker.stack()), ['/watchlist']);
        console.log('PASS repeated native anchors: go(-4) reaches /watchlist');
        await page.evaluate(() => { history.pushState(null, '', '/B'); history.pushState(null, '', '/watchlist'); });
        assert.deepEqual(await page.evaluate(() => window.tracker.stack()), ['/watchlist', '/B', '/watchlist']);
        await page.evaluate(() => history.back()); await page.waitForURL('**/B');
        await page.evaluate(() => history.forward()); await page.waitForURL('**/watchlist');
        assert.equal(await page.evaluate(() => window.tracker.stack().length), 3);
        console.log('PASS A→B→A PUSH, POP and forward, browser ' + browser.version());
    } finally { await browser.close(); server.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
