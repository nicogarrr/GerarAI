import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/lib/actions/email-alerts.actions', () => ({
    getEmailAlertStatus: vi.fn(),
    setEmailAlertPreference: vi.fn(),
}));
vi.mock('@/lib/i18n/client', () => ({ useT: () => (key: string) => key }));

import EmailNotifications from '@/components/alerts/EmailNotifications';
import { getEmailAlertStatus, setEmailAlertPreference } from '@/lib/actions/email-alerts.actions';
import { PUSH_EVENT_TYPES } from '@/lib/alerts/push-event-types';
import { PUSH_TYPE_LABEL_KEYS } from '@/lib/alerts/push-type-labels';

const getStatus = vi.mocked(getEmailAlertStatus);
const setPreference = vi.mocked(setEmailAlertPreference);
const status = (enabled = false) => ({
    smtp: true,
    email: 'audit@example.invalid',
    preferences: PUSH_EVENT_TYPES.map((event_type) => ({ event_type, enabled })),
});

beforeEach(() => {
    getStatus.mockReset().mockResolvedValue(status());
    setPreference.mockReset().mockResolvedValue(undefined);
});

describe('email notification preferences', () => {
    it('does not offer opt-in while SMTP is unavailable', async () => {
        getStatus.mockResolvedValue({ ...status(), smtp: false });
        render(<EmailNotifications />);
        expect(await screen.findByTestId('email-server-off')).toHaveTextContent('alerts.email.serverOff');
        expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
        expect(screen.queryByTestId('email-bound-address')).not.toBeInTheDocument();
    });

    it('does not offer opt-in without the session-bound email', async () => {
        getStatus.mockResolvedValue({ ...status(), email: null });
        render(<EmailNotifications />);
        expect(await screen.findByTestId('email-no-binding')).toHaveTextContent('alerts.email.noBinding');
        expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
        expect(setPreference).not.toHaveBeenCalled();
    });

    it('renders every supported type with its saved opt-in and bound address', async () => {
        getStatus.mockResolvedValue(status(true));
        render(<EmailNotifications />);
        expect(await screen.findByTestId('email-bound-address')).toHaveTextContent('audit@example.invalid');
        expect(screen.getAllByRole('checkbox')).toHaveLength(PUSH_EVENT_TYPES.length);
        for (const eventType of PUSH_EVENT_TYPES) {
            expect(screen.getByRole('checkbox', { name: PUSH_TYPE_LABEL_KEYS[eventType] })).toBeChecked();
        }
        expect(setPreference).not.toHaveBeenCalled();
    });

    it('waits for the server and refreshed state rather than claiming a successful opt-in', async () => {
        let finish!: () => void;
        setPreference.mockImplementationOnce(() => new Promise<void>((resolve) => { finish = resolve; }));
        getStatus.mockResolvedValueOnce(status()).mockResolvedValueOnce(status(true));
        render(<EmailNotifications />);
        const checkbox = await screen.findByRole('checkbox', { name: 'alerts.push.types.earnings' });
        fireEvent.click(checkbox);
        expect(setPreference).toHaveBeenCalledExactlyOnceWith('earnings', true);
        expect(checkbox).not.toBeChecked();
        for (const item of screen.getAllByRole('checkbox')) expect(item).toBeDisabled();
        expect(getStatus).toHaveBeenCalledTimes(1);
        await act(async () => { finish(); });
        await waitFor(() => expect(checkbox).toBeChecked());
        expect(checkbox).toBeEnabled();
        expect(getStatus).toHaveBeenCalledTimes(2);
    });

    it('sends false to revoke a saved opt-in and uses the refreshed result', async () => {
        getStatus.mockResolvedValueOnce(status(true)).mockResolvedValueOnce(status(false));
        render(<EmailNotifications />);
        const checkbox = await screen.findByRole('checkbox', { name: 'alerts.push.types.insiders' });
        fireEvent.click(checkbox);
        await waitFor(() => expect(checkbox).not.toBeChecked());
        expect(setPreference).toHaveBeenCalledExactlyOnceWith('insiders', false);
        expect(checkbox).toBeEnabled();
    });

    it('shows a safe error and preserves the saved choice when a write fails', async () => {
        setPreference.mockRejectedValueOnce(new Error('private upstream details'));
        render(<EmailNotifications />);
        const checkbox = await screen.findByRole('checkbox', { name: 'alerts.push.types.earnings' });
        fireEvent.click(checkbox);
        expect(await screen.findByRole('alert')).toHaveTextContent('alerts.email.errorSave');
        expect(screen.getByRole('alert')).not.toHaveTextContent('private upstream details');
        expect(checkbox).not.toBeChecked();
        expect(checkbox).toBeEnabled();
        expect(getStatus).toHaveBeenCalledTimes(1);
    });

    it('clears a previous write error on retry and reloads saved preferences', async () => {
        setPreference.mockRejectedValueOnce(new Error('offline'));
        render(<EmailNotifications />);
        const checkbox = await screen.findByRole('checkbox', { name: 'alerts.push.types.earnings' });
        fireEvent.click(checkbox);
        await screen.findByRole('alert');
        getStatus.mockResolvedValueOnce(status(true));
        fireEvent.click(checkbox);
        await waitFor(() => expect(checkbox).toBeChecked());
        expect(screen.queryByRole('alert')).not.toBeInTheDocument();
        expect(setPreference).toHaveBeenCalledTimes(2);
    });
});
