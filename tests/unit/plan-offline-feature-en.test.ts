import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import es from '@/lib/i18n/messages/es/plan.json';
import en from '@/lib/i18n/messages/en/plan.json';

// /plan sin backend en inglés decía «Tu plan is not available right now»:
// el nombre de la sección iba en castellano fijo dentro de la frase inglesa.
describe('/plan sin backend: nombre de la sección traducido', () => {
    it('la página no pasa un texto fijo a BackendOffline', () => {
        const src = readFileSync(join(process.cwd(), 'app/(root)/plan/page.tsx'), 'utf8');
        expect(src).not.toMatch(/<BackendOffline feature="/);
        expect(src).toContain("feature={t('plan.offlineFeature')}");
    });

    it('castellano igual que antes, inglés en inglés', () => {
        expect(es.offlineFeature).toBe('Tu plan');
        expect(en.offlineFeature).toBe('Your plan');
    });
});
