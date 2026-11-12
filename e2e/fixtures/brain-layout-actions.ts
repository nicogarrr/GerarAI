import type { Page } from '@playwright/test';

/** Layout tests must neither depend on configured LLMs nor call a provider. */
export function brainLayoutReply(body: string | null, marker?: string): unknown | undefined {
    let args: unknown;
    try { args = JSON.parse(body ?? ''); } catch { return undefined; }
    if (!Array.isArray(args)) return undefined;
    if (args.length === 1 && (args[0] === 'chat' || args[0] === 'analysis')) {
        return { feature: args[0], state: 'unverified', can_start: true, reason: 'not_probed', retry_after_seconds: null };
    }
    if (marker && typeof args[0] === 'string' && args[0].includes(marker)) {
        return { success: true, message: 'Layout fixture response. No provider was called.' };
    }
    return undefined;
}

export async function mockBrainLayoutActions(page: Page, marker?: string): Promise<void> {
    await page.route('**/*', async route => {
        const request = route.request();
        if (request.method() !== 'POST' || !request.headers()['next-action']) return route.continue();
        const reply = brainLayoutReply(request.postData(), marker);
        if (reply === undefined) return route.continue();
        // Next server-action Flight envelope, consumed by its real decoder.
        return route.fulfill({ status: 200, contentType: 'text/x-component',
            body: `0:${JSON.stringify({ a: reply, f: null, b: 'development' })}\n` });
    });
}
