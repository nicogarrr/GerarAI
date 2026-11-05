import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { thesisIsPublic } from '@/lib/research/thesis-publication';

describe('single publication contract', () => {
    it('only the backend-published thesis is public', () => {
        expect(thesisIsPublic('published')).toBe(true);
        for (const status of ['approved', 'final', 'draft', 'review', 'changes_requested', '', null, undefined]) {
            expect(thesisIsPublic(status)).toBe(false);
        }
    });
    it('page and rating share the same predicate', () => {
        const page = readFileSync('app/(root)/research/[ticker]/page.tsx', 'utf8');
        const rating = readFileSync('lib/research/coverage-state.ts', 'utf8');
        expect(page).toContain("import { thesisIsPublic } from '@/lib/research/thesis-publication'");
        expect(page).not.toContain('function thesisIsPublic(');
        expect(rating).toContain("import { thesisIsPublic } from './thesis-publication.ts'");
    });
});
