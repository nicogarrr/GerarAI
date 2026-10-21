import { chromium } from 'playwright-core';
const browser = await chromium.launch({ executablePath: '/usr/bin/google-chrome', args: ['--no-sandbox'] });
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
const errors = [];
page.on('pageerror', (e) => errors.push(String(e)));
await page.goto('http://localhost:3000/mercados', { waitUntil: 'domcontentloaded', timeout: 30000 });
await page.waitForTimeout(15000);
const iframes = await page.locator('iframe').count();
const blank = await page.evaluate(() => {
    const f = document.querySelector('iframe');
    try { return f?.contentDocument?.body?.innerText?.length ?? -1; } catch { return -2; }
});
await page.screenshot({ path: '/downloads/widget-direct-indices.png' });
console.log(JSON.stringify({ iframes, blank, errors: errors.slice(0, 3) }));
await browser.close();
