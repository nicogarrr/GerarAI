import { describe, expect, it } from 'vitest';

import { backendMessage, spanishBackendMessage } from '@/lib/research/backend-error-es';

describe('backend messages follow the interface language', () => {
  it('Spanish stays exactly as before', () => {
    for (const raw of ['Holding not found', '500 Internal Server Error', 'insufficient shares for sale', 'plan_currency_required_for_amount_change', '']) {
      expect(backendMessage(raw, 'es')).toBe(spanishBackendMessage(raw));
    }
  });

  it('English shows readable engine text as a sentence', () => {
    expect(backendMessage('Holding not found', 'en')).toBe('Holding not found.');
    expect(backendMessage('insufficient shares for sale', 'en')).toBe('Insufficient shares for sale.');
    expect(backendMessage('Thesis generation failed (ref abc123)', 'en')).toBe('Thesis generation failed (ref abc123)');
  });

  it('English replaces status lines, internal codes and outages with a plain message', () => {
    expect(backendMessage('500 Internal Server Error', 'en')).toBe('The analysis engine is not responding right now. Retry in a few seconds.');
    expect(backendMessage('404 Not Found', 'en')).toMatch(/could not be found/);
    expect(backendMessage('429', 'en')).toBe('Too many requests. Wait a moment and retry.');
    expect(backendMessage('Research engine unavailable: timeout', 'en')).toMatch(/not responding/);
    expect(backendMessage('plan_currency_required_for_amount_change', 'en')).toBe('The operation could not be completed. Please retry.');
    expect(backendMessage('', 'en', 'Could not delete the document.')).toBe('Could not delete the document.');
  });

  it('Spanish engine text is never mangled in English', () => {
    expect(backendMessage('La colección no está vacía', 'en')).toBe('La colección no está vacía');
  });
});
