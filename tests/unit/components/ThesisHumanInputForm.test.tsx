/**
 * El campo «Valor» del supuesto humano acepta números es-ES (coma decimal,
 * punto de miles) y rechaza los ambiguos con un mensaje útil, en lugar de
 * la burbuja nativa en inglés del type=number o un NaN silencioso.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';

const submit = vi.fn();
vi.mock('@/lib/actions/research.actions', () => ({
    submitThesisHumanInput: (...args: unknown[]) => submit(...args),
}));

import ThesisHumanInputForm from '@/components/research/ThesisHumanInputForm';

function fillForm(value: string) {
    render(<ThesisHumanInputForm ticker="AAPL" />);
    fireEvent.click(screen.getByText('Aportar un supuesto humano'));
    fireEvent.change(screen.getByLabelText(/Clave del driver/), { target: { value: 'revenue' } });
    fireEvent.change(screen.getByLabelText(/Ejercicio fiscal/), { target: { value: '2027' } });
    fireEvent.change(screen.getByLabelText(/Valor/), { target: { value } });
    fireEvent.change(screen.getByLabelText(/Fuente o referencia/), { target: { value: 'Presentación Q4' } });
    fireEvent.change(screen.getByLabelText(/Justificación/), { target: { value: 'Guidance de la directiva' } });
}

beforeEach(() => submit.mockReset());

it('acepta «1250,5» (coma decimal) y envía el valor canónico 1250.5', async () => {
    submit.mockResolvedValue(undefined);
    fillForm('1250,5');
    fireEvent.click(screen.getByRole('button', { name: /Guardar supuesto/ }));
    await waitFor(() => expect(submit).toHaveBeenCalledOnce());
    const formData = submit.mock.calls[0][1] as FormData;
    expect(formData.get('value')).toBe('1250.5');
});

it('acepta «1.234,56» (miles con punto)', async () => {
    submit.mockResolvedValue(undefined);
    fillForm('1.234,56');
    fireEvent.click(screen.getByRole('button', { name: /Guardar supuesto/ }));
    await waitFor(() => expect(submit).toHaveBeenCalledOnce());
    expect((submit.mock.calls[0][1] as FormData).get('value')).toBe('1234.56');
});

it('rechaza «1,234» ambiguo con mensaje es-ES y no llama a la acción', async () => {
    fillForm('1,234');
    fireEvent.click(screen.getByRole('button', { name: /Guardar supuesto/ }));
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent(/ambiguo/i));
    expect(submit).not.toHaveBeenCalled();
});
