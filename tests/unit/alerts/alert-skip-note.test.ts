import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

import { alertSkipNote } from '@/lib/alerts/skip-note';

describe('alertSkipNote', () => {
    it('explains a rule skipped because a trading session is missing (#3274)', () => {
        expect(alertSkipNote('skipped_session_gap')).toMatch(/falta una sesión/);
    });

    it('keeps the stale-observation note', () => {
        expect(alertSkipNote('skipped_stale_observation')).toBe('dato desactualizado');
    });

    it('adds nothing for a normal evaluation', () => {
        expect(alertSkipNote('ok')).toBeNull();
        expect(alertSkipNote(undefined)).toBeNull();
    });

    it('is what the alerts card renders for every skip status', () => {
        const src = readFileSync(join(process.cwd(), 'components/alerts/AlertsManager.tsx'), 'utf8');
        expect(src).toContain('alertSkipNote(alert.lastResultStatus)');
        expect(src).not.toContain("=== 'skipped_stale_observation'");
    });
});
