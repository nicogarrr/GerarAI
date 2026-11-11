import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

// Regresión (#5357): el alta pidió objetivo de inversión, tolerancia al
// riesgo y sector preferido durante meses y NINGÚN consumidor los leía
// (verificado con grep en front y back; solo reaparecían en la exportación
// GDPR). Se quitaron del formulario y del payload. Estos tests ponen en rojo
// cualquier reinserción: el select requerido reaparece en el render o bloquea
// el envío válido, y un payload que vuelva a incluirlos rompe la igualdad.

vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }) }));
const signUpWithEmail = vi.fn();
vi.mock('@/lib/actions/auth.actions', () => ({ signUpWithEmail: (...a: unknown[]) => signUpWithEmail(...a) }));
vi.mock('@/components/forms/AccessRequestForm', () => ({ default: () => <form aria-label="Pedir acceso a GerarAI" /> }));

import SignUpForm from '@/components/forms/SignUpForm';

describe('Alta sin perfil inversor (#5357)', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        signUpWithEmail.mockResolvedValue({ success: true, accountStatus: 'pending' });
    });

    it('no renderiza objetivo, tolerancia ni sector; quedan nombre, email, contraseña, país y términos', () => {
        render(<SignUpForm signUpOpen />);
        for (const label of ['Objetivo de inversión', 'Tolerancia al riesgo', 'Sector preferido']) {
            expect(screen.queryByText(label)).not.toBeInTheDocument();
        }
        // Un combobox/select de onboarding tampoco puede quedar oculto: solo
        // el selector de país (combobox) sigue presente.
        expect(screen.queryByRole('combobox', { name: /Objetivo/i })).not.toBeInTheDocument();
        expect(screen.queryByRole('combobox', { name: /Tolerancia/i })).not.toBeInTheDocument();
        expect(screen.queryByRole('combobox', { name: /Sector/i })).not.toBeInTheDocument();
        expect(screen.getByLabelText('Nombre completo')).toBeInTheDocument();
        expect(screen.getByLabelText('Email')).toBeInTheDocument();
        expect(screen.getByLabelText('Contraseña')).toBeInTheDocument();
        expect(screen.getByText('País')).toBeInTheDocument();
        expect(screen.getByRole('checkbox')).toBeInTheDocument();
    });

    it('alta válida con solo nombre/email/contraseña/país/términos y payload sin los 3 campos', async () => {
        render(<SignUpForm signUpOpen />);
        fireEvent.change(screen.getByLabelText('Nombre completo'), { target: { value: 'Nico Pruebas' } });
        fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'nico@example.com' } });
        fireEvent.change(screen.getByLabelText('Contraseña'), { target: { value: 'super-secreta-1' } });
        fireEvent.click(screen.getByRole('checkbox'));
        // Un select requerido reinsertado bloquearía este envío (validación
        // required de react-hook-form) y el mock nunca sería llamado: rojo.
        fireEvent.click(screen.getByRole('button', { name: 'Crear cuenta' }));
        await waitFor(() => expect(signUpWithEmail).toHaveBeenCalledTimes(1));
        const payload = signUpWithEmail.mock.calls[0][0] as Record<string, unknown>;
        expect(payload).toEqual({
            fullName: 'Nico Pruebas',
            email: 'nico@example.com',
            password: 'super-secreta-1',
            country: 'ES',
            acceptTerms: true,
        });
        for (const field of ['investmentGoals', 'riskTolerance', 'preferredIndustry']) {
            expect(payload).not.toHaveProperty(field);
        }
    });
});
