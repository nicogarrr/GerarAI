import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }) }));
vi.mock('@/lib/actions/auth.actions', () => ({ signInWithEmail: vi.fn(), verifyTwoFactorTotp: vi.fn(), signUpWithEmail: vi.fn() }));
vi.mock('@/components/forms/AccessRequestForm', () => ({ default: () => <form aria-label="Pedir acceso a GerarAI" /> }));
import SignInForm from '@/components/forms/SignInForm';
import SignUpForm from '@/components/forms/SignUpForm';
describe('Access wording matches the server signup mode', () => {
    it('links existing users to access requests when public signup is closed', () => {
        render(<SignInForm passwordResetAvailable={false} publicSignUpOpen={false} />);
        expect(screen.getByRole('link', { name: 'Pedir acceso' })).toHaveAttribute('href', '/sign-up');
        expect(screen.queryByRole('link', { name: 'Crear cuenta' })).not.toBeInTheDocument();
    });
    it('links to account creation when public signup is open', () => {
        render(<SignInForm passwordResetAvailable publicSignUpOpen />);
        expect(screen.getByRole('link', { name: 'Crear cuenta' })).toHaveAttribute('href', '/sign-up');
        expect(screen.getByRole('link', { name: '¿Has olvidado tu contraseña?' })).toHaveAttribute('href', '/forgot-password');
    });
    it('does not promise account creation on the closed request page', () => {
        render(<SignUpForm signUpOpen={false} />);
        expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Pide acceso a GerarAI');
        expect(screen.getByRole('form', { name: 'Pedir acceso a GerarAI' })).toBeInTheDocument();
        expect(screen.queryByLabelText('Contraseña')).not.toBeInTheDocument();
        expect(screen.getByRole('link', { name: 'Iniciar sesión' })).toHaveAttribute('href', '/sign-in');
    });
});

describe('El HTML previo a la hidratación no permite un submit nativo por GET', () => {
    // Regresión: los <form> de alta y entrada no declaraban method (GET por
    // defecto) y el botón nacía habilitado en el HTML; un submit antes de
    // hidratar navegaba a /sign-up?fullName=…&email=…&password=… con la
    // contraseña en la URL (historial, logs y referer).
    it('alta: form con method="post" y botón deshabilitado en el HTML inicial', async () => {
        const { renderToString } = await import('react-dom/server');
        const html = renderToString(<SignUpForm signUpOpen />);
        expect(html).toContain('method="post"');
        expect(html).toMatch(/<button(?=[^>]*type="submit")(?=[^>]*disabled)[^>]*>/);
    });
    it('entrada: form con method="post" y botón deshabilitado en el HTML inicial', async () => {
        const { renderToString } = await import('react-dom/server');
        const html = renderToString(<SignInForm passwordResetAvailable={false} />);
        expect(html).toContain('method="post"');
        expect(html).toMatch(/<button(?=[^>]*type="submit")(?=[^>]*disabled)[^>]*>/);
    });
    it('tras hidratar el botón de alta queda habilitado', () => {
        render(<SignUpForm signUpOpen />);
        expect(screen.getByRole('button', { name: 'Crear cuenta' })).toBeEnabled();
    });
});

describe('Recuperación y cambio de contraseña: mismo agujero de submit nativo', () => {
    it('recuperación: form con method="post" y botón deshabilitado en el HTML inicial', async () => {
        const { renderToString } = await import('react-dom/server');
        const { default: ForgotPasswordForm } = await import('@/components/auth/ForgotPasswordForm');
        const html = renderToString(<ForgotPasswordForm emailConfigured supportEmail="soporte@gerarai.com" />);
        expect(html).toContain('method="post"');
        expect(html).toMatch(/<button(?=[^>]*type="submit")(?=[^>]*disabled)[^>]*>/);
    });
    it('nueva contraseña: form con method="post" y botón deshabilitado en el HTML inicial', async () => {
        const { renderToString } = await import('react-dom/server');
        const { default: ResetPasswordForm } = await import('@/components/auth/ResetPasswordForm');
        const html = renderToString(<ResetPasswordForm token="token-de-prueba" linkError={false} />);
        expect(html).toContain('method="post"');
        expect(html).toMatch(/<button(?=[^>]*type="submit")(?=[^>]*disabled)[^>]*>/);
    });
});

describe('Formularios con contraseña o secreto en Ajustes/Seguridad: mismo agujero', () => {
    it('2FA: los tres forms llevan method="post" y botones deshabilitados en el HTML inicial', async () => {
        const { renderToString } = await import('react-dom/server');
        const { default: TwoFactorSettings } = await import('@/components/security/TwoFactorSettings');
        const html = renderToString(<TwoFactorSettings initiallyEnabled={false} />);
        for (const form of html.match(/<form[^>]*>/g) ?? []) expect(form).toContain('method="post"');
        for (const btn of html.match(/<button(?=[^>]*type="submit")[^>]*>/g) ?? []) expect(btn).toContain('disabled');
    });
    it('Cambio de contraseña: method="post" y botón deshabilitado', async () => {
        const { renderToString } = await import('react-dom/server');
        const { default: ChangePassword } = await import('@/components/security/ChangePassword');
        const html = renderToString(<ChangePassword />);
        expect(html).toContain('method="post"');
        expect(html).toMatch(/<button(?=[^>]*type="submit")(?=[^>]*disabled)[^>]*>/);
    });
    it('Borrado de cuenta: method="post" y botón deshabilitado', async () => {
        const { renderToString } = await import('react-dom/server');
        const { default: PrivacySettings } = await import('@/components/security/PrivacySettings');
        const html = renderToString(<PrivacySettings email="nico@example.com" />);
        expect(html).toContain('method="post"');
        expect(html).toMatch(/<button(?=[^>]*type="submit")(?=[^>]*disabled)[^>]*>/);
    });
    it('Conexión IBKR: method="post" y botón deshabilitado', async () => {
        const { renderToString } = await import('react-dom/server');
        const { default: IBKRConnectionForm } = await import('@/components/settings/IBKRConnectionForm');
        const empty = { connected: false, account_id: null, query_id: null, status: 'not_connected', message: '', complete_query: false, last_attempt_at: null, last_success_at: null, statement_date: null } as const;
        const html = renderToString(<IBKRConnectionForm initial={empty} />);
        expect(html).toContain('method="post"');
        expect(html).toMatch(/<button(?=[^>]*type="submit")(?=[^>]*disabled)[^>]*>/);
    });
    it('Ajustes LLM: method="post" y botón deshabilitado', async () => {
        const { renderToString } = await import('react-dom/server');
        const { default: LlmSettingsForm } = await import('@/components/settings/LlmSettingsForm');
        const initial = { source: 'platform', status: 'platform', provider: 'openrouter', base_url: null, model: 'm', fallback_model: null, reasoning_effort: null, enabled: true, configured: true, api_key_configured: false, api_key_last4: null, key_version: null, billing_scope: 'platform', encryption_available: true, message: '', providers: [{ id: 'openrouter', label: 'OpenRouter', models: [{ id: 'm', label: 'M' }] }] } as const;
        const html = renderToString(<LlmSettingsForm initial={initial as never} />);
        expect(html).toContain('method="post"');
        expect(html).toMatch(/<button(?=[^>]*type="submit")(?=[^>]*disabled)[^>]*>/);
    });
});
