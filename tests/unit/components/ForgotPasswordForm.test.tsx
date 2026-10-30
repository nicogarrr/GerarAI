import React from 'react';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const { requestPasswordReset } = vi.hoisted(() => ({ requestPasswordReset: vi.fn() }));
vi.mock('@/lib/actions/password.actions', () => ({ requestPasswordReset }));

import ForgotPasswordForm from '@/components/auth/ForgotPasswordForm';

const fillEmailAndSubmit = (email: string) => {
    fireEvent.change(screen.getByLabelText('Email de la cuenta'), { target: { value: email } });
    const button = screen.getByRole('button', { name: /Enviar enlace de restablecimiento|Enviando…/ });
    fireEvent.submit(button.closest('form') as HTMLFormElement);
    return button;
};

describe('ForgotPasswordForm: sin SMTP configurado', () => {
    it('no muestra el formulario y ofrece Seguridad y el email de soporte', () => {
        render(<ForgotPasswordForm emailConfigured={false} supportEmail="soporte@gerar.ai" />);
        expect(screen.getByText(/El restablecimiento por correo no está disponible/)).toBeInTheDocument();
        expect(screen.getByRole('link', { name: 'Seguridad' })).toHaveAttribute('href', '/security');
        expect(screen.getByRole('link', { name: 'soporte@gerar.ai' })).toHaveAttribute('href', 'mailto:soporte@gerar.ai');
        expect(screen.queryByLabelText('Email de la cuenta')).not.toBeInTheDocument();
    });

    it('sin email de soporte apunta al centro de ayuda', () => {
        render(<ForgotPasswordForm emailConfigured={false} supportEmail="" />);
        expect(screen.getByRole('link', { name: 'centro de ayuda' })).toHaveAttribute('href', '/help');
        expect(screen.queryByRole('link', { name: /mailto:/ })).not.toBeInTheDocument();
    });
});

describe('ForgotPasswordForm: con SMTP configurado', () => {
    beforeEach(() => { requestPasswordReset.mockReset(); });

    it('pide el email de la cuenta con su etiqueta asociada', () => {
        render(<ForgotPasswordForm emailConfigured supportEmail="" />);
        const input = screen.getByLabelText('Email de la cuenta');
        expect(input).toHaveAttribute('type', 'email');
        expect(input).toHaveAttribute('required');
        expect(input).toHaveAttribute('autoComplete', 'email');
        expect(screen.getByRole('link', { name: 'Volver a iniciar sesión' })).toHaveAttribute('href', '/sign-in');
    });

    it('envía el email a la acción y muestra el mensaje como status, no alert', async () => {
        // La normalización (trim + minúsculas) la hace la acción en el servidor;
        // aquí importa que el componente la llame y muestre su mensaje.
        requestPasswordReset.mockResolvedValue({ success: true, message: 'Si ese email tiene cuenta, recibirás un enlace.' });
        render(<ForgotPasswordForm emailConfigured supportEmail="" />);
        fillEmailAndSubmit('nico@ejemplo.com');
        expect(await screen.findByRole('status')).toHaveTextContent('Si ese email tiene cuenta, recibirás un enlace.');
        expect(screen.queryByRole('alert')).not.toBeInTheDocument();
        expect(requestPasswordReset).toHaveBeenCalledWith('nico@ejemplo.com');
        expect(screen.getByRole('button', { name: 'Enviar enlace de restablecimiento' })).not.toBeDisabled();
    });

    it('deshabilita el botón mientras la solicitud está en vuelo', async () => {
        let resolveRequest: (value: { success: boolean; message: string }) => void = () => {};
        requestPasswordReset.mockImplementation(() => new Promise((resolve) => { resolveRequest = resolve; }));
        render(<ForgotPasswordForm emailConfigured supportEmail="" />);
        const button = fillEmailAndSubmit('nico@ejemplo.com');
        expect(button).toBeDisabled();
        expect(button).toHaveTextContent('Enviando…');
        await act(async () => {
            resolveRequest({ success: true, message: 'listo' });
        });
        expect(screen.getByRole('status')).toHaveTextContent('listo');
        expect(screen.getByRole('button', { name: 'Enviar enlace de restablecimiento' })).not.toBeDisabled();
    });

    it('un rechazo de la acción se muestra como alert con el mensaje del servidor', async () => {
        requestPasswordReset.mockResolvedValue({ success: false, message: 'El restablecimiento por correo no está configurado en este despliegue.' });
        render(<ForgotPasswordForm emailConfigured supportEmail="" />);
        fillEmailAndSubmit('nico@ejemplo.com');
        expect(await screen.findByRole('alert')).toHaveTextContent('no está configurado en este despliegue');
        expect(screen.queryByRole('status')).not.toBeInTheDocument();
    });

    it('una excepción de red muestra el mensaje genérico como alert y reactiva el botón', async () => {
        requestPasswordReset.mockImplementation(async () => { throw new Error('network down'); });
        render(<ForgotPasswordForm emailConfigured supportEmail="" />);
        fillEmailAndSubmit('nico@ejemplo.com');
        expect(await screen.findByRole('alert')).toHaveTextContent('No se pudo procesar la solicitud. Inténtalo de nuevo en unos minutos.');
        expect(screen.getByRole('button', { name: 'Enviar enlace de restablecimiento' })).not.toBeDisabled();
    });
});
