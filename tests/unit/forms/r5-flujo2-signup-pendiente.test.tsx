import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

// Auditoría de flujo r5 (11-nov): un alta nueva queda pendiente de
// aprobación. La pantalla de estado sustituía al formulario pero la URL
// seguía en /sign-up: al recargar (o al volver a la pestaña más tarde)
// reaparecía el formulario vacío, sin rastro de que el alta había ido bien.

const push = vi.fn();
vi.mock('next/navigation', () => ({ useRouter: () => ({ push, refresh: vi.fn() }) }));
const signUpWithEmail = vi.fn();
vi.mock('@/lib/actions/auth.actions', () => ({ signUpWithEmail: (...a: unknown[]) => signUpWithEmail(...a) }));
vi.mock('@/components/forms/AccessRequestForm', () => ({ default: () => <form aria-label="Pedir acceso a GerarAI" /> }));

import SignUpForm from '@/components/forms/SignUpForm';

async function submitValidForm() {
    render(<SignUpForm signUpOpen />);
    fireEvent.change(screen.getByLabelText('Nombre completo'), { target: { value: 'Nico Pruebas' } });
    fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'nico@example.com' } });
    fireEvent.change(screen.getByLabelText('Contraseña'), { target: { value: 'super-secreta-1' } });
    fireEvent.click(screen.getByRole('checkbox'));
    fireEvent.click(screen.getByRole('button', { name: 'Crear cuenta' }));
}

describe('Alta pendiente de aprobación: estado visible y estable', () => {
    let replaceState: ReturnType<typeof vi.spyOn>;
    beforeEach(() => {
        vi.clearAllMocks();
        replaceState = vi.spyOn(window.history, 'replaceState').mockImplementation(() => {});
    });
    afterEach(() => replaceState.mockRestore());

    it('pendiente: enseña la pantalla de cuenta pendiente y la URL pasa a /cuenta-pendiente', async () => {
        signUpWithEmail.mockResolvedValue({ success: true, accountStatus: 'pending' });
        await submitValidForm();
        expect(await screen.findByRole('heading', { name: 'Cuenta creada. Pendiente de aprobación' })).toBeInTheDocument();
        expect(screen.getByText(/te avisaremos por email/i)).toBeInTheDocument();
        expect(replaceState).toHaveBeenCalledWith(null, '', '/cuenta-pendiente?estado=pendiente');
        expect(push).not.toHaveBeenCalled();
    });

    it('sin accountStatus en la respuesta también es pendiente (con aprobación no hay sesión)', async () => {
        signUpWithEmail.mockResolvedValue({ success: true });
        await submitValidForm();
        await waitFor(() => expect(replaceState).toHaveBeenCalledWith(null, '', '/cuenta-pendiente?estado=pendiente'));
    });

    it('aprobada: entra directo a /inicio sin tocar la URL a mano', async () => {
        signUpWithEmail.mockResolvedValue({ success: true, accountStatus: 'approved' });
        await submitValidForm();
        await waitFor(() => expect(push).toHaveBeenCalledWith('/inicio'));
        expect(replaceState).not.toHaveBeenCalled();
    });
});
