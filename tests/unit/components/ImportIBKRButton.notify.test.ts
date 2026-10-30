import { beforeEach, describe, expect, it, vi } from 'vitest';

const t = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn(), warning: vi.fn() }));
vi.mock('sonner', () => ({ toast: t }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ refresh: vi.fn() }) }));
vi.mock('@/lib/actions/portfolio.actions', () => ({ importFromIBKR: vi.fn(), importIBKRCsv: vi.fn(), importIBKRXml: vi.fn() }));
import { notifyImportResult } from '@/components/portfolio/ImportIBKRButton';

beforeEach(() => vi.clearAllMocks());

describe('notifyImportResult (Flex y fichero, mismos avisos)', () => {
    it('con 8 filas con avisos dice cuántas hay y cuántas quedan sin mostrar', () => {
        const errors = Array.from({ length: 8 }, (_, i) => `fila ${i + 1}: sin fecha`);
        expect(notifyImportResult({ status: 'imported', positions_imported: 1, row_errors: errors })).toBe(true);
        const [title, opts] = t.warning.mock.calls[0];
        expect(title).toMatch(/^8 filas con avisos\. Primera: fila 1: sin fecha/);
        expect(opts.description).toMatch(/3 avisos más$/);
    });
    it('un rechazo sin motivo no muestra el estado interno en inglés', () => {
        expect(notifyImportResult({ status: 'rejected' })).toBe(false);
        const [msg] = t.error.mock.calls[0];
        expect(msg).not.toMatch(/rejected/);
        expect(msg).toMatch(/La importación no se completó/);
    });
    it('un rechazo con motivo muestra el motivo del backend', () => {
        notifyImportResult({ status: 'rejected', message: 'Token Flex caducado' });
        expect(t.error.mock.calls[0][0]).toBe('Token Flex caducado');
    });
});
