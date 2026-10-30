import React from 'react';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const { push, resetPasswordWithToken } = vi.hoisted(() => ({ push: vi.fn(), resetPasswordWithToken: vi.fn() }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ push }) }));
vi.mock('@/lib/actions/password.actions', () => ({ resetPasswordWithToken }));

import ResetPasswordForm from '@/components/auth/ResetPasswordForm';

const fillAndSubmit = (next: string, confirm: string) => {
    fireEvent.change(screen.getByLabelText('Contraseña nueva'), { target: { value: next } });
    fireEvent.change(screen.getByLabelText('Repite la contraseña nueva'), { target: { value: confirm } });
    const button = screen.getByRole('button', { name: /Guardar contraseña|Guardando…|Contraseña actualizada/ });
    fireEvent.submit(button.closest('form') as HTMLFormElement);
    return button;
};

describe('ResetPasswordForm: enlace inválido', () => {
    it('sin token no muestra el formulario y enlaza a pedir uno nuevo', () => {
        render(<ResetPasswordForm token="" linkError={false} />);
        expect(screen.getByText(/El enlace no es válido o ha caducado/)).toBeInTheDocument();
        expect(screen.getByRole('link', { name: 'restablecer contraseña' })).toHaveAttribute('href', '/forgot-password');
        expect(screen.queryByLabelText('Contraseña nueva')).not.toBeInTheDocument();
    });

    it('con linkError tampoco muestra el formulario aunque haya token', () => {
        render(<ResetPasswordForm token="tok123" linkError />);
        expect(screen.getByText(/El enlace no es válido o ha caducado/)).toBeInTheDocument();
        expect(screen.queryByLabelText('Contraseña nueva')).not.toBeInTheDocument();
    });
});

describe('ResetPasswordForm: con token válido', () => {
    beforeEach(() => {
        push.mockReset();
        resetPasswordWithToken.mockReset();
    });
    afterEach(() => vi.useRealTimers());

    it('los campos piden la contraseña nueva dos veces con mínimo 8 caracteres', () => {
        render(<ResetPasswordForm token="tok123" linkError={false} />);
        for (const label of ['Contraseña nueva', 'Repite la contraseña nueva']) {
            const input = screen.getByLabelText(label);
            expect(input).toHaveAttribute('type', 'password');
            expect(input).toHaveAttribute('minLength', '8');
            expect(input).toHaveAttribute('autoComplete', 'new-password');
        }
        expect(screen.getByText('Entre 8 y 128 caracteres.')).toBeInTheDocument();
        expect(screen.getByRole('link', { name: 'Ir a iniciar sesión' })).toHaveAttribute('href', '/sign-in');
    });

    it('envía token y ambas contraseñas a la acción', async () => {
        resetPasswordWithToken.mockResolvedValue({ success: false, message: 'Las contraseñas no coinciden.' });
        render(<ResetPasswordForm token="tok 123" linkError={false} />);
        fillAndSubmit('abcdefgh', 'abcdefgi');
        expect(await screen.findByRole('alert')).toHaveTextContent('Las contraseñas no coinciden.');
        expect(resetPasswordWithToken).toHaveBeenCalledWith({ token: 'tok 123', newPassword: 'abcdefgh', confirmPassword: 'abcdefgi' });
    });

    it('tras guardar con éxito bloquea el formulario y redirige a /sign-in', async () => {
        vi.useFakeTimers();
        resetPasswordWithToken.mockResolvedValue({ success: true, message: 'Contraseña actualizada correctamente.' });
        render(<ResetPasswordForm token="tok123" linkError={false} />);
        fillAndSubmit('abcdefgh', 'abcdefgh');
        await act(async () => {});
        expect(screen.getByRole('status')).toHaveTextContent('Contraseña actualizada correctamente.');
        expect(screen.queryByRole('alert')).not.toBeInTheDocument();
        expect(screen.getByLabelText('Contraseña nueva')).toBeDisabled();
        expect(screen.getByRole('button', { name: 'Contraseña actualizada' })).toBeDisabled();
        expect(push).not.toHaveBeenCalled();
        act(() => { vi.advanceTimersByTime(1300); });
        expect(push).toHaveBeenCalledWith('/sign-in');
    });

    it('un fallo de la acción no redirige y deja el formulario editable', async () => {
        vi.useFakeTimers();
        resetPasswordWithToken.mockResolvedValue({ success: false, message: 'El enlace ha caducado.' });
        render(<ResetPasswordForm token="tok123" linkError={false} />);
        fillAndSubmit('abcdefgh', 'abcdefgh');
        await act(async () => {});
        expect(screen.getByRole('alert')).toHaveTextContent('El enlace ha caducado.');
        expect(screen.getByLabelText('Contraseña nueva')).not.toBeDisabled();
        act(() => { vi.advanceTimersByTime(5000); });
        expect(push).not.toHaveBeenCalled();
    });

    it('una excepción de red muestra el mensaje genérico como alert', async () => {
        resetPasswordWithToken.mockImplementation(async () => { throw new Error('network down'); });
        render(<ResetPasswordForm token="tok123" linkError={false} />);
        fillAndSubmit('abcdefgh', 'abcdefgh');
        expect(await screen.findByRole('alert')).toHaveTextContent('No se pudo guardar la contraseña. Inténtalo de nuevo.');
    });
});
