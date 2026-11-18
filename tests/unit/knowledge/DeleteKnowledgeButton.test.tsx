import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const m = vi.hoisted(() => ({ error: vi.fn() }));
vi.mock('sonner', () => ({ toast: { error: m.error } }));

import { DeleteKnowledgeButton } from '@/components/knowledge/DeleteKnowledgeButton';

describe('DeleteKnowledgeButton confirmation', () => {
    const props = { ariaLabel: 'Borrar documento de prueba', confirmTitle: 'Borrar documento', confirmDescription: 'Solo datos de prueba' };

    beforeEach(() => vi.clearAllMocks());

    it('never calls the action on open or cancel, then calls once on confirm', async () => {
        const onDelete = vi.fn().mockResolvedValue({ success: true });
        render(<DeleteKnowledgeButton {...props} onDelete={onDelete} />);
        fireEvent.click(screen.getByRole('button', { name: props.ariaLabel }));
        expect(onDelete).not.toHaveBeenCalled();
        fireEvent.click(screen.getByRole('button', { name: 'Cancelar' }));
        expect(onDelete).not.toHaveBeenCalled();
        fireEvent.click(screen.getByRole('button', { name: props.ariaLabel }));
        fireEvent.click(screen.getByRole('button', { name: 'Eliminar' }));
        await waitFor(() => expect(onDelete).toHaveBeenCalledOnce());
    });

    it('reports a rejected result and enables retry', async () => {
        const onDelete = vi.fn().mockResolvedValue({ success: false });
        render(<DeleteKnowledgeButton {...props} onDelete={onDelete} />);
        fireEvent.click(screen.getByRole('button', { name: props.ariaLabel }));
        fireEvent.click(screen.getByRole('button', { name: 'Eliminar' }));
        expect(await screen.findByRole('alert')).toBeVisible();
        expect(screen.getByRole('button', { name: props.ariaLabel })).toBeEnabled();
    });

    it('muestra el motivo del backend y lo envía al toast', async () => {
        const reason = 'La colección aún tiene documentos.';
        const onDelete = vi.fn().mockResolvedValue({ success: false, message: reason });
        render(<DeleteKnowledgeButton {...props} onDelete={onDelete} />);
        fireEvent.click(screen.getByRole('button', { name: props.ariaLabel }));
        fireEvent.click(screen.getByRole('button', { name: 'Eliminar' }));
        expect(await screen.findByRole('alert')).toHaveTextContent(reason);
        expect(m.error).toHaveBeenCalledWith(reason);
        expect(screen.getByRole('button', { name: props.ariaLabel })).toBeEnabled();
    });

    it('si la acción lanza, avisa y no deja el botón en «Eliminando…»', async () => {
        const onDelete = vi.fn().mockRejectedValue(new Error('boom'));
        render(<DeleteKnowledgeButton {...props} onDelete={onDelete} />);
        fireEvent.click(screen.getByRole('button', { name: props.ariaLabel }));
        fireEvent.click(screen.getByRole('button', { name: 'Eliminar' }));
        expect(await screen.findByRole('alert')).toHaveTextContent('No se pudo eliminar. Inténtalo de nuevo.');
        expect(m.error).toHaveBeenCalledWith('No se pudo eliminar. Inténtalo de nuevo.');
        expect(screen.getByRole('button', { name: props.ariaLabel })).toBeEnabled();
    });
});
