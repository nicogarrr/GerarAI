import { beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';

const h = vi.hoisted(() => ({
    refresh: vi.fn(), success: vi.fn(), error: vi.fn(), warning: vi.fn(), showError: vi.fn(),
    importIbkr: vi.fn(), importCsv: vi.fn(), importXml: vi.fn(), sync: vi.fn(), updateAll: vi.fn(),
}));
vi.mock('next/navigation', () => ({ useRouter: () => ({ refresh: h.refresh }) }));
vi.mock('sonner', () => ({ toast: { success: h.success, error: h.error, warning: h.warning } }));
vi.mock('@/lib/toast', () => ({ showErrorToast: h.showError }));
vi.mock('@/lib/actions/portfolio.actions', () => ({
    importFromIBKR: h.importIbkr, importIBKRCsv: h.importCsv, importIBKRXml: h.importXml,
    syncPortfolioDividends: h.sync, updateAllPortfolioPrices: h.updateAll,
}));
import ImportIBKRButton from '@/components/portfolio/ImportIBKRButton';
import SyncDividendsButton from '@/components/portfolio/SyncDividendsButton';
import RefreshPortfolioButton from '@/components/portfolio/RefreshPortfolioButton';

beforeEach(() => vi.clearAllMocks());

describe('ImportIBKRButton (Flex)', () => {
    it('importacion completa: resumen con recuentos y refresco', async () => {
        h.importIbkr.mockResolvedValue({ status: 'imported', positions_imported: 12, trades_imported: 1500, dividends_imported: 30,
            fees_imported: 4, cash_imported: 2, duplicate_trades: 7, rows_skipped: 3 });
        render(<ImportIBKRButton userId="u1" />);
        fireEvent.click(screen.getByRole('button', { name: /Importar IBKR/ }));
        await waitFor(() => expect(h.success).toHaveBeenCalled());
        const msg = h.success.mock.calls[0][0] as string;
        expect(msg).toContain('12 posiciones');
        expect(msg).toMatch(/1\.?500 operaciones/);
        expect(msg).toContain('7 operaciones ya importadas');
        expect(msg).toContain('3 filas omitidas');
        expect(h.importIbkr).toHaveBeenCalledWith('u1');
        expect(h.refresh).toHaveBeenCalled();
    });

    it('estado distinto de imported: error con mensaje del backend y SIN toast de exito ni refresh', async () => {
        h.importIbkr.mockResolvedValue({ status: 'failed', message: 'Token Flex caducado' });
        render(<ImportIBKRButton userId="u1" />);
        fireEvent.click(screen.getByRole('button', { name: /Importar IBKR/ }));
        await waitFor(() => expect(h.error).toHaveBeenCalledWith('Token Flex caducado', { duration: 10000 }));
        expect(h.success).not.toHaveBeenCalled();
        expect(h.refresh).not.toHaveBeenCalled();
    });

    it('sin mensaje: aviso en español, sin el estado interno', async () => {
        h.importIbkr.mockResolvedValue({ status: 'pending' });
        render(<ImportIBKRButton userId="u1" />);
        fireEvent.click(screen.getByRole('button', { name: /Importar IBKR/ }));
        await waitFor(() => expect(h.error).toHaveBeenCalledWith(expect.stringMatching(/^La importación no se completó/), { duration: 10000 }));
    });

    it('avisos de identidad y filas con avisos (cuántas y detalle, como al subir fichero)', async () => {
        h.importIbkr.mockResolvedValue({ status: 'imported', positions_imported: 1, identity_warning: 'Cuenta distinta', row_errors: ['a', 'b', 'c', 'd'] });
        render(<ImportIBKRButton userId="u1" />);
        fireEvent.click(screen.getByRole('button', { name: /Importar IBKR/ }));
        await waitFor(() => expect(h.warning).toHaveBeenCalledTimes(2));
        expect(h.warning).toHaveBeenCalledWith('Cuenta distinta');
        expect(h.warning).toHaveBeenCalledWith('4 filas con avisos. Primera: a', { duration: 12000, description: 'a\nb\nc\nd' });
    });

    it('recuentos no numericos no se inventan: faltantes son 0 y NaN se ignora', async () => {
        h.importIbkr.mockResolvedValue({ status: 'imported', positions_imported: 2, trades_imported: Number.NaN, dividends_imported: '5' });
        render(<ImportIBKRButton userId="u1" />);
        fireEvent.click(screen.getByRole('button', { name: /Importar IBKR/ }));
        await waitFor(() => expect(h.success).toHaveBeenCalled());
        expect(h.success.mock.calls[0][0]).toContain('2 posiciones, 0 operaciones, 0 dividendos');
    });

    it('excepcion: showErrorToast', async () => {
        h.importIbkr.mockRejectedValue(new Error('net'));
        render(<ImportIBKRButton userId="u1" />);
        fireEvent.click(screen.getByRole('button', { name: /Importar IBKR/ }));
        await waitFor(() => expect(h.showError).toHaveBeenCalled());
    });

    function upload(name: string, content: string) {
        const input = document.querySelector('input[type=file]') as HTMLInputElement;
        const file = new File([content], name);
        Object.defineProperty(file, 'text', { value: async () => content });
        fireEvent.change(input, { target: { files: [file] } });
    }

    it('fichero .CSV (mayusculas) va al importador CSV con el texto', async () => {
        h.importCsv.mockResolvedValue({ status: 'imported', trades_imported: 3 });
        render(<ImportIBKRButton userId="u1" />);
        upload('Trades.CSV', 'symbol,action');
        await waitFor(() => expect(h.importCsv).toHaveBeenCalledWith('u1', 'symbol,action'));
        expect(h.importXml).not.toHaveBeenCalled();
        expect(h.success.mock.calls[0][0]).toBe('IBKR CSV: 3 operaciones importadas');
    });

    it('otro fichero va al importador XML; filas con avisos cuenta y muestra la primera', async () => {
        h.importXml.mockResolvedValue({ status: 'imported', positions_imported: 1, row_errors: ['x1', 'x2'] });
        render(<ImportIBKRButton userId="u1" />);
        upload('flex.xml', '<x/>');
        await waitFor(() => expect(h.importXml).toHaveBeenCalledWith('u1', '<x/>'));
        await waitFor(() => expect(h.warning).toHaveBeenCalledWith('2 filas con avisos. Primera: x1', { duration: 12000, description: 'x1\nx2' }));
    });

    it('subida rechazada por el backend: error y sin exito', async () => {
        h.importXml.mockResolvedValue({ status: 'invalid', message: 'XML no valido' });
        render(<ImportIBKRButton userId="u1" />);
        upload('flex.xml', 'bad');
        await waitFor(() => expect(h.error).toHaveBeenCalledWith('XML no valido', { duration: 10000 }));
        expect(h.success).not.toHaveBeenCalled();
    });

    it('sin fichero seleccionado no llama a nada', () => {
        render(<ImportIBKRButton userId="u1" />);
        fireEvent.change(document.querySelector('input[type=file]') as HTMLInputElement, { target: { files: [] } });
        expect(h.importCsv).not.toHaveBeenCalled();
        expect(h.importXml).not.toHaveBeenCalled();
    });

    it('muchas filas con avisos: el detalle lista 5 y cuenta el resto', async () => {
        const errors = Array.from({ length: 8 }, (_, i) => `Fila ${i + 2}: error`);
        h.importCsv.mockResolvedValue({ status: 'imported', trades_imported: 1, row_errors: errors });
        render(<ImportIBKRButton userId="u1" />);
        upload('t.csv', 'symbol');
        await waitFor(() => expect(h.warning).toHaveBeenCalled());
        const detail = h.warning.mock.calls[0][1].description as string;
        expect(detail.split('\n')).toHaveLength(6);
        expect(detail).toContain('Fila 6: error');
        expect(detail).not.toContain('Fila 7: error');
        expect(detail).toContain('3 avisos más');
    });

    function uploadSized(name: string, size: number) {
        const input = document.querySelector('input[type=file]') as HTMLInputElement;
        const file = new File(['x'], name);
        Object.defineProperty(file, 'size', { value: size });
        fireEvent.change(input, { target: { files: [file] } });
    }

    it('fichero de mas de 3,5 MB: aviso con el tamaño y no se sube', () => {
        render(<ImportIBKRButton userId="u1" />);
        uploadSized('flex.xml', 6 * 1024 * 1024);
        expect(h.error).toHaveBeenCalledWith(expect.stringMatching(/pesa 6 MB y el máximo es 3,5 MB/), { duration: 10000 });
        expect(h.importXml).not.toHaveBeenCalled();
    });

    it('fichero vacio: aviso y no se sube', () => {
        render(<ImportIBKRButton userId="u1" />);
        uploadSized('t.csv', 0);
        expect(h.error).toHaveBeenCalledWith('El fichero está vacío.', { duration: 10000 });
        expect(h.importCsv).not.toHaveBeenCalled();
    });

    it('fichero ilegible: error visible y el boton vuelve a estar disponible', async () => {
        render(<ImportIBKRButton userId="u1" />);
        const input = document.querySelector('input[type=file]') as HTMLInputElement;
        const file = new File(['x'], 'a.xml');
        Object.defineProperty(file, 'text', { value: () => Promise.reject(new Error('NotReadableError')) });
        fireEvent.change(input, { target: { files: [file] } });
        await waitFor(() => expect(h.showError).toHaveBeenCalled());
        expect(screen.getByRole('button', { name: /Subir fichero/ })).not.toBeDisabled();
    });

    it('excepcion al subir', async () => {
        h.importXml.mockRejectedValue(new Error('boom'));
        render(<ImportIBKRButton userId="u1" />);
        upload('a.xml', 'x');
        await waitFor(() => expect(h.showError).toHaveBeenCalled());
    });
});

describe('SyncDividendsButton', () => {
    it('sincroniza, refresca y avisa', async () => {
        h.sync.mockResolvedValue(undefined);
        render(<SyncDividendsButton userId="u2" />);
        fireEvent.click(screen.getByRole('button', { name: /Sincronizar dividendos/ }));
        await waitFor(() => expect(h.success).toHaveBeenCalledWith('Dividendos sincronizados'));
        expect(h.sync).toHaveBeenCalledWith('u2');
        expect(h.refresh).toHaveBeenCalled();
    });

    it('fallo: toast de error con reintento, sin exito', async () => {
        h.sync.mockRejectedValue(new Error('x'));
        render(<SyncDividendsButton userId="u2" />);
        fireEvent.click(screen.getByRole('button', { name: /Sincronizar dividendos/ }));
        await waitFor(() => expect(h.showError).toHaveBeenCalled());
        expect(h.showError.mock.calls[0][1]).toHaveProperty('onRetry');
        expect(h.success).not.toHaveBeenCalled();
        expect(screen.getByRole('button')).not.toBeDisabled();
    });
});

describe('RefreshPortfolioButton', () => {
    it('el toast no promete precios nuevos', async () => {
        h.updateAll.mockResolvedValue(undefined);
        render(<RefreshPortfolioButton userId="u3" />);
        fireEvent.click(screen.getByRole('button', { name: 'Actualizar lecturas' }));
        await waitFor(() => expect(h.success).toHaveBeenCalledWith('Lecturas de cartera actualizadas'));
        expect(h.updateAll).toHaveBeenCalledWith('u3');
        expect(h.refresh).toHaveBeenCalled();
    });

    it('queda ocupado 1 s tras terminar', async () => {
        vi.useFakeTimers();
        try {
            h.updateAll.mockResolvedValue(undefined);
            render(<RefreshPortfolioButton userId="u3" />);
            fireEvent.click(screen.getByRole('button'));
            await act(async () => { await Promise.resolve(); });
            expect(screen.getByRole('button')).toBeDisabled();
            await act(async () => { vi.advanceTimersByTime(1000); });
            expect(screen.getByRole('button')).not.toBeDisabled();
        } finally { vi.useRealTimers(); }
    });

    it('fallo: error, sin exito', async () => {
        h.updateAll.mockRejectedValue(new Error('x'));
        render(<RefreshPortfolioButton userId="u3" />);
        fireEvent.click(screen.getByRole('button'));
        await waitFor(() => expect(h.showError).toHaveBeenCalled());
        expect(h.success).not.toHaveBeenCalled();
        expect(h.refresh).not.toHaveBeenCalled();
    });
});
