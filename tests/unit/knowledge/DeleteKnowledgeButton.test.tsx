import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { DeleteKnowledgeButton } from '@/components/knowledge/DeleteKnowledgeButton';
describe('DeleteKnowledgeButton confirmation', () => {
    const props = { ariaLabel: 'Borrar documento de prueba', confirmTitle: 'Borrar documento', confirmDescription: 'Solo datos de prueba' };
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
});
