import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const { push, refresh } = vi.hoisted(() => ({ push: vi.fn(), refresh: vi.fn() }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ push, refresh }) }));
vi.mock('@/lib/actions/auth.actions', () => ({ signInWithEmail: vi.fn(), verifyTwoFactorTotp: vi.fn() }));
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import { signInWithEmail, verifyTwoFactorTotp } from '@/lib/actions/auth.actions';
import { toast } from 'sonner';
import SignInForm from '@/components/forms/SignInForm';

const mockSignIn = vi.mocked(signInWithEmail);
const mockVerify = vi.mocked(verifyTwoFactorTotp);
const mockToastError = vi.mocked(toast.error);

const EMAIL = 'nico@gerarai.com';
const PASSWORD = 'supersecreta';

async function submitCredentials() {
    fireEvent.change(screen.getByLabelText('Email'), { target: { value: EMAIL } });
    fireEvent.change(screen.getByLabelText('Contraseña'), { target: { value: PASSWORD } });
    fireEvent.click(screen.getByRole('button', { name: 'Iniciar sesión' }));
    await waitFor(() => expect(mockSignIn).toHaveBeenCalledWith({ email: EMAIL, password: PASSWORD }));
}

describe('SignInForm: flujos de entrada', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        mockSignIn.mockResolvedValue({ success: true });
    });

    it('éxito: navega al destino saneado y refresca', async () => {
        render(<SignInForm passwordResetAvailable={false} />);
        await submitCredentials();
        await waitFor(() => expect(push).toHaveBeenCalledWith('/inicio'));
        expect(refresh).toHaveBeenCalled();
    });

    it('éxito con redirectTo explícito: vuelve a esa ruta interna', async () => {
        render(<SignInForm passwordResetAvailable={false} redirectTo="/portfolio" />);
        await submitCredentials();
        await waitFor(() => expect(push).toHaveBeenCalledWith('/portfolio'));
    });

    it('error del backend: toast con su mensaje, sin navegar', async () => {
        mockSignIn.mockResolvedValue({ success: false, error: 'Credenciales incorrectas' });
        render(<SignInForm passwordResetAvailable={false} />);
        await submitCredentials();
        await waitFor(() => expect(mockToastError).toHaveBeenCalledWith('No se pudo iniciar sesión', { description: 'Credenciales incorrectas' }));
        expect(push).not.toHaveBeenCalled();
    });

    it('error sin mensaje: cae al texto de credenciales no válidas', async () => {
        mockSignIn.mockResolvedValue({ success: false });
        render(<SignInForm passwordResetAvailable={false} />);
        await submitCredentials();
        await waitFor(() => expect(mockToastError).toHaveBeenCalledWith('No se pudo iniciar sesión', { description: 'Email o contraseña no válidos.' }));
    });

    it('excepción: mensaje del Error; lo que no es Error sale como inesperado', async () => {
        mockSignIn.mockRejectedValueOnce(new Error('red caída'));
        const { unmount } = render(<SignInForm passwordResetAvailable={false} />);
        await submitCredentials();
        await waitFor(() => expect(mockToastError).toHaveBeenCalledWith('No se pudo iniciar sesión', { description: 'red caída' }));
        unmount();
        mockSignIn.mockRejectedValueOnce('503 pelado');
        render(<SignInForm passwordResetAvailable={false} />);
        await submitCredentials();
        await waitFor(() => expect(mockToastError).toHaveBeenCalledWith('No se pudo iniciar sesión', { description: 'Ha ocurrido un error inesperado. Inténtalo de nuevo.' }));
    });

    it('cuenta pendiente: pantalla de estado, no el toast genérico; y se puede volver', async () => {
        mockSignIn.mockResolvedValue({ success: false, code: 'AUTH_ENDPOINT_ACCOUNT_PENDING' });
        render(<SignInForm passwordResetAvailable={false} />);
        await submitCredentials();
        expect(await screen.findByText('Cuenta creada. Pendiente de aprobación')).toBeInTheDocument();
        expect(mockToastError).not.toHaveBeenCalled();
        fireEvent.click(screen.getByRole('button', { name: 'Usar otra cuenta' }));
        expect(screen.getByText('Bienvenido de nuevo')).toBeInTheDocument();
    });

    it('cuenta rechazada: pantalla de rechazo, no el toast genérico', async () => {
        mockSignIn.mockResolvedValue({ success: false, code: 'ACCOUNT_REJECTED' });
        render(<SignInForm passwordResetAvailable={false} />);
        await submitCredentials();
        expect(await screen.findByText('Solicitud no aprobada')).toBeInTheDocument();
        expect(mockToastError).not.toHaveBeenCalled();
    });
});

describe('SignInForm: verificación en dos pasos', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        mockSignIn.mockResolvedValue({ success: false, twoFactorRequired: true });
    });

    async function reachTwoFactor() {
        render(<SignInForm passwordResetAvailable={false} />);
        await submitCredentials();
        return screen.findByText('Verificación en dos pasos');
    }

    async function submitCode(code = '123456') {
        fireEvent.change(screen.getByLabelText('Código de autenticación'), { target: { value: code } });
        fireEvent.click(screen.getByRole('button', { name: 'Verificar y entrar' }));
    }

    it('pide el código tras credenciales válidas y entra al verificar', async () => {
        mockVerify.mockResolvedValue({ success: true });
        await reachTwoFactor();
        await submitCode();
        await waitFor(() => expect(mockVerify).toHaveBeenCalledWith({ email: EMAIL, password: PASSWORD, totpCode: '123456' }));
        await waitFor(() => expect(push).toHaveBeenCalledWith('/inicio'));
        expect(refresh).toHaveBeenCalled();
    });

    it('código rechazado: toast de verificación fallida con el motivo', async () => {
        mockVerify.mockResolvedValue({ success: false, error: 'Código caducado' });
        await reachTwoFactor();
        await submitCode();
        await waitFor(() => expect(mockToastError).toHaveBeenCalledWith('Verificación fallida', { description: 'Código caducado' }));
        expect(push).not.toHaveBeenCalled();
    });

    it('código rechazado sin motivo y excepción: textos por defecto', async () => {
        mockVerify.mockResolvedValue({ success: false });
        await reachTwoFactor();
        await submitCode();
        await waitFor(() => expect(mockToastError).toHaveBeenCalledWith('Verificación fallida', { description: 'Código de autenticación no válido.' }));
        mockVerify.mockRejectedValueOnce(new Error('totp caído'));
        await submitCode();
        await waitFor(() => expect(mockToastError).toHaveBeenCalledWith('Verificación fallida', { description: 'totp caído' }));
    });

    it('mientras verifica, el botón queda deshabilitado con el texto de progreso', async () => {
        mockVerify.mockReturnValue(new Promise(() => {}));
        await reachTwoFactor();
        await submitCode();
        const button = await screen.findByRole('button', { name: 'Verificando…' });
        expect(button).toBeDisabled();
    });

    it('volver descarta las credenciales y regresa al formulario', async () => {
        await reachTwoFactor();
        fireEvent.click(screen.getByRole('button', { name: 'Volver a iniciar sesión' }));
        expect(screen.getByText('Bienvenido de nuevo')).toBeInTheDocument();
        // Al reentrar, las credenciales descartadas no disparan verificación.
        mockSignIn.mockResolvedValue({ success: true });
        await submitCredentials();
        await waitFor(() => expect(push).toHaveBeenCalledWith('/inicio'));
        expect(mockVerify).not.toHaveBeenCalled();
    });
});
