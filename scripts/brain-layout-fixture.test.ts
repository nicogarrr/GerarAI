import assert from 'node:assert/strict';
import test from 'node:test';
import { brainLayoutReply } from '../e2e/fixtures/brain-layout-actions.ts';

test('layout availability is deterministic for chat and library analysis only', () => {
    for (const feature of ['chat', 'analysis']) {
        assert.deepEqual(brainLayoutReply(JSON.stringify([feature])), {
            feature, state: 'unverified', can_start: true, reason: 'not_probed', retry_after_seconds: null,
        });
    }
    for (const body of [null, '', '{}', '["thesis"]', '["chat","other"]']) assert.equal(brainLayoutReply(body), undefined);
});
test('only the explicit long-message marker gets a local response; unrelated actions pass through', () => {
    assert.equal(brainLayoutReply('["question"]'), undefined);
    assert.equal(brainLayoutReply('["question"]', 'MARKER'), undefined);
    assert.deepEqual(brainLayoutReply('["long MARKER", "fixture-user", "page", []]', 'MARKER'), {
        success: true, message: 'Layout fixture response. No provider was called.',
    });
});
