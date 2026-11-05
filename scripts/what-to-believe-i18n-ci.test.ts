import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import test from 'node:test';

test('WhatToBelieve translation keys are visible to the unchanged i18n guard', () => {
    const output = execFileSync(process.execPath, ['scripts/check-i18n.mjs'], { encoding: 'utf8' });
    assert.match(output, /i18n ok:/);
});
