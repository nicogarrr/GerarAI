import { describe, expect, it } from 'vitest';
import { isDisabledChatAvailabilityResponse } from '../../../e2e/user-flows/brain-request-classifier';

const disabled = { feature: 'chat', state: 'off', can_start: false, reason: 'disabled', retry_after_seconds: null };
const flight = (value: unknown) => `0:{"a":"$@1","b":"development"}\n1:D"$2"\n1:${JSON.stringify(value)}\n`;

describe('brain smoke server-action classification', () => {
    it('excludes the exact disabled availability response seen in the CI trace', () => {
        expect(isDisabledChatAvailabilityResponse(flight(disabled))).toBe(true);
    });
    it.each([
        { answer: 'Generated model answer', llm_trace: { model: 'synthetic' } },
        { ...disabled, answer: 'Generated model answer' },
        { ...disabled, can_start: true },
        { ...disabled, state: 'on' },
        { ...disabled, feature: 'research' },
        { ...disabled, reason: 'quota' },
        { ...disabled, retry_after_seconds: 60 },
        { feature: 'chat', state: 'off', can_start: false },
        null, [],
    ])('keeps actual generation and unknown results detectable: %j', (value) => {
        expect(isDisabledChatAvailabilityResponse(flight(value))).toBe(false);
    });
    it('does not let availability hide a second generated result', () => {
        expect(isDisabledChatAvailabilityResponse(`${flight(disabled)}2:{"answer":"generated"}\n`)).toBe(false);
    });
    it('does not let availability hide a second primitive result', () => {
        expect(isDisabledChatAvailabilityResponse(`${flight(disabled)}2:"generated"\n`)).toBe(false);
    });
    it.each(['', '<html>Error</html>', '1:{broken}', JSON.stringify(disabled)])('does not exclude unreadable or non-Flight results', (body) => {
        expect(isDisabledChatAvailabilityResponse(body)).toBe(false);
    });
});
