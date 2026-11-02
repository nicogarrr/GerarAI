import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { LocaleProvider } from '@/lib/i18n/client';

const { del, exp, toastError, toastSuccess } = vi.hoisted(() => ({ del: vi.fn(), exp: vi.fn(), toastError: vi.fn(), toastSuccess: vi.fn() }));
vi.mock('@/lib/actions/privacy.actions', () => ({ deleteAccount: del, exportAccountData: exp }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }) }));
vi.mock('sonner', () => ({ toast: { error: toastError, success: toastSuccess } }));

import PrivacySettings from '@/components/security/PrivacySettings';

beforeEach(() => { del.mockReset(); exp.mockReset(); toastError.mockReset(); toastSuccess.mockReset(); });

function submitDelete(locale: 'es' | 'en') {
    const { container } = render(<LocaleProvider locale={locale}><PrivacySettings email="a@b.c" /></LocaleProvider>);
    fireEvent.change(container.querySelector('#delete-confirmation')!, { target: { value: 'a@b.c' } });
    fireEvent.change(container.querySelector('#delete-password')!, { target: { value: 'secret' } });
    fireEvent.click(container.querySelector('#delete-understood')!);
    fireEvent.submit(container.querySelector('form')!);
}

it.each([
    ['Contraseña incorrecta. No se ha borrado nada.', 'Wrong password. Nothing has been deleted.'],
    ['Demasiados intentos. Espera un momento antes de volver a intentarlo.', 'Too many attempts. Wait a moment before retrying.'],
    ['No se pudo borrar la cuenta. No se ha eliminado nada. Inténtalo de nuevo.', 'The account could not be deleted. Nothing has been removed. Please retry.'],
    ['Tus datos de investigación se han borrado, pero la cuenta de acceso sigue activa. Vuelve a intentarlo para cerrarla definitivamente.', 'Your research data has been deleted, but your sign-in account is still active. Retry to close it for good.'],
])('in English a failed deletion explains «%s» in English', async (spanish, english) => {
    del.mockResolvedValue({ success: false, message: spanish });
    submitDelete('en');
    await waitFor(() => expect(toastError).toHaveBeenCalled());
    expect(toastError.mock.calls[0][1]).toEqual({ description: english });
});

it('in English the deletion confirmation reads in English', async () => {
    del.mockResolvedValue({ success: true, message: 'Cuenta y datos eliminados. Se han cerrado todas las sesiones.' });
    submitDelete('en');
    await waitFor(() => expect(toastSuccess).toHaveBeenCalled());
    expect(toastSuccess.mock.calls[0][1]).toEqual({ description: 'Account and data deleted. All sessions have been signed out.' });
});

it('in Spanish the message is shown as is', async () => {
    del.mockResolvedValue({ success: false, message: 'Contraseña incorrecta. No se ha borrado nada.' });
    submitDelete('es');
    await waitFor(() => expect(toastError).toHaveBeenCalled());
    expect(toastError.mock.calls[0][1]).toEqual({ description: 'Contraseña incorrecta. No se ha borrado nada.' });
});

it('in English a failed export explains the error in English', async () => {
    exp.mockRejectedValue(new Error('El servicio de datos no responde. Inténtalo de nuevo en unos minutos.'));
    render(<LocaleProvider locale="en"><PrivacySettings email="a@b.c" /></LocaleProvider>);
    fireEvent.click(screen.getAllByRole('button')[0]);
    await waitFor(() => expect(toastError).toHaveBeenCalled());
    expect(toastError.mock.calls[0][1]).toEqual({ description: 'The data service is not responding. Please retry in a few minutes.' });
});
