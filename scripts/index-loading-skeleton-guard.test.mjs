import { existsSync } from 'node:fs';
import assert from 'node:assert/strict';
import { test } from 'node:test';

test('slow SSR index screens stream a skeleton instead of a blank page', () => {
    assert.ok(existsSync('app/(root)/watchlist/loading.tsx'));
    assert.ok(existsSync('app/(root)/research/loading.tsx'));
});
