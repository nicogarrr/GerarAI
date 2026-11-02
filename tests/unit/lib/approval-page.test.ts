import { describe, expect, it } from 'vitest';
import { approvalPage, escapeHtml } from '@/lib/auth/approval-page';
describe('approval page contract', () => {
    it('escapes every HTML delimiter', () => {
        expect(escapeHtml('&<>"\'')).toBe('&amp;&lt;&gt;&quot;&#39;');
    });
    it.each(['32rem', '40rem'])('preserves exact HTML, status and no-store for %s', async (width) => {
        const title = '<Pending>';
        const body = '<p>Review</p>';
        const page = approvalPage(title, body, 403, 'en', width);
        expect(page.status).toBe(403);
        expect(page.headers.get('cache-control')).toBe('no-store');
        expect(page.headers.get('content-type')).toBe('text/html; charset=utf-8');
        expect(await page.text()).toBe([
            '<!doctype html><html lang="en"><head><meta charset="utf-8">',
            '<meta name="viewport" content="width=device-width, initial-scale=1">',
            '<title>&lt;Pending&gt; - GerarAI</title></head>',
            `<body style="font-family: system-ui, sans-serif; max-width: ${width}; margin: 4rem auto; padding: 0 1rem;">`,
            '<h1>&lt;Pending&gt;</h1>', body, '</body></html>',
        ].join(''));
    });
});
