import { chromium } from 'playwright-core';
const browser = await chromium.launch({ executablePath: '/usr/bin/google-chrome', args: ['--no-sandbox'] });
for (const w of [390, 1280]) {
    const page = await browser.newPage({ viewport: { width: w, height: 900 } });
    const errors = [];
    page.on('pageerror', (e) => errors.push(String(e)));
    await page.goto('http://localhost:3000/mercados', { waitUntil: 'domcontentloaded', timeout: 30000 });
    await page.waitForTimeout(12000);
    const tabs = ['Índices', 'Índices (CFD)', 'Acciones ES', 'Materias primas', 'Divisas'];
    for (const t of tabs) {
        await page.getByRole('tab', { name: t, exact: true }).click();
        await page.waitForTimeout(9000);
        const rows = await page.locator('iframe').evaluate((f) => -1).catch(() => -1);
        await page.screenshot({ path: `/downloads/tab-${w}-${t.replace(/[^A-Za-z]/g, '')}.png` });
    }
    console.log(JSON.stringify({ w, errors: errors.slice(0, 2) }));
    await page.close();
}
await browser.close();
