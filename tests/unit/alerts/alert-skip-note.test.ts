import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

import { alertSkipNote } from '@/lib/alerts/skip-note';
// @ts-expect-error TS5097: import con extensión para el runner de node.
import { translateMessage } from '@/lib/i18n/translate.ts';

describe('alertSkipNote', () => {
    it('explains a rule skipped because a trading session is missing (#3274)', () => {
        expect(alertSkipNote('skipped_session_gap')).toMatch(/falta una sesión/);
    });

    it('keeps the stale-observation note', () => {
        expect(alertSkipNote('skipped_stale_observation')).toBe('dato desactualizado');
    });

    it('translates the notes to English instead of hardcoding Spanish', () => {
        const enT = (key: Parameters<typeof translateMessage>[1]) => translateMessage('en', key);
        expect(alertSkipNote('skipped_stale_observation', enT)).toBe('data is out of date');
        expect(alertSkipNote('skipped_session_gap', enT)).toMatch(/trading session is missing/);
    });

    it('adds nothing for a normal evaluation', () => {
        expect(alertSkipNote('ok')).toBeNull();
        expect(alertSkipNote(undefined)).toBeNull();
    });

    it('is what the alerts card renders for every skip status', () => {
        const src = readFileSync(join(process.cwd(), 'components/alerts/AlertsManager.tsx'), 'utf8');
        // Con el traductor del locale elegido: sin `ti` la nota saldría
        // siempre en español, también en la UI en inglés.
        expect(src).toContain('alertSkipNote(alert.lastResultStatus, ti)');
        expect(src).not.toContain("=== 'skipped_stale_observation'");
    });
});
