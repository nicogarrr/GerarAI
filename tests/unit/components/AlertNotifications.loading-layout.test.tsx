import { render, screen, waitFor } from '@testing-library/react';
import { renderToString } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
vi.mock('@/lib/actions/push.actions', () => ({
    getPushStatus: vi.fn(async () => ({ enabled: false, public_key: null, preferences: [] })),
    registerPushDevice: vi.fn(), removePushDevice: vi.fn(), setPushPreference: vi.fn(),
}));
vi.mock('@/lib/actions/email-alerts.actions', () => ({
    getEmailAlertStatus: vi.fn(async () => ({ smtp: false, email: null, preferences: [] })),
    setEmailAlertPreference: vi.fn(),
}));
import PushNotifications from '@/components/alerts/PushNotifications';
import EmailNotifications from '@/components/alerts/EmailNotifications';

describe('notification panel loading layout', () => {
    it('reserves one text line plus the existing gap in both server-rendered panels', () => {
        const container = document.createElement('div');
        container.innerHTML = renderToString(<><PushNotifications /><EmailNotifications /></>);
        for (const id of ['push-loading-space', 'email-loading-space']) {
            const placeholder = container.querySelector(`[data-testid="${id}"]`);
            expect(placeholder).toHaveClass('h-5');
            expect(placeholder).toHaveAttribute('aria-hidden', 'true');
            expect(placeholder?.parentElement).toHaveClass('space-y-3');
        }
    });
    it('replaces the email placeholder with the real server-off status', async () => {
        render(<EmailNotifications />);
        expect(screen.getByTestId('email-loading-space')).toBeInTheDocument();
        expect(await screen.findByTestId('email-server-off')).toBeVisible();
        await waitFor(() => expect(screen.queryByTestId('email-loading-space')).not.toBeInTheDocument());
    });
});
