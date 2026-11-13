import type { APIRequestContext } from '@playwright/test';

type Account = { email: string; password: string; name: string };

/** Only synthetic E2E accounts. Never ignore an arbitrary signup failure. */
export async function ensureSignInAccount(request: Pick<APIRequestContext, 'post'>, baseURL: string, account: Account): Promise<void> {
    const response = await request.post(`${baseURL}/api/auth/sign-up/email`, {
        data: { ...account, acceptTerms: true },
        headers: { Origin: baseURL },
        failOnStatusCode: false,
    });
    const payload: unknown = await response.json().catch(() => null);
    const status = response.status();
    if (payload && typeof payload === 'object') {
        if (status >= 200 && status < 300 && 'user' in payload) {
            const user = payload.user;
            if (user && typeof user === 'object' && 'id' in user && typeof user.id === 'string' && user.id
                && 'email' in user && user.email === account.email) return;
        }
        // Desktop/mobile and retries share this known synthetic account.
        if (status === 422 && 'code' in payload
            && payload.code === 'USER_ALREADY_EXISTS_USE_ANOTHER_EMAIL') return;
    }
    // Do not include response bodies, account addresses or passwords.
    throw new Error(`E2E sign-in account setup failed (HTTP ${status}); expected a created user or a documented duplicate.`);
}
