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
