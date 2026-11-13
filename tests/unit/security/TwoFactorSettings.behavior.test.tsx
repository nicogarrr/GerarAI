import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { renderToString } from 'react-dom/server';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/lib/actions/auth.actions', () => ({
    enableTwoFactorTotp: vi.fn(), activateTwoFactorTotp: vi.fn(), disableTwoFactor: vi.fn(),
}));
vi.mock('@/lib/i18n/client', () => ({ useT: () => (key: string) => key }));
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock('next/dynamic', () => ({ default: () => () => <svg data-testid="synthetic-qr" /> }));

import TwoFactorSettings from '@/components/security/TwoFactorSettings';
import { activateTwoFactorTotp, disableTwoFactor, enableTwoFactorTotp } from '@/lib/actions/auth.actions';
import { toast } from 'sonner';

const enable = vi.mocked(enableTwoFactorTotp);
const activate = vi.mocked(activateTwoFactorTotp);
const disable = vi.mocked(disableTwoFactor);
const writeText = vi.fn();
// All enrollment values are synthetic fixtures, never usable credentials.
const fixture = {
    totpURI: 'otpauth://totp/unit-test?secret=%20unitTestFake%20',
    backupCodes: ['synthetic-backup-a', 'synthetic-backup-b'],
};

beforeEach(() => {
    vi.clearAllMocks();
    enable.mockReset().mockResolvedValue({ success: true, data: fixture });
    activate.mockReset().mockResolvedValue({ success: true });
    disable.mockReset().mockResolvedValue({ success: true });
    writeText.mockReset().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } });
});

async function submitPassword(button: string) {
    fireEvent.change(screen.getByLabelText('security.twoFactor.passwordLabel'), { target: { value: 'synthetic-test-input' } });
    fireEvent.click(screen.getByRole('button', { name: button }));
}

async function beginSetup() {
    render(<TwoFactorSettings initiallyEnabled={false} />);
    await submitPassword('security.twoFactor.enable');
    await screen.findByRole('img', { name: 'security.twoFactor.qrAria' });
}

async function submitCode(value = '123456') {
    fireEvent.change(screen.getByLabelText('security.twoFactor.codeLabel'), { target: { value } });
    fireEvent.click(screen.getByRole('button', { name: 'security.twoFactor.enable' }));
}

describe('two-factor settings behaviour', () => {
    it.each([false, true])('does not allow native credential submission before hydration (enabled=%s)', (initiallyEnabled) => {
        const container = document.createElement('div');
        container.innerHTML = renderToString(<TwoFactorSettings initiallyEnabled={initiallyEnabled} />);
        expect(container.querySelector('form')).toHaveAttribute('method', 'post');
        expect(container.querySelector('button[type="submit"]')).toBeDisabled();
    });

    it('validates the password locally before requesting enrollment', async () => {
        render(<TwoFactorSettings initiallyEnabled={false} />);
        fireEvent.click(screen.getByRole('button', { name: 'security.twoFactor.enable' }));
        expect(await screen.findByRole('alert')).toHaveTextContent('security.twoFactor.passwordRequired');
        expect(enable).not.toHaveBeenCalled();
    });

    it('shows enrollment without claiming that 2FA is already active', async () => {
        await beginSetup();
        expect(enable).toHaveBeenCalledExactlyOnceWith({ password: 'synthetic-test-input' });
        expect(screen.queryByText('security.twoFactor.enabledStatus')).not.toBeInTheDocument();
        expect(screen.getByLabelText('security.twoFactor.secretAria')).toHaveTextContent('UNITTESTFAKE');
        for (const code of fixture.backupCodes) expect(screen.getByText(code)).toBeVisible();
        expect(activate).not.toHaveBeenCalled();
    });

    it('copies only the displayed synthetic manual key and backup codes', async () => {
        await beginSetup();
        fireEvent.click(screen.getByRole('button', { name: 'security.twoFactor.copyKey' }));
        await waitFor(() => expect(toast.success).toHaveBeenCalledWith('security.twoFactor.keyCopied'));
        expect(writeText).toHaveBeenLastCalledWith('UNITTESTFAKE');
        fireEvent.click(screen.getByRole('button', { name: 'security.twoFactor.copyCodes' }));
        await waitFor(() => expect(toast.success).toHaveBeenCalledWith('security.twoFactor.codesCopied'));
        expect(writeText).toHaveBeenLastCalledWith('synthetic-backup-a\nsynthetic-backup-b');
    });

    it('reports clipboard failures without reporting a successful copy', async () => {
        writeText.mockRejectedValue(new Error('clipboard blocked'));
        await beginSetup();
        fireEvent.click(screen.getByRole('button', { name: 'security.twoFactor.copyKey' }));
        await waitFor(() => expect(toast.error).toHaveBeenCalledWith('security.twoFactor.keyCopyFailed'));
        fireEvent.click(screen.getByRole('button', { name: 'security.twoFactor.copyCodes' }));
        await waitFor(() => expect(toast.error).toHaveBeenCalledWith('security.twoFactor.codesCopyFailed'));
        expect(toast.success).not.toHaveBeenCalled();
    });

    it.each(['not a URL', 'https://unit.invalid/?secret=synthetic', 'otpauth://totp/unit-test', 'otpauth://totp/unit-test?secret=%20'])('does not invent a manual key from %s', async (totpURI) => {
        enable.mockResolvedValue({ success: true, data: { totpURI } });
        await beginSetup();
        expect(screen.queryByLabelText('security.twoFactor.secretAria')).not.toBeInTheDocument();
        expect(screen.queryByRole('button', { name: 'security.twoFactor.copyKey' })).not.toBeInTheDocument();
    });

    it.each([
        { success: false, error: 'synthetic enrollment failure' },
        { success: true, data: {} },
    ])('keeps the password form when enrollment has no usable URI: %j', async (response) => {
        enable.mockResolvedValue(response);
        render(<TwoFactorSettings initiallyEnabled={false} />);
        await submitPassword('security.twoFactor.enable');
        await waitFor(() => expect(toast.error).toHaveBeenCalledWith('security.twoFactor.enableFailed', {
            description: response.error ?? 'security.twoFactor.tryAgain',
        }));
        expect(screen.queryByRole('img')).not.toBeInTheDocument();
        expect(screen.getByRole('button', { name: 'security.twoFactor.enable' })).toBeEnabled();
    });

    it('requires six digits and does not call activation for an invalid code', async () => {
        await beginSetup();
        await submitCode('12x');
        expect(await screen.findByRole('alert')).toHaveTextContent('security.twoFactor.codeDigits');
        expect(activate).not.toHaveBeenCalled();
    });

    it('keeps enrollment after a rejected verification and allows retry', async () => {
        activate.mockResolvedValueOnce({ success: false });
        await beginSetup();
        await submitCode();
        await waitFor(() => expect(toast.error).toHaveBeenCalledWith('security.twoFactor.verifyFailed', {
            description: 'security.twoFactor.invalidCode',
        }));
        expect(screen.getByRole('img')).toBeVisible();
        expect(screen.queryByText('security.twoFactor.enabledStatus')).not.toBeInTheDocument();
        await submitCode();
        expect(await screen.findByText('security.twoFactor.enabledStatus')).toBeVisible();
        expect(activate).toHaveBeenLastCalledWith({ totpCode: '123456' });
        expect(screen.queryByRole('img')).not.toBeInTheDocument();
        expect(toast.success).toHaveBeenCalledWith('security.twoFactor.enabledToast');
    });

    it('can cancel setup without activating 2FA', async () => {
        await beginSetup();
        fireEvent.click(screen.getByRole('button', { name: 'security.twoFactor.cancel' }));
        expect(screen.getByLabelText('security.twoFactor.passwordLabel')).toBeVisible();
        expect(screen.queryByRole('img')).not.toBeInTheDocument();
        expect(activate).not.toHaveBeenCalled();
    });

    it('does not claim 2FA is disabled on a failed password check', async () => {
        disable.mockResolvedValueOnce({ success: false, error: 'synthetic wrong password' });
        render(<TwoFactorSettings initiallyEnabled />);
        await submitPassword('security.twoFactor.disable');
        await waitFor(() => expect(toast.error).toHaveBeenCalledWith('security.twoFactor.disableFailed', {
            description: 'synthetic wrong password',
        }));
        expect(screen.getByText('security.twoFactor.enabledStatus')).toBeVisible();
        expect(screen.getByRole('button', { name: 'security.twoFactor.disable' })).toBeEnabled();
        await submitPassword('security.twoFactor.disable');
        await screen.findByRole('button', { name: 'security.twoFactor.enable' });
        expect(screen.queryByText('security.twoFactor.enabledStatus')).not.toBeInTheDocument();
        expect(toast.success).toHaveBeenCalledWith('security.twoFactor.disabledToast');
    });

    it('blocks repeated enrollment submission until the server replies', async () => {
        let finish!: (value: Awaited<ReturnType<typeof enableTwoFactorTotp>>) => void;
        enable.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
        render(<TwoFactorSettings initiallyEnabled={false} />);
        await submitPassword('security.twoFactor.enable');
        const busy = await screen.findByRole('button', { name: 'security.twoFactor.generating' });
        expect(busy).toBeDisabled();
        fireEvent.click(busy);
        expect(enable).toHaveBeenCalledTimes(1);
        await act(async () => { finish({ success: true, data: fixture }); });
        expect(await screen.findByRole('img')).toBeVisible();
    });
});
