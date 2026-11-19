import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/lib/actions/export.actions', () => ({ exportJournal: vi.fn() }));
vi.mock('@/lib/download-blob', () => ({ downloadBlob: vi.fn() }));
vi.mock('@/lib/toast', () => ({ showErrorToast: vi.fn() }));
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import { exportJournal } from '@/lib/actions/export.actions';
import { downloadBlob } from '@/lib/download-blob';
import { showErrorToast } from '@/lib/toast';
import { toast } from 'sonner';
import ExportView from '@/components/export/ExportView';

const mockExport = vi.mocked(exportJournal);
const mockDownload = vi.mocked(downloadBlob);
const mockShowError = vi.mocked(showErrorToast);
const mockSuccess = vi.mocked(toast.success);

const YEAR = new Date().getFullYear();
const SHORT = { content: 'fecha,decision\n2026-01-01,compra POOL', contentType: 'text/csv', filename: 'diario.csv' };

async function pickOption(comboboxName: string, optionName: string) {
    fireEvent.keyDown(screen.getByRole('combobox', { name: comboboxName }), { key: 'Enter' });
    fireEvent.click(await screen.findByRole('option', { name: optionName }));
}

describe('ExportView (diario de decisiones)', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        mockExport.mockResolvedValue(SHORT);
    });

    it('exporta el año en curso en CSV, descarga el blob y enseña la vista previa corta', async () => {
        const { container } = render(<ExportView />);
        fireEvent.click(screen.getByRole('button', { name: 'Exportar diario' }));
        await waitFor(() => expect(mockDownload).toHaveBeenCalled());
        expect(mockExport).toHaveBeenCalledWith(YEAR, 'csv');
        const pre = container.querySelector('pre');
        expect(pre?.textContent).toContain('fecha,decision');
        expect(pre?.textContent?.endsWith('…')).toBe(false);
        expect(mockSuccess).toHaveBeenCalledWith('Exportación completada: diario.csv');
    });

    it('vista previa de 2000+ caracteres: se marca el corte con elipsis', async () => {
        mockExport.mockResolvedValue({ ...SHORT, content: `cabecera${'x'.repeat(2500)}cola` });
        const { container } = render(<ExportView />);
        fireEvent.click(screen.getByRole('button', { name: 'Exportar diario' }));
        await waitFor(() => expect(mockDownload).toHaveBeenCalled());
        const pre = container.querySelector('pre');
        expect(pre?.textContent?.endsWith('…')).toBe(true);
        expect(pre?.textContent).not.toContain('cola');
    });

    it('cambiar año y formato: la acción recibe la selección', async () => {
        render(<ExportView />);
        await pickOption('Año', String(YEAR - 1));
        await pickOption('Formato', 'JSON (datos crudos)');
        fireEvent.click(screen.getByRole('button', { name: 'Exportar diario' }));
        await waitFor(() => expect(mockExport).toHaveBeenCalledWith(YEAR - 1, 'json'));
    });

    it('mientras exporta, el botón queda deshabilitado con el texto de progreso', async () => {
        mockExport.mockReturnValue(new Promise(() => {}));
        render(<ExportView />);
        fireEvent.click(screen.getByRole('button', { name: 'Exportar diario' }));
        const button = await screen.findByRole('button', { name: /Exportando/ });
        expect(button).toBeDisabled();
        expect(mockDownload).not.toHaveBeenCalled();
    });

    it('fallo de la acción: error por toast, sin descarga ni vista previa', async () => {
        mockExport.mockRejectedValue(new Error('down'));
        const { container } = render(<ExportView />);
        fireEvent.click(screen.getByRole('button', { name: 'Exportar diario' }));
        await waitFor(() => expect(mockShowError).toHaveBeenCalled());
        expect(mockDownload).not.toHaveBeenCalled();
        expect(container.querySelector('pre')).toBeNull();
    });
});
