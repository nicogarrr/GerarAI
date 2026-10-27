import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

const { preview, showError } = vi.hoisted(() => ({ preview: vi.fn(), showError: vi.fn() }));
vi.mock('@/lib/actions/taxes.actions', () => ({ previewTaxFiling: preview }));
vi.mock('@/lib/toast', () => ({ showErrorToast: showError }));
import TmePreviewForm from '@/components/taxes/TmePreviewForm';

function setup() {
    const onPreview = vi.fn();
    const onReset = vi.fn();
    render(<TmePreviewForm year={2025} onPreview={onPreview} onReset={onReset} />);
    return { onPreview, onReset };
}
function submit(value: string) {
    fireEvent.change(screen.getByLabelText(/TME de la base liquidable/), { target: { value } });
    fireEvent.click(screen.getByRole('button', { name: 'Calcular vista previa' }));
}

describe('TmePreviewForm validacion del TME', () => {
    beforeEach(() => vi.clearAllMocks());

    it.each(['', 'abc', '-1', '100,01', '19,123', '101'])('rechaza %j sin llamar al backend', (value) => {
        const { onPreview } = setup();
        submit(value);
        expect(screen.getByRole('alert')).toHaveTextContent('entre 0 y 100 %');
        expect(preview).not.toHaveBeenCalled();
        expect(onPreview).not.toHaveBeenCalled();
    });

    it.each([['19,00', 19], ['0', 0], ['100', 100], ['21,5', 21.5]])('acepta %s como %d', async (value, expected) => {
        preview.mockResolvedValue({ ok: true });
        const { onPreview } = setup();
        submit(value as string);
        await waitFor(() => expect(onPreview).toHaveBeenCalledWith({ ok: true }));
        expect(preview).toHaveBeenCalledWith(2025, expected);
    });

    it('tras aplicar permite quitar el TME y limpia el campo', async () => {
        preview.mockResolvedValue({});
        const { onReset } = setup();
        submit('19');
        const quitar = await screen.findByRole('button', { name: 'Quitar TME' });
        fireEvent.click(quitar);
        expect(onReset).toHaveBeenCalledOnce();
        expect((screen.getByLabelText(/TME de la base liquidable/) as HTMLInputElement).value).toBe('');
        expect(screen.queryByRole('button', { name: 'Quitar TME' })).not.toBeInTheDocument();
    });

    it('error del backend: toast y no se marca como aplicado', async () => {
        preview.mockRejectedValue(new Error('boom'));
        const { onPreview } = setup();
        submit('19');
        await waitFor(() => expect(showError).toHaveBeenCalled());
        expect(onPreview).not.toHaveBeenCalled();
        expect(screen.queryByRole('button', { name: 'Quitar TME' })).not.toBeInTheDocument();
    });

    it('un error de validacion se borra al volver a escribir', () => {
        setup();
        submit('xx');
        expect(screen.getByRole('alert')).toBeInTheDocument();
        fireEvent.change(screen.getByLabelText(/TME de la base liquidable/), { target: { value: '1' } });
        expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    });
});
