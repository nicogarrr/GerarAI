/**
 * Guard: el token `destructive-foreground` existe de verdad.
 *
 * components/ui/badge.tsx:16 declaraba `text-destructive-foreground`, pero
 * globals.css solo definía `--destructive` (y `--color-destructive`): la
 * clase no generaba color y un Badge destructive heredaría texto ilegible
 * sobre el rojo. Latente hoy (ningún consumidor), roto al primer uso.
 *
 * Ejecución: node --experimental-strip-types --test scripts/badge-destructive-token-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const badge = readFileSync('components/ui/badge.tsx', 'utf8');
const css = readFileSync('app/globals.css', 'utf8');

describe('badge destructive: token real', () => {
    it('la variante destructive usa el token', () => {
        assert.match(badge, /bg-destructive text-destructive-foreground/);
    });
    it('globals.css define --destructive-foreground y su mapeo --color-', () => {
        assert.match(css, /--destructive-foreground:\s*oklch\(/);
        assert.match(css, /--color-destructive-foreground:\s*var\(--destructive-foreground\)/);
    });
});
