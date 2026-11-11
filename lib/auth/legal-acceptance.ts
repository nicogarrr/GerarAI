import { createHash } from 'node:crypto';
import es from '../i18n/messages/es/landing.json' with { type: 'json' };
import en from '../i18n/messages/en/landing.json' with { type: 'json' };

// Content fingerprints, not a claim of legal validation. Both published languages
// belong to the same revision. Editing either document changes its version.
function version(esText: unknown, enText: unknown): string {
    return `sha256:${createHash('sha256').update(JSON.stringify([esText, enText])).digest('hex')}`;
}

export const LEGAL_TEXT_VERSIONS = {
    terms: version(es.terminos, en.terminos),
    privacy: version(es.privacidad, en.privacidad),
} as const;

export const LEGAL_ACCEPTANCE_REQUIRED_CODE = 'LEGAL_ACCEPTANCE_REQUIRED';

/** Only a real boolean checked by the user counts. Never coerce strings. */
export function hasLegalAcceptance(body: unknown): boolean {
    return body !== null && typeof body === 'object'
        && 'acceptTerms' in body && body.acceptTerms === true;
}

/** Server-owned fields, inserted atomically with the user, never backfilled. */
export function legalAcceptanceStamp(now = new Date()) {
    return {
        termsVersion: LEGAL_TEXT_VERSIONS.terms,
        privacyVersion: LEGAL_TEXT_VERSIONS.privacy,
        legalAcceptedAt: now,
    };
}
