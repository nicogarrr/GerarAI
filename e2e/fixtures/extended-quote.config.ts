import { defineConfig } from '@playwright/test';
const port = process.env.E2E_EXTENDED_QUOTE_PORT || '3101';
export default defineConfig({
    testDir: '..', testMatch: 'extended-quote.spec.ts', workers: 1, timeout: 60000,
    use: { baseURL: `http://127.0.0.1:${port}`, launchOptions: { executablePath: process.env.E2E_CHROME_PATH || '/usr/bin/google-chrome', args: ['--no-sandbox'] } },
    webServer: { command: `npm run dev -- --hostname 127.0.0.1 --port ${port}`, cwd: '../..', env: { APP_ENV: 'test', E2E_AUTH_BYPASS: '1', NEXT_DIST_DIR: '.next-extended' }, url: `http://127.0.0.1:${port}/extended-quote-preview`, reuseExistingServer: false, timeout: 120000 },
});
