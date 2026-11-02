import { readFileSync } from 'node:fs';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const t = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn(), warning: vi.fn() }));
vi.mock('sonner', () => ({ toast: t }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ refresh: vi.fn() }) }));
vi.mock('@/lib/actions/portfolio.actions', () => ({ importFromIBKR: vi.fn(), importIBKRCsv: vi.fn(), importIBKRXml: vi.fn() }));
import { notifyImportResult } from '@/components/portfolio/ImportIBKRButton';
import { createTranslator } from '@/lib/i18n/translate';
import { createFormatters } from '@/lib/format';

// Frase real de ibkr_import_service.py (identity_warning), leída del .py: si cambia, el test lo nota.
const PY = readFileSync('data-engine/app/services/ibkr_import_service.py', 'utf8');
const BLOCK = PY.match(/identity_warning = \(\s*((?:"[^"]*"\s*)+)\)/);
const WARNING = [...(BLOCK?.[1] ?? '').matchAll(/"([^"]*)"/g)].map((m) => m[1]).join('');

beforeEach(() => vi.clearAllMocks());

describe('importación CSV: aviso de CSV sin identificador en el idioma de la pantalla', () => {
    it('lee la frase del backend', () => {
        expect(WARNING).toMatch(/^CSV sin identificador de operación: .*usa tradeID para importarlos sin ambigüedad\.$/);
    });

    it('en inglés, el aviso sale en inglés', () => {
        notifyImportResult({ status: 'imported', trades_imported: 3, identity_warning: WARNING }, createTranslator('en'), createFormatters('en'));
        const [msg] = t.warning.mock.calls[0];
        expect(msg).toMatch(/^CSV without a trade identifier: .*tradeID/);
        expect(msg).not.toMatch(/sin identificador|operación|archivo/);
    });

    it('en castellano, la frase del backend tal cual', () => {
        notifyImportResult({ status: 'imported', trades_imported: 3, identity_warning: WARNING });
        expect(t.warning.mock.calls[0][0]).toBe(WARNING);
    });

    it('un aviso distinto pasa tal cual', () => {
        notifyImportResult({ status: 'imported', trades_imported: 3, identity_warning: 'Otro aviso' }, createTranslator('en'), createFormatters('en'));
        expect(t.warning.mock.calls[0][0]).toBe('Otro aviso');
    });
});
